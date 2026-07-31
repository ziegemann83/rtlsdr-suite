"""Audio playback sink built on sounddevice, fed from a small ring buffer."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd


class AudioSink:
    def __init__(self, sample_rate: int = 48000, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._lock = threading.Lock()
        self._buffer = np.zeros(0, dtype=np.float32)
        self._volume = 1.0
        self._stream = None
        self._max_buffer = sample_rate * 4  # cap latency growth

    def start(self):
        if self._stream is not None:
            return
        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            callback=self._callback,
            blocksize=1024,
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)

    def set_volume(self, vol: float):
        self._volume = max(0.0, min(2.0, vol))

    def push(self, audio: np.ndarray):
        if audio is None or len(audio) == 0:
            return
        with self._lock:
            self._buffer = np.concatenate([self._buffer, audio])
            if len(self._buffer) > self._max_buffer:
                # drop oldest samples to avoid unbounded latency
                self._buffer = self._buffer[-self._max_buffer:]

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            n = min(frames, len(self._buffer))
            chunk = self._buffer[:n]
            self._buffer = self._buffer[n:]
        if n < frames:
            chunk = np.concatenate([chunk, np.zeros(frames - n, dtype=np.float32)])
        outdata[:, 0] = chunk * self._volume
