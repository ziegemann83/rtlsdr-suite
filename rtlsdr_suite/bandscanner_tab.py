"""Band scanner / activity logger tab.

Sweeps a configurable frequency range in fixed steps, measures the signal
power at each step, and logs every step whose power exceeds a threshold.
Useful for mapping out which frequencies are actually in use in your area
before pointing one of the other tabs at a specific channel.
"""

from __future__ import annotations

import csv
import time

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSpinBox,
    QComboBox, QPushButton, QMessageBox, QFileDialog, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from .sdr_device import SdrWorker

SCAN_SAMPLE_RATE = 250_000.0  # narrow-ish per-step bandwidth, keeps steps meaningful


class LogEntry:
    __slots__ = ("timestamp", "freq_mhz", "power_db")

    def __init__(self, timestamp: float, freq_mhz: float, power_db: float):
        self.timestamp = timestamp
        self.freq_mhz = freq_mhz
        self.power_db = power_db


class BandScannerTab(QWidget):
    OWNER = "bandscan"
    MAX_LOG_ROWS = 2000

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.worker: SdrWorker | None = None
        self._freqs_hz: list[float] = []
        self._freq_index = 0
        self._dwell_power_db = -999.0
        self._log: list[LogEntry] = []

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("From (MHz):"))
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(24.0, 1766.0)
        self.start_spin.setDecimals(3)
        self.start_spin.setValue(430.0)
        controls.addWidget(self.start_spin)

        controls.addWidget(QLabel("To (MHz):"))
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(24.0, 1766.0)
        self.end_spin.setDecimals(3)
        self.end_spin.setValue(440.0)
        controls.addWidget(self.end_spin)

        controls.addWidget(QLabel("Step (kHz):"))
        self.step_spin = QSpinBox()
        self.step_spin.setRange(5, 10000)
        self.step_spin.setValue(25)
        controls.addWidget(self.step_spin)

        controls.addWidget(QLabel("Dwell (ms):"))
        self.dwell_spin = QSpinBox()
        self.dwell_spin.setRange(50, 5000)
        self.dwell_spin.setValue(150)
        controls.addWidget(self.dwell_spin)

        controls.addWidget(QLabel("Threshold (dB):"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(-120, 0)
        self.threshold_spin.setValue(-25)
        controls.addWidget(self.threshold_spin)

        root.addLayout(controls)

        controls2 = QHBoxLayout()
        controls2.addWidget(QLabel("Gain:"))
        self.gain_combo = QComboBox()
        self.gain_combo.addItem("auto")
        for g in [0, 9, 14, 27, 37, 49]:
            self.gain_combo.addItem(str(g))
        controls2.addWidget(self.gain_combo)

        self.loop_check = QCheckBox("Loop continuously")
        self.loop_check.setChecked(True)
        controls2.addWidget(self.loop_check)

        self.start_btn = QPushButton("Start scan")
        self.start_btn.setCheckable(True)
        self.start_btn.toggled.connect(self._on_toggle)
        controls2.addWidget(self.start_btn)

        self.clear_btn = QPushButton("Clear log")
        self.clear_btn.clicked.connect(self._clear_log)
        controls2.addWidget(self.clear_btn)

        self.export_btn = QPushButton("Export CSV...")
        self.export_btn.clicked.connect(self._export_csv)
        controls2.addWidget(self.export_btn)

        self.status_label = QLabel("Idle")
        controls2.addWidget(self.status_label)
        controls2.addStretch(1)
        root.addLayout(controls2)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Frequency (MHz)", "Power (dB)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        root.addWidget(self.table)

        self._scan_timer = QTimer(self)
        self._scan_timer.timeout.connect(self._hop)

    def _clear_log(self):
        self._log.clear()
        self.table.setRowCount(0)

    def _build_freq_list(self) -> list[float]:
        start = self.start_spin.value()
        end = self.end_spin.value()
        step_mhz = self.step_spin.value() / 1000.0
        if end <= start or step_mhz <= 0:
            return []
        freqs = []
        f = start
        while f <= end + 1e-9:
            freqs.append(round(f, 6))
            f += step_mhz
        return freqs

    def _on_toggle(self, checked):
        if checked:
            freqs_mhz = self._build_freq_list()
            if not freqs_mhz:
                QMessageBox.warning(self, "Invalid range", "'To' must be greater than 'From'.")
                self.start_btn.blockSignals(True)
                self.start_btn.setChecked(False)
                self.start_btn.blockSignals(False)
                return
            if not self.hub.try_acquire(self.OWNER):
                QMessageBox.warning(
                    self, "Device busy",
                    "The RTL-SDR is already in use by another tab. Stop it there first."
                )
                self.start_btn.blockSignals(True)
                self.start_btn.setChecked(False)
                self.start_btn.blockSignals(False)
                return
            self._freqs_hz = [f * 1e6 for f in freqs_mhz]
            self._freq_index = 0
            self._dwell_power_db = -999.0
            self.start_btn.setText("Stop scan")
            gain = self.gain_combo.currentText()
            gain_val = "auto" if gain == "auto" else float(gain)
            self.worker = SdrWorker(device_index=self.hub.device_index)
            self.worker.center_freq = self._freqs_hz[0]
            self.worker.sample_rate = SCAN_SAMPLE_RATE
            self.worker.gain = gain_val
            self.worker.samples_ready.connect(self._on_samples)
            self.worker.error.connect(self._on_error)
            self.worker.device_opened.connect(self._on_device_opened)
            self.worker.start()
            self.status_label.setText("Opening device...")
        else:
            self.start_btn.setText("Start scan")
            self._stop_all()
            self.status_label.setText("Idle")
            self.hub.release(self.OWNER)

    def _on_device_opened(self):
        self._scan_timer.start(self.dwell_spin.value())
        self.status_label.setText(f"Scanning {self.start_spin.value():.3f}-{self.end_spin.value():.3f} MHz...")

    def _stop_all(self):
        self._scan_timer.stop()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.setText("Start scan")
        self.start_btn.blockSignals(False)
        self._stop_all()
        self.hub.release(self.OWNER)

    def _on_samples(self, iq):
        power_db = 10.0 * np.log10(float(np.mean(np.abs(iq) ** 2)) + 1e-20)
        self._dwell_power_db = max(self._dwell_power_db, power_db)

    def _hop(self):
        if self.worker is None or not self._freqs_hz:
            return
        current_freq_mhz = self._freqs_hz[self._freq_index] / 1e6
        if self._dwell_power_db >= self.threshold_spin.value():
            self._log_hit(current_freq_mhz, self._dwell_power_db)

        self._freq_index += 1
        if self._freq_index >= len(self._freqs_hz):
            if self.loop_check.isChecked():
                self._freq_index = 0
            else:
                self.start_btn.setChecked(False)
                return
        self._dwell_power_db = -999.0
        next_freq = self._freqs_hz[self._freq_index]
        self.worker.set_center_freq(next_freq)
        self.status_label.setText(
            f"Scanning... {next_freq / 1e6:.4f} MHz "
            f"({self._freq_index + 1}/{len(self._freqs_hz)}), {len(self._log)} hits logged"
        )

    def _log_hit(self, freq_mhz: float, power_db: float):
        entry = LogEntry(time.time(), freq_mhz, power_db)
        self._log.insert(0, entry)
        self._log = self._log[: self.MAX_LOG_ROWS]
        self.table.setRowCount(len(self._log))
        for row, e in enumerate(self._log):
            values = [
                time.strftime("%H:%M:%S", time.localtime(e.timestamp)),
                f"{e.freq_mhz:.4f}",
                f"{e.power_db:.1f}",
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(val))

    def _export_csv(self):
        if not self._log:
            QMessageBox.information(self, "Nothing to export", "No hits logged yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export scan log", "bandscan.csv", "CSV files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "time", "frequency_mhz", "power_db"])
            for e in reversed(self._log):  # chronological order in the file
                writer.writerow([
                    e.timestamp,
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp)),
                    f"{e.freq_mhz:.6f}",
                    f"{e.power_db:.1f}",
                ])

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_all()
