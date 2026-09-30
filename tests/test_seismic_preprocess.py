"""What is done to a field record before an inversion is allowed to fit it."""

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import QuantitySpec
from ofag.services.seismic_preprocess import (
    BandpassSpec,
    MuteSpec,
    SeismicPreprocessingSpec,
    apply_preprocessing,
    band_window,
    mute_weights,
)

STEP_S = 0.002
SAMPLES = 512


def _hz(value: float) -> QuantitySpec:
    return QuantitySpec(value=value, quantity_type=QuantityType.FREQUENCY, unit="Hz")


def _s(value: float) -> QuantitySpec:
    return QuantitySpec(value=value, quantity_type=QuantityType.TIME, unit="s")


def _velocity(value: float) -> QuantitySpec:
    return QuantitySpec(value=value, quantity_type=QuantityType.P_WAVE_VELOCITY, unit="m/s")


def _tone(frequency: float, amplitude: float = 1.0) -> np.ndarray:
    times = np.arange(SAMPLES) * STEP_S
    return amplitude * np.sin(2 * np.pi * frequency * times)


def _gathers(trace: np.ndarray, shots: int = 2, channels: int = 3) -> np.ndarray:
    return np.tile(trace, (shots, channels, 1))


def _offsets(shots: int = 2, channels: int = 3) -> np.ndarray:
    return np.tile(np.arange(channels) * 100.0 + 100.0, (shots, 1))


def test_nothing_declared_leaves_the_data_exactly_as_it_was() -> None:
    """The default is not a mild processing sequence; it is none."""
    gathers = _gathers(_tone(20.0) + 5.0)

    processed, applied = apply_preprocessing(
        gathers, _offsets(), STEP_S, SeismicPreprocessingSpec()
    )

    assert applied == ()
    assert np.array_equal(processed, gathers)


def test_the_mean_removed_is_each_trace_s_own() -> None:
    """A DC offset varies by channel, so a survey-wide mean would leave it."""
    gathers = _gathers(_tone(20.0))
    gathers[0, 1] += 7.0
    gathers[1, 2] -= 3.0

    processed, applied = apply_preprocessing(
        gathers, _offsets(), STEP_S, SeismicPreprocessingSpec(remove_mean=True)
    )

    assert np.allclose(processed.mean(axis=-1), 0.0, atol=1e-12)
    assert applied == ("removed each trace's mean",)


def test_a_bandpass_removes_what_is_outside_the_band_and_keeps_what_is_inside() -> None:
    inside = _tone(20.0)
    outside = _tone(90.0)
    gathers = _gathers(inside + outside)

    processed, _ = apply_preprocessing(
        gathers,
        _offsets(),
        STEP_S,
        SeismicPreprocessingSpec(bandpass=BandpassSpec(high_pass=_hz(5.0), low_pass=_hz(40.0))),
    )

    trace = processed[0, 0]
    # Correlation against each pure tone: the passed one survives, the rejected one is
    # gone.
    assert abs(np.dot(trace, inside)) / np.dot(inside, inside) > 0.9
    assert abs(np.dot(trace, outside)) / np.dot(outside, outside) < 0.02


def test_a_bandpass_does_not_shift_the_arrivals_it_cleans_up() -> None:
    """Zero-phase, because FWI fits phase."""
    times = np.arange(SAMPLES) * STEP_S
    centre = 0.4
    pulse = np.exp(-(((times - centre) / 0.02) ** 2)) * np.sin(2 * np.pi * 20.0 * (times - centre))
    gathers = _gathers(pulse)

    processed, _ = apply_preprocessing(
        gathers,
        _offsets(),
        STEP_S,
        SeismicPreprocessingSpec(bandpass=BandpassSpec(low_pass=_hz(40.0))),
    )

    # Measure the pulse centre from its energy.
    def centre_of_energy(trace: np.ndarray) -> float:
        power = trace**2
        return float(np.sum(times * power) / np.sum(power))

    assert centre_of_energy(pulse) == pytest.approx(centre, abs=1e-6)
    assert centre_of_energy(processed[0, 0]) == pytest.approx(centre, abs=0.2 * STEP_S)


def test_the_band_window_is_tapered_rather_than_a_brick_wall() -> None:
    """A step in frequency rings in time, and the inversion fits the ringing."""
    window = band_window(SAMPLES, STEP_S, BandpassSpec(low_pass=_hz(40.0)))
    frequencies = np.fft.rfftfreq(SAMPLES, STEP_S)

    assert window[0] == pytest.approx(1.0)
    assert window[frequencies > 40.0].max() == pytest.approx(0.0, abs=1e-12)
    # It descends over the last octave instead of stepping: half way down the transition
    # band it is half way down in amplitude, and it never rises.
    transition = window[(frequencies >= 20.0) & (frequencies <= 40.0)]
    assert np.all(np.diff(transition) <= 1e-12)
    # Half way down the band by amplitude, within the resolution of a 0.98 Hz frequency
    # grid.
    assert window[int(np.argmin(np.abs(frequencies - 30.0)))] == pytest.approx(0.5, abs=0.05)


def test_a_bandpass_with_no_corner_is_refused_rather_than_being_a_no_op() -> None:
    with pytest.raises(ValidationError, match="at least one corner"):
        BandpassSpec()


def test_corners_the_wrong_way_round_are_refused() -> None:
    with pytest.raises(ValidationError, match="at or above"):
        BandpassSpec(high_pass=_hz(40.0), low_pass=_hz(20.0))


def test_the_mute_follows_the_offset_rather_than_cutting_a_flat_time() -> None:
    """The arrival moves out with offset, so the mute has to."""
    offsets = np.array([[100.0, 400.0]])
    weights = mute_weights(
        offsets,
        SAMPLES,
        STEP_S,
        MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.0)),
    )

    times = np.arange(SAMPLES) * STEP_S
    near = times[int(np.argmax(weights[0, 0] > 0))]
    far = times[int(np.argmax(weights[0, 1] > 0))]
    assert near == pytest.approx(0.1, abs=STEP_S)
    assert far == pytest.approx(0.4, abs=STEP_S)


def test_the_mute_edge_is_tapered_so_it_is_not_fitted_as_an_arrival() -> None:
    """A step is broadband; the inversion would build structure to explain it."""
    offsets = np.array([[200.0]])
    mute = MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.04))

    weights = mute_weights(offsets, SAMPLES, STEP_S, mute)[0, 0]

    assert weights[: int(0.2 / STEP_S)].max() == pytest.approx(0.0, abs=1e-12)
    assert weights[-1] == pytest.approx(1.0)
    partial = weights[int(0.2 / STEP_S) : int(0.24 / STEP_S)]
    assert np.all(np.diff(partial) >= -1e-12)
    assert 0.0 < partial.max() < 1.0


def test_the_delay_moves_the_mute_later_so_more_of_the_record_survives() -> None:
    offsets = np.array([[100.0]])
    without = mute_weights(
        offsets,
        SAMPLES,
        STEP_S,
        MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.0)),
    )
    with_delay = mute_weights(
        offsets,
        SAMPLES,
        STEP_S,
        MuteSpec(velocity=_velocity(1000.0), delay=_s(0.05), taper=_s(0.0)),
    )

    assert with_delay.sum() < without.sum()


def test_a_mute_velocity_that_is_not_a_velocity_is_refused() -> None:
    with pytest.raises(ValidationError, match="P-wave velocity"):
        MuteSpec(velocity=_hz(1000.0), delay=_s(0.0), taper=_s(0.0))


def test_the_gain_grows_with_time_rather_than_scaling_the_record() -> None:
    """t**2 is a claim about spreading; a constant would just be a scale."""
    gathers = _gathers(np.ones(SAMPLES))

    processed, applied = apply_preprocessing(
        gathers, _offsets(), STEP_S, SeismicPreprocessingSpec(time_gain_power=2.0)
    )

    times = np.arange(SAMPLES) * STEP_S
    assert np.allclose(processed[0, 0], times**2)
    assert applied == ("gained by t**2",)


def test_rms_normalisation_makes_a_quiet_far_trace_weigh_as_much_as_a_loud_near_one() -> None:
    gathers = np.stack([np.stack([_tone(20.0, 100.0), _tone(20.0, 0.1)])])

    processed, _ = apply_preprocessing(
        gathers,
        np.array([[100.0, 2000.0]]),
        STEP_S,
        SeismicPreprocessingSpec(trace_normalisation="rms"),
    )

    energies = np.sqrt(np.mean(processed**2, axis=-1))
    assert energies[0, 0] == pytest.approx(energies[0, 1], rel=1e-9)


def test_a_dead_trace_stays_dead_rather_than_dividing_by_zero() -> None:
    gathers = np.stack([np.stack([_tone(20.0), np.zeros(SAMPLES)])])

    processed, _ = apply_preprocessing(
        gathers,
        np.array([[100.0, 200.0]]),
        STEP_S,
        SeismicPreprocessingSpec(trace_normalisation="rms"),
    )

    assert np.all(np.isfinite(processed))
    assert not processed[0, 1].any()


def test_the_steps_run_in_the_order_the_record_says_they_did() -> None:
    """Order matters: gaining before muting amplifies what the mute removes."""
    gathers = _gathers(_tone(20.0) + 3.0)
    spec = SeismicPreprocessingSpec(
        remove_mean=True,
        bandpass=BandpassSpec(low_pass=_hz(40.0)),
        top_mute=MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.01)),
        time_gain_power=1.0,
        trace_normalisation="rms",
    )

    _, applied = apply_preprocessing(gathers, _offsets(), STEP_S, spec)

    assert applied == (
        "removed each trace's mean",
        "kept below 40 Hz, zero-phase",
        "muted before offset / 1000 m/s +0 s, tapered over 0.01 s",
        "gained by t**1",
        "normalised each trace by its own RMS",
    )


def test_an_offset_per_trace_is_required_because_the_mute_needs_one() -> None:
    with pytest.raises(ValueError, match="one offset per trace"):
        apply_preprocessing(
            _gathers(_tone(20.0)), np.array([100.0, 200.0]), STEP_S, SeismicPreprocessingSpec()
        )


def test_a_bottom_mute_keeps_what_arrives_before_the_line() -> None:
    """The other half, and the one a land record actually needs."""
    offsets = np.array([[100.0, 400.0]])
    mute = MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.0))

    weights = mute_weights(offsets, SAMPLES, STEP_S, mute, keep="before")

    times = np.arange(SAMPLES) * STEP_S
    # Kept up to offset/velocity, then gone -- the mirror of the top mute.
    assert weights[0, 0][times < 0.1].min() == pytest.approx(1.0)
    assert weights[0, 0][times > 0.1].max() == pytest.approx(0.0, abs=1e-12)
    assert weights[0, 1][times < 0.4].min() == pytest.approx(1.0)
    assert weights[0, 1][times > 0.4].max() == pytest.approx(0.0, abs=1e-12)


def test_the_two_mutes_are_the_same_line_read_from_opposite_sides() -> None:
    offsets = np.array([[250.0]])
    mute = MuteSpec(velocity=_velocity(800.0), delay=_s(0.05), taper=_s(0.0))

    after = mute_weights(offsets, SAMPLES, STEP_S, mute, keep="after")
    before = mute_weights(offsets, SAMPLES, STEP_S, mute, keep="before")

    # Every sample belongs to exactly one side; nothing is dropped by both or kept by
    # both, which is what makes a pair of them a window.
    assert np.all(after + before == 1.0)


def test_a_bottom_mute_tapers_into_the_side_it_keeps() -> None:
    """Backwards from the top mute's ramp, not a second piece of arithmetic."""
    offsets = np.array([[200.0]])
    mute = MuteSpec(velocity=_velocity(1000.0), delay=_s(0.0), taper=_s(0.04))

    weights = mute_weights(offsets, SAMPLES, STEP_S, mute, keep="before")[0, 0]

    times = np.arange(SAMPLES) * STEP_S
    assert weights[times < 0.16].min() == pytest.approx(1.0)
    assert weights[times > 0.20].max() == pytest.approx(0.0, abs=1e-12)
    ramp = weights[(times >= 0.16) & (times <= 0.20)]
    assert np.all(np.diff(ramp) <= 1e-12)


def test_the_pair_keeps_only_the_cone_the_body_waves_live_in() -> None:
    """Which is the whole point: first breaks in, ground roll out."""
    times = np.arange(SAMPLES) * STEP_S
    # Short enough that the 335 m/s ground roll is inside a 1.02 s record at every one
    # of them; on the real line, at 1,460 m, it is not, which is a separate problem the
    # setup page now reports.
    offsets = np.array([[100.0, 200.0, 300.0]])
    refraction = offsets[0] / 2100.0
    ground_roll = offsets[0] / 335.0
    gathers = np.zeros((1, 3, SAMPLES))
    for channel, (early, late) in enumerate(zip(refraction, ground_roll, strict=True)):
        gathers[0, channel] += np.exp(-(((times - early) / 0.02) ** 2))
        gathers[0, channel] += 8.0 * np.exp(-(((times - late) / 0.05) ** 2))

    processed, applied = apply_preprocessing(
        gathers,
        offsets,
        STEP_S,
        SeismicPreprocessingSpec(
            top_mute=MuteSpec(velocity=_velocity(6000.0), delay=_s(-0.05), taper=_s(0.02)),
            bottom_mute=MuteSpec(velocity=_velocity(800.0), delay=_s(0.05), taper=_s(0.05)),
        ),
    )

    assert applied == (
        "muted before offset / 6000 m/s -0.05 s, tapered over 0.02 s",
        "muted after offset / 800 m/s +0.05 s, tapered over 0.05 s",
    )
    for channel in range(3):
        kept, raw = processed[0, channel], gathers[0, channel]
        around_refraction = np.abs(times - refraction[channel]) < 0.03
        around_ground_roll = np.abs(times - ground_roll[channel]) < 0.10
        # As a ratio against what was there before, which is the claim: an absolute
        # threshold would only be measuring the tail of a Gaussian reaching through the
        # taper into the side that is kept.
        assert kept[around_refraction].max() / raw[around_refraction].max() > 0.8
        suppression = np.abs(kept[around_ground_roll]).max() / np.abs(raw[around_ground_roll]).max()
        assert suppression < 0.05
