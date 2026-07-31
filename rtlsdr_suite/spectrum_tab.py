"""Spectrum + waterfall display tab."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox,
    QPushButton, QMessageBox,
)

from .dsp import power_spectrum_db
from .sdr_device import SdrWorker


class SpectrumTab(QWidget):
    """Live spectrum analyzer / waterfall for the RTL-SDR dongle."""

    OWNER = "spectrum"

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.worker: SdrWorker | None = None
        self.nfft = 2048
        self.waterfall_rows = 200
        self._waterfall = np.full((self.waterfall_rows, self.nfft), -120.0, dtype=np.float32)
        self._pending_iq = None

        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Center (MHz):"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(24.0, 1766.0)
        self.freq_spin.setDecimals(4)
        self.freq_spin.setSingleStep(0.1)
        self.freq_spin.setValue(100.0)
        self.freq_spin.valueChanged.connect(self._on_freq_changed)
        controls.addWidget(self.freq_spin)

        controls.addWidget(QLabel("Sample rate:"))
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(["2.048 MSps", "2.4 MSps", "1.024 MSps", "0.25 MSps"])
        controls.addWidget(self.rate_combo)

        controls.addWidget(QLabel("FFT size:"))
        self.fft_combo = QComboBox()
        self.fft_combo.addItems(["512", "1024", "2048", "4096", "8192"])
        self.fft_combo.setCurrentText("2048")
        self.fft_combo.currentTextChanged.connect(self._on_fft_change)
        controls.addWidget(self.fft_combo)

        controls.addWidget(QLabel("Gain:"))
        self.gain_combo = QComboBox()
        self.gain_combo.addItem("auto")
        for g in [0, 9, 14, 27, 37, 49]:
            self.gain_combo.addItem(str(g))
        controls.addWidget(self.gain_combo)

        self.start_btn = QPushButton("Start")
        self.start_btn.setCheckable(True)
        self.start_btn.toggled.connect(self._on_toggle)
        controls.addWidget(self.start_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.status_label = QLabel("Idle")
        root.addWidget(self.status_label)

        self.spectrum_plot = pg.PlotWidget(title="Spectrum")
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        self.spectrum_plot.setLabel("left", "Power", units="dB")
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen("y", width=1))
        root.addWidget(self.spectrum_plot, stretch=2)

        self.waterfall_plot = pg.PlotWidget(title="Waterfall")
        self.waterfall_img = pg.ImageItem()
        self.waterfall_plot.addItem(self.waterfall_img)
        self.waterfall_plot.setLabel("bottom", "Frequency bin")
        self.waterfall_plot.setLabel("left", "Time (newest column = latest)")
        cmap = pg.colormap.get("viridis")
        self.waterfall_img.setLookupTable(cmap.getLookupTable())
        root.addWidget(self.waterfall_plot, stretch=3)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(100)
        self._ui_timer.timeout.connect(self._update_plots)
        self._ui_timer.start()

    def _rate_hz(self) -> float:
        return float(self.rate_combo.currentText().split()[0]) * 1e6

    def _on_fft_change(self, text):
        self.nfft = int(text)
        self._waterfall = np.full((self.waterfall_rows, self.nfft), -120.0, dtype=np.float32)

    def _on_freq_changed(self, mhz):
        if self.worker is not None:
            self.worker.set_center_freq(mhz * 1e6)

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
            self.start_btn.setText("Stop")
            gain = self.gain_combo.currentText()
            gain_val = "auto" if gain == "auto" else float(gain)
            self.worker = SdrWorker(device_index=self.hub.device_index)
            self.worker.center_freq = self.freq_spin.value() * 1e6
            self.worker.sample_rate = self._rate_hz()
            self.worker.gain = gain_val
            self.worker.samples_ready.connect(self.on_samples)
            self.worker.error.connect(self._on_error)
            self.worker.device_opened.connect(lambda: self.status_label.setText("Streaming..."))
            self.worker.start()
            self.status_label.setText("Opening device...")
        else:
            self.start_btn.setText("Start")
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
        self.start_btn.setText("Start")
        self.start_btn.blockSignals(False)
        self._stop_worker()
        self.hub.release(self.OWNER)

    def on_samples(self, iq):
        self._pending_iq = iq

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_worker()

    def _update_plots(self):
        if self._pending_iq is None:
            return
        iq = self._pending_iq
        self._pending_iq = None
        db = power_spectrum_db(iq, self.nfft)
        rate = self._rate_hz()
        freqs = np.fft.fftshift(np.fft.fftfreq(len(db), d=1.0 / rate)) + self.freq_spin.value() * 1e6
        self.spectrum_curve.setData(freqs, db)

        self._waterfall = np.roll(self._waterfall, -1, axis=0)
        if len(db) == self._waterfall.shape[1]:
            self._waterfall[-1, :] = db
        self.waterfall_img.setImage(self._waterfall.T, autoLevels=False, levels=(-110, -20))
