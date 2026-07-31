"""NOAA weather satellite (APT) tab: live-decodes a pass into a grayscale image."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QMessageBox, QFileDialog,
)

from .apt_decoder import AptDecoder, LINE_WIDTH
from .sdr_device import SdrWorker


class AptTab(QWidget):
    OWNER = "apt"

    # NOAA satellites all transmit APT around 137 MHz; exact assignment drifts
    # over time as satellites are retired, so all three are offered.
    FREQ_PRESETS = {
        "NOAA-15 (137.6200 MHz)": 137_620_000,
        "NOAA-18 (137.9125 MHz)": 137_912_500,
        "NOAA-19 (137.1000 MHz)": 137_100_000,
    }

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.worker: SdrWorker | None = None
        self.decoder: AptDecoder | None = None

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Satellite:"))
        self.freq_combo = QComboBox()
        self.freq_combo.addItems(list(self.FREQ_PRESETS.keys()))
        controls.addWidget(self.freq_combo)

        self.start_btn = QPushButton("Start APT decode")
        self.start_btn.setCheckable(True)
        self.start_btn.toggled.connect(self._on_toggle)
        controls.addWidget(self.start_btn)

        self.save_btn = QPushButton("Save PNG...")
        self.save_btn.clicked.connect(self._save_png)
        controls.addWidget(self.save_btn)

        self.status_label = QLabel("Idle")
        controls.addWidget(self.status_label)
        controls.addStretch(1)
        root.addLayout(controls)

        root.addWidget(QLabel(
            "Antenna needs a reasonably clear view of the sky; a satellite pass "
            "lasts roughly 10-15 minutes. Point-and-shoot: this shows the raw, "
            "uncropped 2080 px wide APT frame (channel A + B + telemetry side "
            "by side), not a calibrated/enhanced product."
        ))

        self.image_label = QLabel("No image yet")
        self.image_label.setMinimumHeight(300)
        self.image_label.setScaledContents(False)
        root.addWidget(self.image_label, stretch=1)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(1000)
        self._ui_timer.timeout.connect(self._refresh_image)
        self._ui_timer.start()

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
            freq_hz = self.FREQ_PRESETS[self.freq_combo.currentText()]
            rate_hz = 250_000.0  # generous margin around the ~34 kHz APT channel bandwidth
            self.freq_combo.setEnabled(False)
            self.start_btn.setText("Stop APT decode")
            self.decoder = AptDecoder(iq_sample_rate=rate_hz)
            self.worker = SdrWorker(device_index=self.hub.device_index)
            self.worker.center_freq = freq_hz
            self.worker.sample_rate = rate_hz
            self.worker.gain = "auto"
            self.worker.samples_ready.connect(self._on_samples)
            self.worker.error.connect(self._on_error)
            self.worker.device_opened.connect(lambda: self.status_label.setText("Receiving pass..."))
            self.worker.start()
            self.status_label.setText("Opening device...")
        else:
            self.freq_combo.setEnabled(True)
            self.start_btn.setText("Start APT decode")
            self._stop_worker()
            self.status_label.setText("Idle")
            self.hub.release(self.OWNER)

    def _stop_worker(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.setText("Start APT decode")
        self.start_btn.blockSignals(False)
        self.freq_combo.setEnabled(True)
        self._stop_worker()
        self.hub.release(self.OWNER)

    def _on_samples(self, iq):
        if self.decoder is not None:
            self.decoder.feed(iq)

    def _refresh_image(self):
        if self.decoder is None or not self.decoder.rows:
            return
        img = self.decoder.image()
        h, w = img.shape
        qimg = QImage(img.tobytes(), w, h, w, QImage.Format_Grayscale8)
        pix = QPixmap.fromImage(qimg)
        target_w = max(self.image_label.width(), LINE_WIDTH // 2)
        scaled = pix.scaledToWidth(min(target_w, LINE_WIDTH), Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        if self.start_btn.isChecked():
            self.status_label.setText(f"Receiving pass... {h} lines decoded ({h / 2:.0f} s)")

    def _save_png(self):
        if self.decoder is None or not self.decoder.rows:
            QMessageBox.information(self, "No image", "Nothing decoded yet.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save APT image", "noaa_apt.png", "PNG files (*.png)")
        if not path:
            return
        self.decoder.save_png(path)

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_worker()
