"""ADS-B aircraft tracker tab: launches rtl_adsb, decodes with pyModeS."""

from __future__ import annotations

import shutil
import subprocess
import time

import pyqtgraph as pg
from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QMessageBox, QHeaderView,
)

from .adsb_decoder import AdsbTracker


class RtlAdsbReader(QThread):
    """Runs the external `rtl_adsb` binary and emits each raw hex line."""

    message = Signal(str)
    error = Signal(str)
    started_ok = Signal()

    def __init__(self, device_index: int = 0, parent=None):
        super().__init__(parent)
        self.device_index = device_index
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
        exe = shutil.which("rtl_adsb")
        if not exe:
            self.error.emit(
                "rtl_adsb was not found on PATH. Install the rtl-sdr driver/tools "
                "package (e.g. 'apt install rtl-sdr', 'brew install librtlsdr', "
                "or the osmocom rtl-sdr Windows release) which provides rtl_adsb, "
                "and make sure it is on your PATH."
            )
            return

        cmd = [exe, "-d", str(self.device_index), "-R"]  # -R: raw output, no timestamps
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
            )
        except Exception as exc:
            self.error.emit(f"Could not start rtl_adsb: {exc}")
            return

        self._running = True
        self.started_ok.emit()
        try:
            assert self._proc.stdout is not None
            for line in self._proc.stdout:
                if not self._running:
                    break
                line = line.strip()
                if line:
                    self.message.emit(line)
        except Exception as exc:  # pragma: no cover
            self.error.emit(f"rtl_adsb read error: {exc}")
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


class AdsbTab(QWidget):
    OWNER = "adsb"

    COLUMNS = ["ICAO", "Callsign", "Altitude (ft)", "Speed (kt)", "Track (deg)",
               "V/S (fpm)", "Lat", "Lon", "Msgs", "Last seen (s)"]

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.reader: RtlAdsbReader | None = None
        self.tracker = AdsbTracker()

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.start_btn = QPushButton("Start ADS-B receiver")
        self.start_btn.setCheckable(True)
        self.start_btn.toggled.connect(self._on_toggle)
        controls.addWidget(self.start_btn)
        self.status_label = QLabel("Idle")
        controls.addWidget(self.status_label)
        controls.addStretch(1)
        root.addLayout(controls)

        body = QHBoxLayout()
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        body.addWidget(self.table, stretch=3)

        self.map_plot = pg.PlotWidget(title="Aircraft positions (lat/lon)")
        self.map_plot.setLabel("bottom", "Longitude")
        self.map_plot.setLabel("left", "Latitude")
        self.map_scatter = pg.ScatterPlotItem(size=8, brush=pg.mkBrush("#3fa7ff"))
        self.map_plot.addItem(self.map_scatter)
        body.addWidget(self.map_plot, stretch=2)
        root.addLayout(body)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(1000)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start()

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
            self.start_btn.setText("Stop ADS-B receiver")
            self.reader = RtlAdsbReader(device_index=self.hub.device_index)
            self.reader.message.connect(self._on_message)
            self.reader.error.connect(self._on_error)
            self.reader.started_ok.connect(lambda: self.status_label.setText("Listening for 1090 MHz ADS-B..."))
            self.reader.start()
            self.status_label.setText("Starting rtl_adsb...")
        else:
            self.start_btn.setText("Start ADS-B receiver")
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
        self.start_btn.setText("Start ADS-B receiver")
        self.start_btn.blockSignals(False)
        self._stop_reader()
        self.hub.release(self.OWNER)

    def _on_message(self, raw_line: str):
        # rtl_adsb raw format looks like "*8D4840D6202CC371C32CE0576098;"
        hexmsg = raw_line.strip().lstrip("*").rstrip(";").strip()
        self.tracker.feed_hex(hexmsg)

    def _refresh_table(self):
        self.tracker.prune()
        aircraft = sorted(self.tracker.aircraft.values(), key=lambda a: -a.last_seen)
        self.table.setRowCount(len(aircraft))
        lats, lons = [], []
        now = time.time()
        for row, ac in enumerate(aircraft):
            values = [
                ac.icao,
                ac.callsign or "",
                f"{ac.altitude:.0f}" if ac.altitude is not None else "",
                f"{ac.speed:.0f}" if ac.speed is not None else "",
                f"{ac.track:.0f}" if ac.track is not None else "",
                f"{ac.vertical_rate:.0f}" if ac.vertical_rate is not None else "",
                f"{ac.lat:.4f}" if ac.lat is not None else "",
                f"{ac.lon:.4f}" if ac.lon is not None else "",
                str(ac.messages),
                f"{now - ac.last_seen:.0f}",
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))
            if ac.lat is not None and ac.lon is not None:
                lats.append(ac.lat)
                lons.append(ac.lon)

        if lons and lats:
            self.map_scatter.setData(lons, lats)
        if self.start_btn.isChecked():
            self.status_label.setText(
                f"Listening... {len(aircraft)} aircraft tracked, "
                f"{self.tracker.valid_messages}/{self.tracker.total_messages} valid msgs"
            )

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_reader()
