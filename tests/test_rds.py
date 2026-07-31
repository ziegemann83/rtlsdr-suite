"""Round-trip test for the RDS decoder: encode a synthetic RDS signal the
same way a real broadcaster would (differential + biphase coding onto a
57 kHz subcarrier, embedded as the phase of a complex baseband carrier),
feed it through RdsDemodulator exactly like live IQ from the dongle, and
check that the station name and RadioText come back out correctly.
"""

import numpy as np

from rtlsdr_suite.rds import RdsDemodulator, encode_block, SYMBOL_RATE

SAMPLE_RATE = 237500.0  # exact multiple of SYMBOL_RATE, keeps the test signal simple
SAMPLES_PER_SYMBOL_HIGHRATE = int(round(SAMPLE_RATE / SYMBOL_RATE))  # 200
PI_CODE = 0x1234


def _build_group_bits(kind: str, seg: int, text: str) -> list[int]:
    if kind == "0A":
        b = seg & 0x3
        c = 0
        d = (ord(text[0]) << 8) | ord(text[1])
    else:  # "2A"
        b = (2 << 12) | (seg & 0xF)
        c = (ord(text[0]) << 8) | ord(text[1])
        d = (ord(text[2]) << 8) | ord(text[3])
    bits = []
    for data, offset in zip([PI_CODE, b, c, d], ["A", "B", "C", "D"]):
        bits += encode_block(data, offset)
    return bits


def _synthetic_iq():
    groups = [
        ("0A", 0, "TE"),
        ("0A", 1, "ST"),
        ("0A", 2, "FM"),
        ("0A", 3, "  "),
        ("2A", 0, "Hell"),
        ("2A", 1, "o Te"),
        ("2A", 2, "st  "),
    ]
    raw_bits = []
    for _ in range(2):  # repeat once so the decoder has a full cycle to lock onto
        for kind, seg, text in groups:
            raw_bits += _build_group_bits(kind, seg, text)

    # differential encode
    enc = []
    prev = 0
    for bit in raw_bits:
        prev = bit ^ prev
        enc.append(prev)

    # biphase (Manchester) modulate each encoded bit at high sample rate
    half = SAMPLES_PER_SYMBOL_HIGHRATE // 2
    baseband = np.empty(len(enc) * SAMPLES_PER_SYMBOL_HIGHRATE, dtype=np.float64)
    for i, e in enumerate(enc):
        start = i * SAMPLES_PER_SYMBOL_HIGHRATE
        if e == 0:
            baseband[start: start + half] = 1.0
            baseband[start + half: start + 2 * half] = -1.0
        else:
            baseband[start: start + half] = -1.0
            baseband[start + half: start + 2 * half] = 1.0

    n = len(baseband)
    t = np.arange(n) / SAMPLE_RATE
    amplitude = 0.6
    composite = amplitude * baseband * np.cos(2.0 * np.pi * 57000.0 * t)

    phase = np.cumsum(composite)
    iq = np.exp(1j * phase).astype(np.complex128)
    return iq


def test_rds_decodes_ps_and_radiotext_single_chunk():
    # Feeding the whole synthetic signal in one call isolates the actual
    # decode logic (block sync, differential decode, group parsing) from
    # the resampling edge-artifacts that appear at chunk boundaries (see
    # the chunked test below) - this is the primary correctness check.
    iq = _synthetic_iq()
    demod = RdsDemodulator(SAMPLE_RATE)
    demod.process(iq)

    assert demod.decoder.pi == PI_CODE
    assert demod.decoder.ps == "TESTFM"
    assert demod.decoder.radiotext.startswith("Hello Test")


def test_rds_recovers_ps_across_multiple_chunks():
    # Streaming input in several chunks (as the real SdrWorker does) can
    # lose an occasional group right at a chunk boundary because each
    # process() call resamples independently - a known, documented
    # limitation. PI and the station name should still come through since
    # they repeat every group / every few groups.
    iq = _synthetic_iq()
    demod = RdsDemodulator(SAMPLE_RATE)
    chunk = len(iq) // 3
    for start in range(0, len(iq), chunk):
        demod.process(iq[start:start + chunk])

    assert demod.decoder.pi == PI_CODE
    assert demod.decoder.ps == "TESTFM"
