"""General purpose receiver tab: WFM / NFM / AM / USB / LSB with audio out + recording."""

from __future__ import annotations

import os
import time
import wave

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QComboBox,
    QPushButton, QSlider, QMessageBox, QFileDialog, QCheckBox, QLineEdit,
    QSpinBox, QApplication, QSystemTrayIcon, QListWidget, QListWidgetItem,
    QInputDialog,
)
from PySide6.QtCore import Qt

from .dsp import make_demodulator
from .sdr_device import SdrWorker
from .audio_out import AudioSink
from .settings import get_settings, ReceiverPresets

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
        self.presets = ReceiverPresets()

        # -- squelch-triggered auto recording --
        self._auto_record_dir: str | None = None
        self._auto_recording = False
        self._auto_wav_file: wave.Wave_write | None = None
        self._squelch_open = False

        # -- multi-frequency scan list --
        self._scan_freqs_mhz: list[float] = []
        self._scan_index = 0
        self._scan_last_hop_time = 0.0
        self._scan_signal_since: float | None = None

        # -- squelch alert --
        self._last_alert_time = 0.0
        self._tray_icon: QSystemTrayIcon | None = None

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

        # -- squelch-triggered auto recording --
        controls3 = QHBoxLayout()
        self.auto_record_check = QCheckBox("Auto-record on squelch")
        self.auto_record_check.toggled.connect(self._on_auto_record_toggled)
        controls3.addWidget(self.auto_record_check)
        self.auto_record_label = QLabel("(no folder selected)")
        controls3.addWidget(self.auto_record_label)

        self.alert_check = QCheckBox("Alert on squelch open")
        controls3.addWidget(self.alert_check)
        controls3.addStretch(1)
        root.addLayout(controls3)

        # -- multi-frequency scan list --
        controls4 = QHBoxLayout()
        self.scan_check = QCheckBox("Scan list (MHz, comma separated):")
        self.scan_check.toggled.connect(self._on_scan_toggled)
        controls4.addWidget(self.scan_check)
        self.scan_freqs_edit = QLineEdit()
        self.scan_freqs_edit.setPlaceholderText("e.g. 145.500, 433.500, 446.006")
        controls4.addWidget(self.scan_freqs_edit, stretch=2)
        controls4.addWidget(QLabel("Dwell (s):"))
        self.scan_dwell_spin = QSpinBox()
        self.scan_dwell_spin.setRange(1, 60)
        self.scan_dwell_spin.setValue(3)
        controls4.addWidget(self.scan_dwell_spin)
        root.addLayout(controls4)

        self.status_label = QLabel("Idle")
        root.addWidget(self.status_label)

        # -- named frequency/mode presets --
        presets_row = QHBoxLayout()
        presets_row.addWidget(QLabel("Presets:"))
        self.preset_list = QListWidget()
        self.preset_list.setMaximumHeight(90)
        self.preset_list.itemDoubleClicked.connect(self._on_preset_activated)
        presets_row.addWidget(self.preset_list, stretch=1)

        preset_btns = QVBoxLayout()
        self.preset_add_btn = QPushButton("+ Speichern")
        self.preset_add_btn.clicked.connect(self._on_add_preset)
        preset_btns.addWidget(self.preset_add_btn)
        self.preset_remove_btn = QPushButton("- Entfernen")
        self.preset_remove_btn.clicked.connect(self._on_remove_preset)
        preset_btns.addWidget(self.preset_remove_btn)
        presets_row.addLayout(preset_btns)
        root.addLayout(presets_row)

        root.addStretch(1)

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(250)
        self._scan_timer.timeout.connect(self._scan_tick)

        self._reload_preset_list()
        self._load_settings()

    def _reload_preset_list(self):
        self.preset_list.clear()
        for p in self.presets.load():
            freq_mhz = p.get("freq_hz", 0) / 1e6
            item = QListWidgetItem(f"{p.get('name', '?')} — {freq_mhz:.4f} MHz ({p.get('mode', '?')})")
            self.preset_list.addItem(item)

    def _on_add_preset(self):
        name, ok = QInputDialog.getText(self, "Preset speichern", "Name für diese Frequenz:")
        if not ok or not name.strip():
            return
        self.presets.add(name.strip(), self.freq_spin.value() * 1e6, self.mode_combo.currentText())
        self._reload_preset_list()

    def _on_remove_preset(self):
        row = self.preset_list.currentRow()
        if row >= 0:
            self.presets.remove(row)
            self._reload_preset_list()

    def _on_preset_activated(self, item: QListWidgetItem):
        row = self.preset_list.row(item)
        presets = self.presets.load()
        if 0 <= row < len(presets):
            p = presets[row]
            self.freq_spin.setValue(p.get("freq_hz", 0) / 1e6)
            idx = self.mode_combo.findText(p.get("mode", "WFM"))
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)

    def set_frequency_mhz(self, freq_mhz: float):
        """Called externally (e.g. from the Spectrum tab's click-to-tune)."""
        self.freq_spin.setValue(freq_mhz)

    def _load_settings(self):
        s = get_settings()
        self.freq_spin.setValue(float(s.value("receiver/freq_mhz", 100.0)))
        mode_text = s.value("receiver/mode", "WFM")
        idx = self.mode_combo.findText(mode_text)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        rate_text = s.value("receiver/rate", "2.048 MSps")
        idx = self.rate_combo.findText(rate_text)
        if idx >= 0:
            self.rate_combo.setCurrentIndex(idx)
        gain_text = s.value("receiver/gain", "auto")
        idx = self.gain_combo.findText(gain_text)
        if idx >= 0:
            self.gain_combo.setCurrentIndex(idx)
        self.vol_slider.setValue(int(s.value("receiver/volume", 100)))
        self.squelch_slider.setValue(int(s.value("receiver/squelch", -120)))

    def save_settings(self):
        s = get_settings()
        s.setValue("receiver/freq_mhz", self.freq_spin.value())
        s.setValue("receiver/mode", self.mode_combo.currentText())
        s.setValue("receiver/rate", self.rate_combo.currentText())
        s.setValue("receiver/gain", self.gain_combo.currentText())
        s.setValue("receiver/volume", self.vol_slider.value())
        s.setValue("receiver/squelch", self.squelch_slider.value())

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
            if self.scan_check.isChecked():
                self._scan_last_hop_time = time.time()
                self._scan_timer.start()
        else:
            self.start_btn.setText("Start")
            self._stop_all()
            self.status_label.setText("Idle")
            self.hub.release(self.OWNER)

    def _stop_all(self):
        self._scan_timer.stop()
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait(2000)
            self.worker = None
        self.audio_sink.stop()
        if self._recording:
            self.record_btn.setChecked(False)
        self._close_auto_wav()
        self._squelch_open = False

    def _on_error(self, msg):
        self.status_label.setText(f"Error: {msg}")
        self.start_btn.blockSignals(True)
        self.start_btn.setChecked(False)
        self.start_btn.setText("Start")
        self.start_btn.blockSignals(False)
        self._stop_all()
        self.hub.release(self.OWNER)

    def _on_auto_record_toggled(self, checked):
        if checked:
            folder = QFileDialog.getExistingDirectory(self, "Folder for auto-recorded clips")
            if not folder:
                self.auto_record_check.blockSignals(True)
                self.auto_record_check.setChecked(False)
                self.auto_record_check.blockSignals(False)
                return
            self._auto_record_dir = folder
            self.auto_record_label.setText(folder)
            self.record_btn.setEnabled(False)
        else:
            self._close_auto_wav()
            self.auto_record_label.setText("(no folder selected)")
            self.record_btn.setEnabled(True)

    def _open_auto_wav(self):
        if not self._auto_record_dir:
            return
        fname = time.strftime("recv_%Y%m%d_%H%M%S.wav")
        path = os.path.join(self._auto_record_dir, fname)
        try:
            self._auto_wav_file = wave.open(path, "wb")
            self._auto_wav_file.setnchannels(1)
            self._auto_wav_file.setsampwidth(2)
            self._auto_wav_file.setframerate(AUDIO_RATE)
            self._auto_recording = True
            self.status_label.setText(f"Auto-recording: {fname}")
        except Exception as exc:
            self._auto_wav_file = None
            self._auto_recording = False
            self.status_label.setText(f"Could not start auto-recording: {exc}")

    def _close_auto_wav(self):
        self._auto_recording = False
        if self._auto_wav_file is not None:
            try:
                self._auto_wav_file.close()
            except Exception:
                pass
            self._auto_wav_file = None

    def _on_scan_toggled(self, checked):
        if checked:
            try:
                freqs = [
                    float(f.strip()) for f in self.scan_freqs_edit.text().split(",") if f.strip()
                ]
            except ValueError:
                QMessageBox.warning(self, "Invalid scan list",
                                     "Please enter comma-separated MHz values, e.g. 145.500, 433.500")
                self.scan_check.blockSignals(True)
                self.scan_check.setChecked(False)
                self.scan_check.blockSignals(False)
                return
            if not freqs:
                QMessageBox.warning(self, "Empty scan list", "Enter at least one frequency to scan.")
                self.scan_check.blockSignals(True)
                self.scan_check.setChecked(False)
                self.scan_check.blockSignals(False)
                return
            self._scan_freqs_mhz = freqs
            self._scan_index = 0
            self._scan_last_hop_time = time.time()
            self._scan_signal_since = None
            self.scan_freqs_edit.setEnabled(False)
            if self.worker is not None:
                self._scan_timer.start()
        else:
            self._scan_timer.stop()
            self.scan_freqs_edit.setEnabled(True)

    def _scan_tick(self):
        if self.worker is None or not self._scan_freqs_mhz:
            return
        now = time.time()
        squelch_db = self.squelch_slider.value()
        if self._last_power_db >= squelch_db:
            # signal present: stay parked on this frequency
            self._scan_signal_since = self._scan_signal_since or now
            self._scan_last_hop_time = now
            return
        self._scan_signal_since = None
        if now - self._scan_last_hop_time >= self.scan_dwell_spin.value():
            self._scan_index = (self._scan_index + 1) % len(self._scan_freqs_mhz)
            next_mhz = self._scan_freqs_mhz[self._scan_index]
            self.freq_spin.blockSignals(True)
            self.freq_spin.setValue(next_mhz)
            self.freq_spin.blockSignals(False)
            self.worker.set_center_freq(next_mhz * 1e6)
            self._scan_last_hop_time = now
            self.status_label.setText(f"Scanning... parked on {next_mhz:.4f} MHz")

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
        squelch_open = power_db >= self.squelch_slider.value()
        if not squelch_open:
            audio = np.zeros_like(audio)
        self.audio_sink.push(audio)

        if self._recording and self._wav_file is not None and len(audio):
            pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
            self._wav_file.writeframes(pcm16.tobytes())

        # squelch-triggered auto recording: open a new clip on rising edge,
        # close it on falling edge, so each transmission becomes its own file
        if self.auto_record_check.isChecked():
            if squelch_open and not self._squelch_open:
                self._open_auto_wav()
            elif not squelch_open and self._squelch_open:
                self._close_auto_wav()
            if self._auto_recording and self._auto_wav_file is not None and len(audio):
                pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
                self._auto_wav_file.writeframes(pcm16.tobytes())

        # squelch alert: beep + desktop notification on the rising edge, rate-limited
        # so a marginal signal flickering open/closed doesn't spam notifications
        if self.alert_check.isChecked() and squelch_open and not self._squelch_open:
            now = time.time()
            if now - self._last_alert_time > 2.0:
                self._last_alert_time = now
                self._fire_alert(power_db)

        self._squelch_open = squelch_open

        if not (self.scan_check.isChecked() and not squelch_open):
            self.status_label.setText(f"Receiving... signal: {power_db:.1f} dB")

    def _fire_alert(self, power_db: float):
        QApplication.beep()
        if QSystemTrayIcon.isSystemTrayAvailable():
            if self._tray_icon is None:
                self._tray_icon = QSystemTrayIcon(self)
                app = QApplication.instance()
                icon = app.windowIcon() if app is not None else None
                if icon is not None and not icon.isNull():
                    self._tray_icon.setIcon(icon)
                self._tray_icon.show()
            self._tray_icon.showMessage(
                "RTL-SDR Suite",
                f"Signal detected on {self.freq_spin.value():.4f} MHz ({power_db:.1f} dB)",
                QSystemTrayIcon.Information,
                4000,
            )

    def shutdown(self):
        if self.start_btn.isChecked():
            self.start_btn.setChecked(False)
        self._stop_all()
        self.save_settings()
