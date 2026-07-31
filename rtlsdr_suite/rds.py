"""RDS (Radio Data System) decoding for the WFM broadcast band.

RDS carries a low-bitrate digital side-channel on a 57 kHz subcarrier of
the FM composite signal (3rd harmonic of the 19 kHz stereo pilot). This
module turns raw IQ samples into decoded station name ("PS") and
RadioText, following the EN 50067 / IEC 62106 standard:

- 57.0 kHz subcarrier, 1187.5 bit/s.
- Data bits are differentially encoded, then biphase (Manchester) coded.
- Bits are grouped into 26-bit blocks (16 data bits + 10 CRC check bits),
  four blocks (A, B, C or C', D) per "group". Each block's checkword is
  the CRC10 of its data bits XORed with a fixed per-position offset word,
  which is how a receiver finds block boundaries in an unbroken bitstream.
- Group type 0A carries the 8-character station name (PS), group type 2A
  carries up to 64 characters of RadioText.

This is a from-scratch implementation validated with a synthetic
generator + round-trip unit test (see tests/test_rds.py), not against a
real off-air capture. Real broadcasts add noise, multipath and RTL-SDR
tuner drift that a synthetic signal doesn't - the symbol-timing recovery
here uses a fairly simple "pick the sample phase with the most biphase
energy, then keep it" strategy rather than a continuously-adaptive clock
loop, so it may take a few seconds to lock (or fail to lock on a weak/
noisy station) on real hardware. Good enough to show station name and
RadioText on a solid signal; not a substitute for a dedicated RDS chip.
"""

from __future__ import annotations

from fractions import Fraction

import numpy as np
from scipy import signal as sps

SUBCARRIER_HZ = 57000.0
SYMBOL_RATE = 1187.5
SAMPLES_PER_SYMBOL = 8
TARGET_RATE = SYMBOL_RATE * SAMPLES_PER_SYMBOL  # 9500 Hz

# Degree-10 CRC generator polynomial x^10+x^8+x^7+x^5+x^4+x^3+1 (EN 50067/IEC 62106),
# represented as an 11-bit integer with the implicit leading (x^10) coefficient.
_GENERATOR_POLY = 0b10110111001

OFFSET_WORDS = {
    "A": 0x0FC,
    "B": 0x198,
    "C": 0x168,
    "C'": 0x350,
    "D": 0x1B4,
}


def _remainder(bits: list[int]) -> list[int]:
    """Poly-division remainder of `bits` (MSB first) by the CRC generator.

    Works for any input of length >= 10; the last 10 bits of `reg` are
    treated as the remainder slot. Used both to compute the 10-bit CRC of
    a 16-bit data word (call with data16 + [0]*10) and to compute the
    syndrome of a full 26-bit received block (call with the 26 bits as-is)
    - the same function correctly serves both roles because the offset-word
    XOR trick is linear over GF(2).
    """
    reg = list(bits)
    n = len(reg)
    for i in range(n - 10):
        if reg[i]:
            for j in range(11):
                reg[i + j] ^= (_GENERATOR_POLY >> (10 - j)) & 1
    return reg[n - 10:]


def _bits_to_int(bits) -> int:
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def _int_to_bits(value: int, width: int) -> list[int]:
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def encode_block(data16: int, offset: str) -> list[int]:
    """Build a transmittable 26-bit RDS block (used by the test signal generator)."""
    data_bits = _int_to_bits(data16, 16)
    check = _bits_to_int(_remainder(data_bits + [0] * 10))
    checkword = check ^ OFFSET_WORDS[offset]
    return data_bits + _int_to_bits(checkword, 10)


class RdsDecoder:
    """Bit-level RDS group decoder.

    Feed it the recovered (post biphase-demod, post differential-decode)
    0/1 bitstream via `process_bits()`. It finds block/group sync itself
    and exposes the decoded PI code, station name and RadioText.
    """

    _OFFSET_SEQUENCE = [
        ("A", (0x0FC,)),
        ("B", (0x198,)),
        ("C", (0x168, 0x350)),  # either C or C' is valid in this slot
        ("D", (0x1B4,)),
    ]

    def __init__(self):
        self.pi: int | None = None
        self._ps = [" "] * 8
        self._radiotext = [" "] * 64
        self._bitbuf: list[int] = []
        self._synced = False

    @property
    def ps(self) -> str:
        return "".join(self._ps).rstrip()

    @property
    def radiotext(self) -> str:
        return "".join(self._radiotext).rstrip()

    def process_bits(self, bits) -> None:
        if len(bits) == 0:
            return
        self._bitbuf.extend(int(b) for b in bits)
        if not self._synced:
            self._try_sync()
        if self._synced:
            self._consume_groups()

    def _try_sync(self) -> None:
        buf = self._bitbuf
        max_start = len(buf) - 4 * 26
        for start in range(0, max(0, max_start) + 1):
            ok = True
            for i, (_name, expected) in enumerate(self._OFFSET_SEQUENCE):
                block = buf[start + i * 26: start + i * 26 + 26]
                syndrome = _bits_to_int(_remainder(block))
                if syndrome not in expected:
                    ok = False
                    break
            if ok:
                self._synced = True
                self._bitbuf = buf[start:]
                return
        # no lock yet: keep the buffer from growing without bound while we
        # keep searching on the next batch of incoming bits
        if len(buf) > 4000:
            self._bitbuf = buf[-2000:]

    def _consume_groups(self) -> None:
        pos = 0
        buf = self._bitbuf
        while len(buf) - pos >= 104:
            words = []
            valid = True
            for i, (_name, expected) in enumerate(self._OFFSET_SEQUENCE):
                block = buf[pos + i * 26: pos + i * 26 + 26]
                syndrome = _bits_to_int(_remainder(block))
                if syndrome not in expected:
                    valid = False
                words.append(_bits_to_int(block[:16]))
            if valid:
                self._decode_group(words)
                pos += 104
            else:
                # lost sync (e.g. a noise burst) - drop one bit and keep
                # searching for the next valid 4-block window
                self._synced = False
                pos += 1
                self._bitbuf = buf[pos:]
                self._try_sync()
                return
        self._bitbuf = buf[pos:]

    def _decode_group(self, words: list[int]) -> None:
        pi, b, c, d = words
        self.pi = pi
        group_type = (b >> 12) & 0xF
        version = (b >> 11) & 0x1  # 0 = A, 1 = B
        if group_type == 0 and version == 0:  # 0A: program service name
            seg = b & 0x3
            for i, ch in enumerate([(d >> 8) & 0xFF, d & 0xFF]):
                if 32 <= ch < 127:
                    self._ps[seg * 2 + i] = chr(ch)
        elif group_type == 2 and version == 0:  # 2A: RadioText
            seg = b & 0xF
            chars = [(c >> 8) & 0xFF, c & 0xFF, (d >> 8) & 0xFF, d & 0xFF]
            for i, ch in enumerate(chars):
                if 32 <= ch < 127:
                    self._radiotext[seg * 4 + i] = chr(ch)


class RdsDemodulator:
    """Extracts the RDS subcarrier from raw IQ and feeds bits to an RdsDecoder.

    Call `process(iq)` with successive chunks of raw IQ samples at the
    tuner's sample rate (must be > ~120 kHz so the 57 kHz subcarrier is
    below Nyquist - all the sample rates offered in the Receiver tab
    qualify). Read `.decoder.pi` / `.decoder.ps` / `.decoder.radiotext`
    for the current decode state.
    """

    def __init__(self, sample_rate: float):
        self.sample_rate = float(sample_rate)
        self.decoder = RdsDecoder()
        self._prev_iq = 0j
        self._sample_counter = 0
        self._diff_prev = 0
        self._locked_phase: int | None = None
        frac = Fraction(TARGET_RATE / self.sample_rate).limit_denominator(2000)
        self._resample_up = frac.numerator
        self._resample_down = frac.denominator

    def process(self, iq: np.ndarray) -> None:
        if len(iq) == 0:
            return
        extended = np.concatenate(([self._prev_iq], iq))
        self._prev_iq = iq[-1]
        composite = np.angle(extended[1:] * np.conj(extended[:-1])).astype(np.float64)

        n = len(composite)
        idx = np.arange(n) + self._sample_counter
        self._sample_counter += n
        carrier = np.exp(-1j * 2.0 * np.pi * SUBCARRIER_HZ * idx / self.sample_rate)
        baseband = composite * carrier

        resampled = sps.resample_poly(baseband, self._resample_up, self._resample_down)
        if len(resampled) < SAMPLES_PER_SYMBOL * 4:
            return

        phases = (
            [self._locked_phase] if self._locked_phase is not None
            else list(range(SAMPLES_PER_SYMBOL))
        )
        best_phase = phases[0]
        best_score = -1.0
        best_symbols = None
        for phase in phases:
            usable = resampled[phase:]
            n_sym = len(usable) // SAMPLES_PER_SYMBOL
            if n_sym < 2:
                continue
            usable = usable[: n_sym * SAMPLES_PER_SYMBOL].reshape(n_sym, SAMPLES_PER_SYMBOL)
            half = SAMPLES_PER_SYMBOL // 2
            sym_val = np.real(usable[:, :half].sum(axis=1) - usable[:, half:].sum(axis=1))
            score = float(np.sum(sym_val ** 2))
            if score > best_score:
                best_score = score
                best_phase = phase
                best_symbols = sym_val

        if best_symbols is None:
            return
        if self._locked_phase is None:
            self._locked_phase = best_phase

        manchester_bits = (best_symbols < 0).astype(int)
        prev_arr = np.concatenate(([self._diff_prev], manchester_bits[:-1]))
        diff_bits = manchester_bits ^ prev_arr
        if len(manchester_bits):
            self._diff_prev = int(manchester_bits[-1])

        self.decoder.process_bits(diff_bits.tolist())
