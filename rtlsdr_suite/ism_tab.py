"""433/868 MHz ISM band scanner tab: launches rtl_433 and decodes its JSON output.

Covers common short-range devices such as weather stations, tyre pressure
monitors (TPMS), wireless doorbells/remote sockets, and many other ISM-band
sensors that rtl_433 already knows how to demodulate and decode.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView, QComboBox,
)

from .proc_utils import NO_WINDOW_KWARGS


class RtlPacket:
    """One decoded rtl_433 JSON record, kept around long enough to show in the table."""

    def __init__(self, data: dict):
        self.data = data
        self.model = data.get("model", "?")
        # rtl_433 identifies a physical device by some combination of model/id/channel;
        # use whatever subset is present so re-transmissions update the same row
        # instead of appending a new one every time.
        key_bits = [str(data.get(k)) for k in ("model", "id", "channel") if data.get(k) is not None]
        self.key = "|".join(key_bits) if key_bits else json.dumps(data, sort_keys=True)
        self.last_seen = time.time()
        self.count = 1

    def update(self, data: dict):
        self.data = data
        self.last_seen = time.time()
        self.count += 1


class Rtl433Reader(QThread):
    """Runs the external `rtl_433` binary and emits each decoded JSON record."""

    record = Signal(dict)
    error = Signal(str)
    started_ok = Signal()

    # Common preset frequencies for the EU/US ISM bands rtl_433 devices use.
    FREQ_PRESETS = {
        "433.92 MHz (EU, most common)": 433_920_000,
        "868.3 MHz (EU, wireless sensors)": 868_300_000,
        "315 MHz (US, TPMS/remotes)": 315_000_000,
        "915 MHz (US ISM)": 915_000_000,
    }

    def __init__(self, device_index: int = 0, freq_hz: float = 433_920_000, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.freq_hz = freq_hz
        self._proc: subprocess.Popen | None = None
        self._running = False

    def stop(self):
        self._running = False
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self):
        exe = shutil.which("rtl_433")
        if not exe:
            self.error.emit(
                "rtl_433 was not found on PATH. Download it from "
                "https://github.com/merbanan/rtl_433 (Windows builds are attached "
                "to each GitHub release) and add the folder to your PATH."
            )
            return

        cmd = [
            exe,
            "-d", str(self.device_index),
            "-f", str(int(self.freq_hz)),
            "-F", "json",
            "-M", "level",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                **NO_WINDOW_KWARGS,
            )
        except Exception as exc:
            self.error.emit(f"Could not start rtl_433: {exc}")
            return

        self._running = True
        self.started_ok.emit()
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if not self._running:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                self.record.emit(data)
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error.emit(f"rtl_433 read error: {exc}")
        finally:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=2)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
            self._proc = None


class IsmTab(QWidget):
    OWNER = "ism"

    COLUMNS = ["Model", "ID", "Channel", "Temp (C)", "Humidity (%)",
               "Battery", "Other fields", "Count", "Last seen (s)"]

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.reader: Rtl433Reader | None = None
        self.packets: dict[str, RtlPacket] = {}

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Frequency:"))
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(list(Rtl433Reader.FREQ_PRESETS.keys()))
        controls.addWidget(self.freq_combo)

        self.start_btn = QPushButton("Start ISM scanner")
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

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start()

    def _clear(self):
        self.packets.clear()
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
            freq_hz = Rtl433Reader.FREQ_PRESETS[self.freq_combo.currentText()]
            self.freq_combo.setEnabled(False)
            self.start_btn.setText("Stop ISM scanner")
            self.reader = Rtl433Reader(device_index=self.hub.device_index, freq_hz=freq_hz)
            self.reader.record.connect(self._on_record)
            self.reader.error.connect(self._on_error)
            self.reader.started_ok.connect(
                lambda: self.status_label.setText(f"Listening on {self.freq_combo.currentText()}...")
            )
            self.reader.start()
            self.status_label.setText("Starting rtl_433...")
        else:
            self.freq_combo.setEnabled(True)
            self.start_btn.setText("Start ISM scanner")
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
        self.start_btn.setText("Start ISM scanner")
        self.start_btn.blockSignals(False)
        self.freq_combo.setEnabled(True)
        self._stop_reader()
        self.hub.release(self.OWNER)

    def _on_record(self, data: dict):
        pkt = RtlPacket(data)
        existing = self.packets.get(pkt.key)
        if existing is not None:
            existing.update(data)
        else:
            self.packets[pkt.key] = pkt

    def _refresh_table(self):
        # drop entries that haven't been seen in a while so the table doesn't grow forever
        now = time.time()
        stale = [k for k, p in self.packets.items() if now - p.last_seen > 600]
        for k in stale:
            del self.packets[k]

        packets = sorted(self.packets.values(), key=lambda p: -p.last_seen)
        self.table.setRowCount(len(packets))
        known_keys = {"model", "id", "channel", "temperature_C", "humidity", "battery_ok", "time"}
        for row, pkt in enumerate(packets):
            d = pkt.data
            battery = d.get("battery_ok")
            battery_str = "" if battery is None else ("OK" if battery else "LOW")
            other = ", ".join(
                f"{k}={v}" for k, v in d.items() if k not in known_keys
            )
            values = [
                pkt.model,
                str(d.get("id", "")),
                str(d.get("channel", "")),
                f"{d['temperature_C']:.1f}" if "temperature_C" in d else "",
                f"{d['humidity']:.0f}" if "humidity" in d else "",
                battery_str,
                other,
                str(pkt.count),
                f"{now - pkt.last_seen:.0f}",
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))

        if self.start_btn.isChecked():
            self.status_label.setText(
                f"Listening on {self.freq_combo.currentText()}... {len(packets)} devices seen"
            )

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_reader()
