"""Signal processing helpers: spectral estimation and demodulators."""

from __future__ import annotations

import numpy as np
from scipy import signal as sps


def _factor_stages(factor: int, max_stage: int = 10) -> list[int]:
    """Split a decimation factor into a list of stage factors <= max_stage."""
    factor = max(1, int(factor))
    stages = []
    remaining = factor
    while remaining > max_stage:
        # pick the largest divisor of `remaining` that is <= max_stage,
        # falling back to max_stage itself if remaining is prime-ish
        stage = max_stage
        for d in range(max_stage, 1, -1):
            if remaining % d == 0:
                stage = d
                break
        stages.append(stage)
        remaining //= stage
    if remaining > 1:
        stages.append(remaining)
    return stages or [1]


def _cascaded_decimate(x: np.ndarray, factor: int) -> np.ndarray:
    """scipy.signal.decimate is only numerically stable for factors <= ~13,
    so split large decimation factors into a cascade of smaller stages."""
    out = x
    for stage in _factor_stages(factor):
        if stage <= 1:
            continue
        if len(out) <= stage * 8:
            break
        out = sps.decimate(out, stage, ftype="fir", zero_phase=False)
    return out


def power_spectrum_db(iq: np.ndarray, nfft: int = 2048) -> np.ndarray:
    """Return a single averaged power spectrum in dB, DC-centered (fftshift)."""
    n = len(iq)
    if n < nfft:
        nfft = int(2 ** np.floor(np.log2(max(n, 2))))
    usable = (n // nfft) * nfft
    if usable == 0:
        return np.zeros(nfft)
    chunks = iq[:usable].reshape(-1, nfft)
    window = np.hanning(nfft)
    spec = np.fft.fftshift(np.fft.fft(chunks * window, axis=1), axes=1)
    power = np.mean(np.abs(spec) ** 2, axis=0)
    power = np.maximum(power, 1e-20)
    return 10.0 * np.log10(power / nfft)


class FMDemodulator:
    """Wide/narrow FM demodulator with de-emphasis and decimation to audio rate."""

    def __init__(self, sample_rate: float, audio_rate: int = 48000, deemphasis_us: float = 75.0):
        self.sample_rate = sample_rate
        self.audio_rate = audio_rate
        self._prev = 0j
        # de-emphasis single pole IIR state
        self._deemph_state = 0.0
        tau = deemphasis_us * 1e-6
        dt = 1.0 / audio_rate
        self._deemph_alpha = dt / (tau + dt)

    def process(self, iq: np.ndarray) -> np.ndarray:
        if len(iq) == 0:
            return np.zeros(0, dtype=np.float32)
        extended = np.concatenate(([self._prev], iq))
        self._prev = iq[-1]
        prod = extended[1:] * np.conj(extended[:-1])
        demod = np.angle(prod).astype(np.float32)  # instantaneous frequency, radians/sample

        decim = max(1, int(round(self.sample_rate / self.audio_rate)))
        if decim > 1:
            audio = _cascaded_decimate(demod, decim)
        else:
            audio = demod

        # simple de-emphasis (single-pole low pass)
        out = np.empty_like(audio)
        state = self._deemph_state
        alpha = self._deemph_alpha
        for i, x in enumerate(audio):
            state = state + alpha * (x - state)
            out[i] = state
        self._deemph_state = state

        peak = np.max(np.abs(out)) + 1e-9
        return (out / max(peak, 1.0)).astype(np.float32)


class AMDemodulator:
    def __init__(self, sample_rate: float, audio_rate: int = 48000):
        self.sample_rate = sample_rate
        self.audio_rate = audio_rate
        self._dc = 0.0

    def process(self, iq: np.ndarray) -> np.ndarray:
        if len(iq) == 0:
            return np.zeros(0, dtype=np.float32)
        mag = np.abs(iq).astype(np.float32)
        dc = float(np.mean(mag))
        self._dc = 0.999 * self._dc + 0.001 * dc if self._dc else dc
        mag = mag - self._dc
        decim = max(1, int(round(self.sample_rate / self.audio_rate)))
        audio = _cascaded_decimate(mag, decim) if decim > 1 else mag
        peak = np.max(np.abs(audio)) + 1e-9
        return (audio / max(peak, 1.0)).astype(np.float32)


class SSBDemodulator:
    """Single sideband (USB/LSB) demodulator.

    Extracts one sideband by zeroing out the unwanted half of the spectrum
    (the negative-frequency half for USB, the positive-frequency half for
    LSB) and taking the real part of the result. This is a straightforward
    block-based version of the classic "phasing method" filter - simple to
    reason about and good enough for voice-grade shortwave reception, though
    a dedicated SSB receiver with a steeper/continuous filter will sound
    cleaner right at the block boundaries.
    """

    def __init__(self, sample_rate: float, audio_rate: int = 48000, mode: str = "USB"):
        self.sample_rate = sample_rate
        self.audio_rate = audio_rate
        self.mode = mode  # "USB" or "LSB"

    def process(self, iq: np.ndarray) -> np.ndarray:
        if len(iq) == 0:
            return np.zeros(0, dtype=np.float32)
        n = len(iq)
        spectrum = np.fft.fft(iq)
        freqs = np.fft.fftfreq(n)
        if self.mode.upper() == "USB":
            spectrum[freqs < 0] = 0
        else:  # LSB
            spectrum[freqs > 0] = 0
        filtered = np.fft.ifft(spectrum)
        # x2 to restore amplitude lost by discarding half the spectrum
        audio = (2.0 * np.real(filtered)).astype(np.float32)
        decim = max(1, int(round(self.sample_rate / self.audio_rate)))
        if decim > 1:
            audio = _cascaded_decimate(audio, decim)
        peak = np.max(np.abs(audio)) + 1e-9
        return (audio / max(peak, 1.0)).astype(np.float32)


def make_demodulator(mode: str, sample_rate: float, audio_rate: int = 48000):
    mode = mode.upper()
    if mode == "WFM":
        return FMDemodulator(sample_rate, audio_rate, deemphasis_us=75.0)
    if mode == "NFM":
        return FMDemodulator(sample_rate, audio_rate, deemphasis_us=300.0)
    if mode == "AM":
        return AMDemodulator(sample_rate, audio_rate)
    if mode in ("USB", "LSB"):
        return SSBDemodulator(sample_rate, audio_rate, mode=mode)
    raise ValueError(f"Unknown mode: {mode}")


def squelch_gate(audio: np.ndarray, iq_power_db: float, threshold_db: float) -> np.ndarray:
    """Mute audio if the signal power is below the squelch threshold."""
    if iq_power_db < threshold_db:
        return np.zeros_like(audio)
    return audio
