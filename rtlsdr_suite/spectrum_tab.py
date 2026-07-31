"""Spectrum + waterfall display tab."""

from __future__ import annotations

import json
import os

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox,
    QPushButton, QMessageBox, QFileDialog, QCheckBox, QSpinBox,
)

from .dsp import power_spectrum_db
from .sdr_device import SdrWorker
from .settings import get_settings

# IQ recordings are raw interleaved float32 I/Q (i.e. numpy complex64, native
# byte order) with a small JSON sidecar carrying the capture metadata needed
# to play it back meaningfully (center frequency, sample rate).
IQ_RECORD_CHUNK_SAMPLES = 65536


class SpectrumTab(QWidget):
    """Live spectrum analyzer / waterfall for the RTL-SDR dongle."""

    OWNER = "spectrum"

    #: emitted (freq_mhz) when the user clicks on the spectrum plot to tune there
    tune_requested = Signal(float)

    # (center MHz, sample rate label) presets for bands this dongle can usefully look at.
    # The 868/915 MHz LoRa/Meshtastic entries only make the chirp activity *visible* in
    # the spectrum/waterfall - a stock RTL-SDR (no precision TCXO, ~3.2 MSps max bandwidth)
    # cannot demodulate LoRa's chirp spread spectrum packets, so there is no decode here,
    # just "is something transmitting right now and where".
    PRESETS = {
        "-- select preset --": None,
        "FM Broadcast (100 MHz)": (100.0, "2.048 MSps"),
        "Airband voice (124 MHz)": (124.0, "2.048 MSps"),
        "ADS-B (1090 MHz)": (1090.0, "2.4 MSps"),
        "433 MHz ISM (rtl_433 devices)": (433.92, "2.048 MSps"),
        "868 MHz EU LoRa/Meshtastic (view only)": (868.5, "2.048 MSps"),
        "915 MHz US LoRa/Meshtastic (view only)": (915.0, "2.4 MSps"),
        "POCSAG pager (439.9875 MHz)": (439.9875, "0.25 MSps"),
    }

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.worker: SdrWorker | None = None
        self.nfft = 2048
        self.waterfall_rows = 200
        self._waterfall = np.full((self.waterfall_rows, self.nfft), -120.0, dtype=np.float32)
        self._pending_iq = None

        # -- IQ raw recording --
        self._iq_record_file = None  # binary file handle
        self._recording_iq = False

        # -- IQ playback (no hardware involved) --
        self._playback_file = None
        self._playback_rate_hz = None
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(100)
        self._playback_timer.timeout.connect(self._playback_tick)

        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(self.PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        controls.addWidget(self.preset_combo)

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

        controls_iq = QHBoxLayout()
        self.record_iq_btn = QPushButton("Record IQ...")
        self.record_iq_btn.setCheckable(True)
        self.record_iq_btn.toggled.connect(self._on_record_iq_toggled)
        controls_iq.addWidget(self.record_iq_btn)

        self.playback_btn = QPushButton("Play back file...")
        self.playback_btn.setCheckable(True)
        self.playback_btn.toggled.connect(self._on_playback_toggled)
        controls_iq.addWidget(self.playback_btn)

        self.playback_loop_check = QCheckBox("Loop")
        controls_iq.addWidget(self.playback_loop_check)
        controls_iq.addStretch(1)
        root.addLayout(controls_iq)

        self.status_label = QLabel("Idle")
        root.addWidget(self.status_label)

        self.spectrum_plot = pg.PlotWidget(title="Spectrum")
        self.spectrum_plot.setLabel("bottom", "Frequency", units="Hz")
        self.spectrum_plot.setLabel("left", "Power", units="dB")
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen("y", width=1))
        root.addWidget(self.spectrum_plot, stretch=2)

        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Waterfall min (dB):"))
        self.level_min_spin = QSpinBox()
        self.level_min_spin.setRange(-140, 0)
        self.level_min_spin.setValue(-110)
        self.level_min_spin.valueChanged.connect(self._on_levels_changed)
        color_row.addWidget(self.level_min_spin)
        color_row.addWidget(QLabel("max (dB):"))
        self.level_max_spin = QSpinBox()
        self.level_max_spin.setRange(-100, 20)
        self.level_max_spin.setValue(-20)
        self.level_max_spin.valueChanged.connect(self._on_levels_changed)
        color_row.addWidget(self.level_max_spin)
        color_row.addWidget(QLabel("(Klick ins Spektrum stimmt den Empfänger auf diese Frequenz ab)"))
        color_row.addStretch(1)
        root.addLayout(color_row)

        self.waterfall_plot = pg.PlotWidget(title="Waterfall")
        self.waterfall_img = pg.ImageItem()
        self.waterfall_plot.addItem(self.waterfall_img)
        self.waterfall_plot.setLabel("bottom", "Frequency bin")
        self.waterfall_plot.setLabel("left", "Time (newest column = latest)")
        cmap = pg.colormap.get("viridis")
        self.waterfall_img.setLookupTable(cmap.getLookupTable())
        root.addWidget(self.waterfall_plot, stretch=3)

        self.spectrum_plot.scene().sigMouseClicked.connect(self._on_plot_clicked)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(100)
        self._ui_timer.timeout.connect(self._update_plots)
        self._ui_timer.start()

        self._load_settings()

    def _rate_hz(self) -> float:
        return float(self.rate_combo.currentText().split()[0]) * 1e6

    def _on_fft_change(self, text):
        self.nfft = int(text)
        self._waterfall = np.full((self.waterfall_rows, self.nfft), -120.0, dtype=np.float32)

    def _on_freq_changed(self, mhz):
        if self.worker is not None:
            self.worker.set_center_freq(mhz * 1e6)

    def _on_preset_changed(self, name):
        preset = self.PRESETS.get(name)
        if preset is None:
            return
        freq_mhz, rate_label = preset
        self.freq_spin.setValue(freq_mhz)  # triggers _on_freq_changed if already streaming
        if self.rate_combo.findText(rate_label) >= 0:
            self.rate_combo.setCurrentText(rate_label)
        if self.worker is not None:
            self.worker.set_sample_rate(self._rate_hz())

    def _on_levels_changed(self, _value):
        pass  # levels are read directly from the spinboxes in _update_plots

    def _on_plot_clicked(self, event):
        if not self.spectrum_plot.sceneBoundingRect().contains(event.scenePos()):
            return
        view_point = self.spectrum_plot.getPlotItem().vb.mapSceneToView(event.scenePos())
        freq_hz = view_point.x()
        freq_mhz = freq_hz / 1e6
        if not (24.0 <= freq_mhz <= 1766.0):
            return
        self.freq_spin.setValue(freq_mhz)
        self.tune_requested.emit(freq_mhz)

    def _load_settings(self):
        s = get_settings()
        self.freq_spin.setValue(float(s.value("spectrum/freq_mhz", 100.0)))
        rate_text = s.value("spectrum/rate", "2.048 MSps")
        idx = self.rate_combo.findText(rate_text)
        if idx >= 0:
            self.rate_combo.setCurrentIndex(idx)
        fft_text = s.value("spectrum/fft", "2048")
        idx = self.fft_combo.findText(fft_text)
        if idx >= 0:
            self.fft_combo.setCurrentIndex(idx)
        gain_text = s.value("spectrum/gain", "auto")
        idx = self.gain_combo.findText(gain_text)
        if idx >= 0:
            self.gain_combo.setCurrentIndex(idx)
        self.level_min_spin.setValue(int(s.value("spectrum/level_min_db", -110)))
        self.level_max_spin.setValue(int(s.value("spectrum/level_max_db", -20)))

    def save_settings(self):
        s = get_settings()
        s.setValue("spectrum/freq_mhz", self.freq_spin.value())
        s.setValue("spectrum/rate", self.rate_combo.currentText())
        s.setValue("spectrum/fft", self.fft_combo.currentText())
        s.setValue("spectrum/gain", self.gain_combo.currentText())
        s.setValue("spectrum/level_min_db", self.level_min_spin.value())
        s.setValue("spectrum/level_max_db", self.level_max_spin.value())

    def _on_toggle(self, checked):
        if checked:
            if self.playback_btn.isChecked():
                QMessageBox.information(self, "Stop playback first",
                                         "Stop the IQ file playback before starting a live capture.")
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
        if self.record_iq_btn.isChecked():
            self.record_iq_btn.setChecked(False)

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
        if self._recording_iq and self._iq_record_file is not None:
            np.asarray(iq, dtype=np.complex64).tofile(self._iq_record_file)

    # -- IQ raw recording --
    def _on_record_iq_toggled(self, checked):
        if checked:
            if self.worker is None:
                QMessageBox.information(self, "Not streaming",
                                         "Click 'Start' first so there is a live IQ stream to record.")
                self.record_iq_btn.blockSignals(True)
                self.record_iq_btn.setChecked(False)
                self.record_iq_btn.blockSignals(False)
                return
            path, _ = QFileDialog.getSaveFileName(self, "Record raw IQ", "capture.cf32", "Raw IQ (*.cf32)")
            if not path:
                self.record_iq_btn.blockSignals(True)
                self.record_iq_btn.setChecked(False)
                self.record_iq_btn.blockSignals(False)
                return
            try:
                self._iq_record_file = open(path, "wb")
            except Exception as exc:
                QMessageBox.warning(self, "Could not open file", str(exc))
                self.record_iq_btn.blockSignals(True)
                self.record_iq_btn.setChecked(False)
                self.record_iq_btn.blockSignals(False)
                return
            meta = {
                "format": "complex64 (interleaved float32 I/Q, native byte order)",
                "center_freq_hz": self.freq_spin.value() * 1e6,
                "sample_rate_hz": self._rate_hz(),
            }
            try:
                with open(path + ".json", "w") as f:
                    json.dump(meta, f, indent=2)
            except Exception:
                pass
            self._recording_iq = True
            self.record_iq_btn.setText("Stop recording IQ")
        else:
            self._recording_iq = False
            self.record_iq_btn.setText("Record IQ...")
            if self._iq_record_file is not None:
                self._iq_record_file.close()
                self._iq_record_file = None

    # -- IQ playback (reads a .cf32 capture back in, no hardware needed) --
    def _on_playback_toggled(self, checked):
        if checked:
            if self.start_btn.isChecked():
                QMessageBox.information(self, "Stop live capture first",
                                         "Stop the live 'Start' capture before playing back a file.")
                self.playback_btn.blockSignals(True)
                self.playback_btn.setChecked(False)
                self.playback_btn.blockSignals(False)
                return
            path, _ = QFileDialog.getOpenFileName(self, "Play back raw IQ", "", "Raw IQ (*.cf32);;All files (*)")
            if not path:
                self.playback_btn.blockSignals(True)
                self.playback_btn.setChecked(False)
                self.playback_btn.blockSignals(False)
                return
            rate_hz = self._rate_hz()
            freq_mhz = self.freq_spin.value()
            meta_path = path + ".json"
            if os.path.exists(meta_path):
                try:
                    with open(meta_path) as f:
                        meta = json.load(f)
                    rate_hz = float(meta.get("sample_rate_hz", rate_hz))
                    freq_mhz = float(meta.get("center_freq_hz", freq_mhz * 1e6)) / 1e6
                    self.freq_spin.setValue(freq_mhz)
                    label = f"{rate_hz / 1e6:.3f} MSps"
                    if self.rate_combo.findText(label) < 0:
                        self.rate_combo.addItem(label)
                    self.rate_combo.setCurrentText(label)
                except Exception:
                    pass
            try:
                self._playback_file = open(path, "rb")
            except Exception as exc:
                QMessageBox.warning(self, "Could not open file", str(exc))
                self.playback_btn.blockSignals(True)
                self.playback_btn.setChecked(False)
                self.playback_btn.blockSignals(False)
                return
            self._playback_rate_hz = rate_hz
            self.start_btn.setEnabled(False)
            self.playback_btn.setText("Stop playback")
            self.status_label.setText(f"Playing back {os.path.basename(path)}...")
            self._playback_timer.start()
        else:
            self._stop_playback()
            self.status_label.setText("Idle")

    def _stop_playback(self):
        self._playback_timer.stop()
        if self._playback_file is not None:
            self._playback_file.close()
            self._playback_file = None
        self.start_btn.setEnabled(True)
        self.playback_btn.setText("Play back file...")

    def _playback_tick(self):
        if self._playback_file is None or self._playback_rate_hz is None:
            return
        chunk = np.fromfile(self._playback_file, dtype=np.complex64, count=IQ_RECORD_CHUNK_SAMPLES)
        if len(chunk) == 0:
            if self.playback_loop_check.isChecked():
                self._playback_file.seek(0)
                chunk = np.fromfile(self._playback_file, dtype=np.complex64, count=IQ_RECORD_CHUNK_SAMPLES)
            if len(chunk) == 0:
                self.playback_btn.setChecked(False)  # end of file, not looping
                return
        # feed the same rendering path _update_plots() uses for a live worker
        self._pending_iq = chunk
        self.status_label.setText(
            f"Playing back... {self._playback_rate_hz / 1e6:.3f} MSps @ {self.freq_spin.value():.4f} MHz"
        )

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_worker()
        self._stop_playback()
        if self._iq_record_file is not None:
            self._iq_record_file.close()
            self._iq_record_file = None
        self.save_settings()

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
        self.waterfall_img.setImage(
            self._waterfall.T, autoLevels=False,
            levels=(self.level_min_spin.value(), self.level_max_spin.value()),
        )
