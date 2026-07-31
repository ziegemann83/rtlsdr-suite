"""General purpose receiver tab: WFM / NFM / AM / USB / LSB with audio out + recording."""

from __future__ import annotations

import time
import wave

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox,
    QPushButton, QSlider, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt

from .dsp import make_demodulator
from .sdr_device import SdrWorker
from .audio_out import AudioSink

AUDIO_RATE = 48000


class ReceiverTab(QWidget):
    OWNER = "receiver"

    def __init__(self, device_hub, parent=None):
        super().__init__(parent)
        self.hub = device_hub
        self.worker: SdrWorker | None = None
        self.demod = None
        self.audio_sink = AudioSink(sample_rate=AUDIO_RATE)
        self._recording = False
        self._wav_file: wave.Wave_write | None = None
        self._last_power_db = -120.0

        root = QVBoxLayout(self)
        controls = QHBoxLayout()

        controls.addWidget(QLabel("Frequency (MHz):"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(24.0, 1766.0)
        self.freq_spin.setDecimals(4)
        self.freq_spin.setSingleStep(0.001)
        self.freq_spin.setValue(100.0)
        self.freq_spin.valueChanged.connect(self._on_freq_changed)
        controls.addWidget(self.freq_spin)

        controls.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["WFM", "NFM", "AM", "USB", "LSB"])
        self.mode_combo.currentTextChanged.connect(self._on_mode_changed)
        controls.addWidget(self.mode_combo)

        controls.addWidget(QLabel("Sample rate:"))
        self.rate_combo = QComboBox()
        self.rate_combo.addItems(["2.048 MSps", "1.024 MSps", "0.25 MSps"])
        controls.addWidget(self.rate_combo)

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
        root.addLayout(controls)

        controls2 = QHBoxLayout()
        controls2.addWidget(QLabel("Volume:"))
        self.vol_slider = QSlider(Qt.Horizontal)
        self.vol_slider.setRange(0, 200)
        self.vol_slider.setValue(100)
        self.vol_slider.valueChanged.connect(lambda v: self.audio_sink.set_volume(v / 100.0))
        controls2.addWidget(self.vol_slider)

        controls2.addWidget(QLabel("Squelch (dB):"))
        self.squelch_slider = QSlider(Qt.Horizontal)
        self.squelch_slider.setRange(-120, 0)
        self.squelch_slider.setValue(-120)
        controls2.addWidget(self.squelch_slider)

        self.record_btn = QPushButton("Record")
        self.record_btn.setCheckable(True)
        self.record_btn.toggled.connect(self._on_record_toggled)
        controls2.addWidget(self.record_btn)
        root.addLayout(controls2)

        self.status_label = QLabel("Idle")
        root.addWidget(self.status_label)
        root.addStretch(1)

    def _rate_hz(self) -> float:
        return float(self.rate_combo.currentText().split()[0]) * 1e6

    def _on_freq_changed(self, mhz):
        if self.worker is not None:
            self.worker.set_center_freq(mhz * 1e6)

    def _on_mode_changed(self, mode):
        if self.worker is not None:
            self.demod = make_demodulator(mode, self._rate_hz(), AUDIO_RATE)

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
            rate = self._rate_hz()
            self.demod = make_demodulator(self.mode_combo.currentText(), rate, AUDIO_RATE)
            self.worker = SdrWorker(device_index=self.hub.device_index)
            self.worker.center_freq = self.freq_spin.value() * 1e6
            self.worker.sample_rate = rate
            self.worker.gain = gain_val
            self.worker.samples_ready.connect(self.on_samples)
            self.worker.error.connect(self._on_error)
            self.worker.device_opened.connect(lambda: self.status_label.setText("Receiving..."))
            self.worker.start()
            self.audio_sink.start()
            self.status_label.setText("Opening device...")
        else:
            self.start_btn.setText("Start")
            self._stop_all()
            self.status_label.setText("Idle")
            self.hub.release(self.OWNER)

    def _stop_all(self):
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.audio_sink.stop()
        if self._recording:
            self.record_btn.setChecked(False)

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.setText("Start")
        self.start_btn.blockSignals(False)
        self._stop_all()
        self.hub.release(self.OWNER)

    def _on_record_toggled(self, checked):
        if checked:
            path, _ = QFileDialog.getSaveFileName(self, "Save recording", "recording.wav", "WAV files (*.wav)")
            if not path:
                self.record_btn.blockSignals(True)
                self.record_btn.setChecked(False)
                self.record_btn.blockSignals(False)
                return
            self._wav_file = wave.open(path, "wb")
            self._wav_file.setnchannels(1)
            self._wav_file.setsampwidth(2)
            self._wav_file.setframerate(AUDIO_RATE)
            self._recording = True
            self.record_btn.setText("Stop recording")
        else:
            self._recording = False
            self.record_btn.setText("Record")
            if self._wav_file is not None:
                self._wav_file.close()
                self._wav_file = None

    def on_samples(self, iq):
        if self.demod is None:
            return
        power_db = 10.0 * np.log10(float(np.mean(np.abs(iq) ** 2)) + 1e-20)
        self._last_power_db = power_db
        audio = self.demod.process(iq)
        if power_db < self.squelch_slider.value():
            audio = np.zeros_like(audio)
        self.audio_sink.push(audio)
        if self._recording and self._wav_file is not None and len(audio):
            pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            self._wav_file.writeframes(pcm16.tobytes())
        self.status_label.setText(f"Receiving... signal: {power_db:.1f} dB")

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_all()
