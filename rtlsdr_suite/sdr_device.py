"""Background thread that owns the RTL-SDR device and streams IQ samples.

Only one SdrWorker should be reading from the dongle at a time. The worker
is used by both the Spectrum tab and the Receiver tab, which share the same
underlying device connection through MainWindow.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QThread, Signal


class SdrWorker(QThread):
    """Reads IQ samples from an RTL-SDR dongle in a background thread.

    Signals
    -------
    samples_ready(np.ndarray)
        Emitted with a block of complex64 IQ samples, normalized to [-1, 1].
    error(str)
        Emitted if opening the device or reading samples fails.
    device_opened()
        Emitted once the device has been successfully opened and configured.
    """

    samples_ready = Signal(object)
    error = Signal(str)
    device_opened = Signal()

    def __init__(self, device_index: int = 0, parent=None):
        super().__init__(parent)
        self.device_index = device_index
        self.center_freq = 100_000_000.0
        self.sample_rate = 2_048_000.0
        self.gain = "auto"  # 'auto' or a float in dB
        self.freq_correction_ppm = 0
        self._samples_per_read = 256 * 1024
        self._running = False
        self._sdr = None

    # -- configuration setters, safe to call before start() or while running --
    def set_center_freq(self, freq_hz: float):
        self.center_freq = float(freq_hz)
        if self._sdr is not None:
            try:
                self._sdr.center_freq = self.center_freq
            except Exception as exc:  # pragma: no cover - hardware dependent
                self.error.emit(f"Could not set frequency: {exc}")

    def set_sample_rate(self, rate_hz: float):
        self.sample_rate = float(rate_hz)
        if self._sdr is not None:
            try:
                self._sdr.sample_rate = self.sample_rate
            except Exception as exc:  # pragma: no cover
                self.error.emit(f"Could not set sample rate: {exc}")

    def set_gain(self, gain):
        self.gain = gain
        if self._sdr is not None:
            try:
                self._sdr.gain = gain
            except Exception as exc:  # pragma: no cover
                self.error.emit(f"Could not set gain: {exc}")

    def set_samples_per_read(self, n: int):
        # must be a multiple of 512 for pyrtlsdr / librtlsdr
        self._samples_per_read = max(512, (n // 512) * 512)

    def stop(self):
        self._running = False

    def run(self):
        try:
            from rtlsdr import RtlSdr
        except Exception as exc:
            self.error.emit(
                "pyrtlsdr / librtlsdr not available: "
                f"{exc}\nInstall librtlsdr drivers and 'pip install pyrtlsdr'."
            )
            return

        try:
            self._sdr = RtlSdr(device_index=self.device_index)
            self._sdr.sample_rate = self.sample_rate
            self._sdr.center_freq = self.center_freq
            self._sdr.freq_correction = self.freq_correction_ppm
            self._sdr.gain = self.gain
        except Exception as exc:
            self.error.emit(f"Could not open RTL-SDR device #{self.device_index}: {exc}")
            self._sdr = None
            return

        self.device_opened.emit()
        self._running = True
        try:
            while self._running:
                iq = self._sdr.read_samples(self._samples_per_read)
                if not self._running:
                    break
                self.samples_ready.emit(np.asarray(iq, dtype=np.complex64))
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error.emit(f"Error while reading samples: {exc}")
        finally:
            try:
                if self._sdr is not None:
                    self._sdr.close()
            except Exception:
                pass
            self._sdr = None

    @staticmethod
    def list_devices() -> list[str]:
        """Return human readable names for connected RTL-SDR dongles."""
        try:
            from rtlsdr import librtlsdr
            n = librtlsdr.rtlsdr_get_device_count()
            names = []
            for i in range(n):
                try:
                    name = librtlsdr.rtlsdr_get_device_name(i).decode(errors="replace")
                except Exception:
                    name = "RTL-SDR"
                names.append(f"[{i}] {name}")
            return names
        except Exception:
            return []
