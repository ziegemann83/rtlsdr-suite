"""Unit tests for the signal processing helpers (rtlsdr_suite.dsp)."""

import numpy as np
import pytest

from rtlsdr_suite.dsp import (
    power_spectrum_db,
    make_demodulator,
    FMDemodulator,
    AMDemodulator,
    SSBDemodulator,
    _factor_stages,
    _cascaded_decimate,
)


def _noise_iq(n=200_000, scale=0.1, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * scale


def test_power_spectrum_db_shape_and_range():
    iq = _noise_iq(65536)
    db = power_spectrum_db(iq, nfft=2048)
    assert db.shape == (2048,)
    assert np.all(np.isfinite(db))
    # noise should not read as absolute silence or absurdly hot
    assert -80 < np.median(db) < 20


def test_power_spectrum_db_handles_short_input():
    # fewer samples than nfft should not crash, just fall back to a smaller fft
    iq = _noise_iq(100)
    db = power_spectrum_db(iq, nfft=2048)
    assert len(db) > 0
    assert np.all(np.isfinite(db))


@pytest.mark.parametrize("mode", ["WFM", "NFM", "AM", "USB", "LSB"])
def test_make_demodulator_produces_bounded_audio(mode):
    iq = _noise_iq(200_000)
    demod = make_demodulator(mode, sample_rate=2_048_000, audio_rate=48_000)
    audio = demod.process(iq)
    assert len(audio) > 0
    assert np.all(np.isfinite(audio))
    assert np.max(np.abs(audio)) <= 1.0 + 1e-6


def test_make_demodulator_unknown_mode_raises():
    with pytest.raises(ValueError):
        make_demodulator("NOPE", 2_048_000)


def test_fm_demodulator_state_persists_across_calls():
    demod = FMDemodulator(2_048_000, 48_000)
    iq = _noise_iq(100_000)
    out1 = demod.process(iq[:50_000])
    out2 = demod.process(iq[50_000:])
    assert len(out1) > 0 and len(out2) > 0


def test_am_demodulator_empty_input():
    demod = AMDemodulator(2_048_000, 48_000)
    out = demod.process(np.array([], dtype=np.complex64))
    assert len(out) == 0


def test_ssb_demodulator_usb_lsb_differ():
    iq = _noise_iq(200_000, seed=1)
    usb = SSBDemodulator(2_048_000, 48_000, mode="USB").process(iq.copy())
    lsb = SSBDemodulator(2_048_000, 48_000, mode="LSB").process(iq.copy())
    assert len(usb) == len(lsb)
    # USB and LSB pick up different sidebands - outputs shouldn't be identical
    assert not np.allclose(usb, lsb)


@pytest.mark.parametrize("factor,max_stage", [(1, 10), (7, 10), (100, 10)])
def test_factor_stages_multiply_back_to_factor(factor, max_stage):
    # Exact reconstruction holds when `factor` only has prime factors <= max_stage.
    stages = _factor_stages(factor, max_stage)
    product = 1
    for s in stages:
        assert s <= max_stage
        product *= s
    assert product == factor


def test_factor_stages_approximates_when_factor_has_large_prime():
    # 43 is prime and > max_stage, so exact factorization is impossible; the
    # implementation should still return bounded stages that approximate it
    # reasonably closely rather than raising or looping forever.
    stages = _factor_stages(43, 10)
    product = 1
    for s in stages:
        assert 1 < s <= 10
        product *= s
    assert abs(product - 43) / 43 < 0.15


def test_cascaded_decimate_reduces_length():
    x = np.sin(np.linspace(0, 100, 100_000)).astype(np.float32)
    out = _cascaded_decimate(x, 43)
    assert len(out) < len(x)
    assert len(out) > 0
