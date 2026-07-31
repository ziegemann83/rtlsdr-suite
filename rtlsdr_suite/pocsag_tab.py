"""POCSAG pager decoder tab.

Pipes `rtl_fm` (raw FM-demodulated audio) into `multimon-ng` (POCSAG512/1200/2400
decoder), the same way the ADS-B tab shells out to `rtl_adsb` and the ISM tab
shells out to `rtl_433`: the demodulation/decoding itself is handled by a
battle-tested external C tool rather than re-implemented in Python (BCH error
correction and bit-sync recovery for POCSAG are fiddly to get right, and
multimon-ng already does it well).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView, QComboBox,
)

from .proc_utils import NO_WINDOW_KWARGS

# multimon-ng prints lines like:
#   POCSAG512: Address: 1234567  Function: 0  Alpha:   Hello world
#   POCSAG1200: Address: 1234567  Function: 3  Numeric: 123-456
_LINE_RE = re.compile(
    r"^(?P<proto>POCSAG\d+):\s*Address:\s*(?P<address>\d+)\s*"
    r"Function:\s*(?P<function>\d+)\s*(?P<kind>Alpha|Numeric):\s*(?P<text>.*)$"
)


class PocsagMessage:
    def __init__(self, proto: str, address: str, function: str, kind: str, text: str):
        self.proto = proto
        self.address = address
        self.function = function
        self.kind = kind
        self.text = text
        self.timestamp = time.time()


class PocsagReader(QThread):
    """Runs `rtl_fm | multimon-ng` and emits each decoded pager message."""

    message = Signal(object)
    error = Signal(str)
    started_ok = Signal()

    FREQ_PRESETS = {
        "439.9875 MHz (EU POCSAG, common)": 439_987_500,
        "466.230 MHz (EU/DE Cityruf legacy)": 466_230_000,
        "929.6625 MHz (US paging, common)": 929_662_500,
    }

    def __init__(self, device_index: int = 0, freq_hz: float = 439_987_500, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.freq_hz = freq_hz
        self._rtl_fm: subprocess.Popen | None = None
        self._multimon: subprocess.Popen | None = None
        self._running = False

    def stop(self):
        self._running = False
        for proc in (self._multimon, self._rtl_fm):
            if proc is not None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def run(self):
        rtl_fm_exe = shutil.which("rtl_fm")
        multimon_exe = shutil.which("multimon-ng")
        missing = [name for name, exe in (("rtl_fm", rtl_fm_exe), ("multimon-ng", multimon_exe)) if not exe]
        if missing:
            self.error.emit(
                f"{' and '.join(missing)} not found on PATH. rtl_fm ships with the "
                "rtl-sdr tools (already used by the ADS-B tab); multimon-ng can be "
                "downloaded from https://github.com/EliasOenal/multimon-ng "
                "(Windows builds are attached to releases). Add both to your PATH."
            )
            return

        rtl_fm_cmd = [
            rtl_fm_exe,
            "-d", str(self.device_index),
            "-f", str(int(self.freq_hz)),
            "-M", "fm",
            "-s", "22050",
            "-",
        ]
        multimon_cmd = [
            multimon_exe,
            "-a", "POCSAG512",
            "-a", "POCSAG1200",
            "-a", "POCSAG2400",
            "-t", "raw",
            "-f", "alpha",
            "-",
        ]
        try:
            self._rtl_fm = subprocess.Popen(
                rtl_fm_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                **NO_WINDOW_KWARGS,
            )
            self._multimon = subprocess.Popen(
                multimon_cmd, stdin=self._rtl_fm.stdout, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
                **NO_WINDOW_KWARGS,
            )
            # allow rtl_fm to receive SIGPIPE if multimon-ng exits first
            if self._rtl_fm.stdout is not None:
                self._rtl_fm.stdout.close()
        except Exception as exc:
            self.error.emit(f"Could not start rtl_fm/multimon-ng pipeline: {exc}")
            return

        self._running = True
        self.started_ok.emit()
        try:
            assert self._multimon.stdout is not None
            for line in self._multimon.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                m = _LINE_RE.match(line)
                if not m:
                    continue
                msg = PocsagMessage(
                    proto=m.group("proto"),
                    address=m.group("address"),
                    function=m.group("function"),
                    kind=m.group("kind"),
                    text=m.group("text").strip(),
                )
                self.message.emit(msg)
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error.emit(f"multimon-ng read error: {exc}")
        finally:
            for proc in (self._multimon, self._rtl_fm):
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            self._rtl_fm = None
            self._multimon = None


class PocsagTab(QWidget):
    OWNER = "pocsag"

    COLUMNS = ["Time", "Protocol", "Address", "Function", "Type", "Message"]
    MAX_ROWS = 500

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.reader: PocsagReader | None = None
        self._rows: list[PocsagMessage] = []

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Frequency:"))
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(list(PocsagReader.FREQ_PRESETS.keys()))
        controls.addWidget(self.freq_combo)

        self.start_btn = QPushButton("Start POCSAG decoder")
        self.start_btn.setCheckable(True)
        self.start_btn.toggled.connect(self._on_toggle)
        controls.addWidget(self.start_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self._clear)
        controls.addWidget(self.clear_btn)

        self.status_label = QLabel("Idle")
        controls.addWidget(self.status_label)
        controls.addStretch(1)
        root.addLayout(controls)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table)

    def _clear(self):
        self._rows.clear()
        self.table.setRowCount(0)

    def _on_toggle(self, checked):
        if checked:
            if not self.hub.try_acquire(self.OWNER):
                QMessageBox.warning(
                    self, "Device busy",
                    "The RTL-SDR is already in use by another tab. Stop it there first."
                )
                self.start_btn.blockSignals(True)
                self.start_btn.setChecked(False)
                self.start_btn.blockSignals(False)
                return
            freq_hz = PocsagReader.FREQ_PRESETS[self.freq_combo.currentText()]
            self.freq_combo.setEnabled(False)
            self.start_btn.setText("Stop POCSAG decoder")
            self.reader = PocsagReader(device_index=self.hub.device_index, freq_hz=freq_hz)
            self.reader.message.connect(self._on_message)
            self.reader.error.connect(self._on_error)
            self.reader.started_ok.connect(
                lambda: self.status_label.setText(f"Listening on {self.freq_combo.currentText()}...")
            )
            self.reader.start()
            self.status_label.setText("Starting rtl_fm | multimon-ng...")
        else:
            self.freq_combo.setEnabled(True)
            self.start_btn.setText("Start POCSAG decoder")
            self._stop_reader()
            self.status_label.setText("Idle")
            self.hub.release(self.OWNER)

    def _stop_reader(self):
        if self.reader is not None:
            self.reader.stop()
            self.reader.wait(2000)
            self.reader = None

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.setText("Start POCSAG decoder")
        self.start_btn.blockSignals(False)
        self.freq_combo.setEnabled(True)
        self._stop_reader()
        self.hub.release(self.OWNER)

    def _on_message(self, msg: PocsagMessage):
        self._rows.insert(0, msg)
        self._rows = self._rows[: self.MAX_ROWS]
        self.table.setRowCount(len(self._rows))
        for row, m in enumerate(self._rows):
            values = [
                time.strftime("%H:%M:%S", time.localtime(m.timestamp)),
                m.proto,
                m.address,
                m.function,
                m.kind,
                m.text,
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
        if self.start_btn.isChecked():
            self.status_label.setText(
                f"Listening on {self.freq_combo.currentText()}... {len(self._rows)} messages"
            )

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_reader()
