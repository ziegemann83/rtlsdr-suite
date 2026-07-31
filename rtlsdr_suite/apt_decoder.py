"""NOAA APT weather satellite image decoder.

APT (Automatic Picture Transmission) is the analog image format used by the
NOAA-15/18/19 polar-orbiting weather satellites on ~137 MHz. The RF signal is
a narrowband FM carrier; once FM-demodulated, the resulting "audio" contains
a 2400 Hz subcarrier that is amplitude-modulated with the video (pixel)
data, at a fixed rate of 4160 pixels/second (2 lines/second, 2080 pixels/line).

This is a compact, dependency-free decoder good enough to produce a
recognisable raw APT image (clouds/coastlines visible) from a live or
recorded pass. It intentionally does not attempt telemetry-based calibration
or channel A/B splitting/cropping - it produces the classic "raw" 2080 px
wide APT image, which is what most simple decoders show before enhancement.

Algorithm
---------
1. FM-discriminate the raw IQ (no de-emphasis - that would attenuate the
   2400 Hz subcarrier).
2. Resample the discriminator output to 20800 Hz (5x the pixel rate; this
   is the sample rate almost every APT tool/recording uses internally).
3. Recover the video envelope from the 2400 Hz AM subcarrier via a Hilbert
   transform (take the magnitude of the analytic signal after bandpassing
   around 2400 Hz).
4. Decimate the envelope by exactly 5 to land on the 4160 Hz pixel rate.
5. Cross-correlate against the known 7-pulse sync-A pattern to find each
   line's start (checking both normal and inverted polarity, since some
   receiver chains flip the video sign), then slice a fixed-width
   2080-pixel line. Falls back to a fixed-stride guess if no sync peak is
   found nearby (keeps the image producible even on a noisy or short
   capture).
6. Track a smoothed, drift-corrected estimate of the true line length (in
   pixels) instead of assuming exactly 2080.0 between every sync pulse.
   The RTL-SDR's sample-rate clock is not phase-locked to the satellite's
   4160 Hz line clock, so over a 10-15 minute pass the two drift apart by
   tens of pixels; without correction, later lines in the image
   increasingly "shear" sideways relative to earlier ones. Re-centering
   the sync search window on the current drift estimate each line keeps
   the whole pass aligned instead of just the first minute or two.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np
from scipy import signal as sps

PIXEL_RATE = 4160  # pixels/second
LINE_WIDTH = 2080  # pixels/line (0.5 s/line)
WORK_RATE = 20800  # 5x pixel rate; internal working sample rate

# Sync A: 7 cycles of a 1040 Hz square wave (4160/1040 = 4 samples/cycle at
# the pixel rate), each cycle 2 "high" + 2 "low" pixels.
_SYNC_A = np.array(([1, 1, 0, 0] * 7), dtype=np.float32)
_SYNC_A = (_SYNC_A - _SYNC_A.mean()) / (_SYNC_A.std() + 1e-9)


def _resample(x: np.ndarray, in_rate: float, out_rate: float) -> np.ndarray:
    if len(x) == 0:
        return x
    from fractions import Fraction
    frac = Fraction(out_rate).limit_denominator(1000) / Fraction(in_rate).limit_denominator(1000)
    up, down = frac.numerator, frac.denominator
    return sps.resample_poly(x, up, down).astype(np.float32)


def write_png_grayscale(path: str, image: np.ndarray) -> None:
    """Write a 2D uint8 array as an 8-bit grayscale PNG, stdlib only."""
    if image.dtype != np.uint8:
        image = image.astype(np.uint8)
    height, width = image.shape

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # bit depth 8, color type 0 (gray)
    raw = bytearray()
    for row in image:
        raw.append(0)  # filter type 0 (none) per scanline
        raw.extend(row.tobytes())
    idat = zlib.compress(bytes(raw), level=6)
    with open(path, "wb") as f:
        f.write(sig)
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


class AptDecoder:
    """Streaming NOAA APT decoder: feed IQ chunks, pull out finished image rows."""

    # how far the estimated line length may drift per line, as a fraction of
    # LINE_WIDTH - generous enough to absorb realistic RTL-SDR clock error
    # (tens of ppm) while still rejecting a wild single-line misdetection
    _MAX_DRIFT_FRACTION = 0.01

    def __init__(self, iq_sample_rate: float):
        self.iq_sample_rate = iq_sample_rate
        self._prev_iq = 0j
        self._env_buffer = np.zeros(0, dtype=np.float32)
        self._search_pos = 0  # index into env_buffer where we expect the next line to start
        self._line_length_est = float(LINE_WIDTH)  # smoothed, drift-corrected line length
        self._last_sync_off: int | None = None  # env_buffer offset of the previous line's start
        self._synced_lines = 0  # consecutive lines found via real sync (vs. fallback stride)
        self.rows: list[np.ndarray] = []
        self._max_rows = 2000  # ~16 min of pass, plenty for a single overhead pass

    def feed(self, iq: np.ndarray) -> int:
        """Feed a chunk of raw IQ samples. Returns how many new rows were produced."""
        if len(iq) == 0:
            return 0
        extended = np.concatenate(([self._prev_iq], iq))
        self._prev_iq = iq[-1]
        prod = extended[1:] * np.conj(extended[:-1])
        discrim = np.angle(prod).astype(np.float32)

        work = _resample(discrim, self.iq_sample_rate, WORK_RATE)
        if len(work) == 0:
            return 0

        # bandpass around the 2400 Hz subcarrier, then envelope via Hilbert
        sos = sps.butter(4, [1800, 3000], btype="bandpass", fs=WORK_RATE, output="sos")
        band = sps.sosfilt(sos, work)
        envelope = np.abs(sps.hilbert(band)).astype(np.float32)

        # decimate WORK_RATE (20800) -> PIXEL_RATE (4160): exact factor of 5
        pixels = envelope[: (len(envelope) // 5) * 5].reshape(-1, 5).mean(axis=1)

        self._env_buffer = np.concatenate([self._env_buffer, pixels])
        return self._extract_rows()

    def _find_sync(self, lo: int, hi: int) -> tuple[int | None, float]:
        """Search env_buffer[lo:hi+len(_SYNC_A)] for the sync-A pulse train.

        Checks both normal and inverted polarity (some receiver chains flip
        the video sign) and returns the best (offset, score) pair, or
        (None, -1.0) if nothing scores above the detection threshold.
        """
        if hi <= lo:
            return None, -1.0
        seg = self._env_buffer[lo: hi + len(_SYNC_A)]
        if seg.std() < 1e-9:
            return None, -1.0
        norm = (seg - seg.mean()) / (seg.std() + 1e-9)
        corr_pos = np.correlate(norm, _SYNC_A, mode="valid")
        corr_neg = np.correlate(norm, -_SYNC_A, mode="valid")
        if len(corr_pos) == 0:
            return None, -1.0
        idx_pos = int(np.argmax(corr_pos))
        idx_neg = int(np.argmax(corr_neg))
        if corr_pos[idx_pos] >= corr_neg[idx_neg]:
            idx, score = idx_pos, float(corr_pos[idx_pos])
        else:
            idx, score = idx_neg, float(corr_neg[idx_neg])
        if score > 15.0:  # empirical threshold for a real sync pulse
            return lo + idx, score
        return None, -1.0

    def _extract_rows(self) -> int:
        produced = 0
        # search window widens a bit once we've lost sync a few times in a
        # row, so a brief noisy stretch doesn't permanently derail alignment
        while True:
            search_window = 200 if self._synced_lines > 0 else 400
            expected_len = int(round(self._line_length_est))
            if len(self._env_buffer) - self._search_pos < expected_len + search_window:
                break

            lo = max(0, self._search_pos - search_window // 2)
            hi = min(
                len(self._env_buffer) - len(_SYNC_A),
                self._search_pos + search_window // 2,
            )
            best_off, best_score = self._find_sync(lo, hi)

            if best_off is not None:
                # update the smoothed line-length estimate from this
                # measured start-to-start distance vs. the previous line's
                # sync, but clamp the per-line change so one bad detection
                # can't derail future search
                if self._last_sync_off is not None:
                    measured = best_off - self._last_sync_off
                    max_delta = LINE_WIDTH * self._MAX_DRIFT_FRACTION
                    measured_clamped = float(np.clip(
                        measured, LINE_WIDTH - max_delta, LINE_WIDTH + max_delta
                    ))
                    self._line_length_est = 0.8 * self._line_length_est + 0.2 * measured_clamped
                self._last_sync_off = best_off
                self._synced_lines += 1
                next_start = best_off + int(round(self._line_length_est))
            else:
                # no confident sync found nearby: fall back to the current
                # drift-corrected stride estimate rather than snapping back
                # to a fixed 2080, so a short noisy stretch doesn't undo
                # alignment already learned from earlier in the pass
                best_off = self._search_pos
                self._last_sync_off = best_off
                self._synced_lines = 0
                next_start = best_off + int(round(self._line_length_est))

            line = self._env_buffer[best_off: best_off + LINE_WIDTH]
            if len(line) < LINE_WIDTH:
                break
            lo_p, hi_p = np.percentile(line, [1, 99])
            span = max(hi_p - lo_p, 1e-6)
            row = np.clip((line - lo_p) / span * 255.0, 0, 255).astype(np.uint8)
            self.rows.append(row)
            produced += 1
            self._search_pos = next_start
            if len(self.rows) > self._max_rows:
                self.rows.pop(0)

        # drop consumed samples to keep the buffer bounded
        if self._search_pos > 4 * LINE_WIDTH:
            self._env_buffer = self._env_buffer[self._search_pos:]
            self._search_pos = 0
        return produced

    def image(self) -> np.ndarray:
        if not self.rows:
            return np.zeros((1, LINE_WIDTH), dtype=np.uint8)
        return np.stack(self.rows, axis=0)

    def save_png(self, path: str) -> None:
        write_png_grayscale(path, self.image())
