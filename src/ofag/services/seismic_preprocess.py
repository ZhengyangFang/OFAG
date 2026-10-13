"""What is done to a field record before an inversion is allowed to fit it."""

from typing import Literal

import numpy as np
from pydantic import Field, model_validator

from ofag.core.constants import QuantityType
from ofag.core.schemas import QuantitySpec, StrictModel
from ofag.core.units import canonicalize_quantity


def _seconds(spec: QuantitySpec) -> float:
    return float(np.asarray(canonicalize_quantity(spec.value, spec.unit, spec.quantity_type)))


def _hertz(spec: QuantitySpec) -> float:
    return float(np.asarray(canonicalize_quantity(spec.value, spec.unit, spec.quantity_type)))


class BandpassSpec(StrictModel):
    """The band the record is trusted in."""

    #: Everything below this is removed: the recording system's drift and the ground
    #: roll a 2D elastic run at these frequencies cannot represent.
    high_pass: QuantitySpec | None = None
    #: Everything above this is removed, usually because the grid cannot propagate it
    #: without dispersing.
    low_pass: QuantitySpec | None = None

    @model_validator(mode="after")
    def corners_are_frequencies(self) -> "BandpassSpec":
        for name, corner in (("high_pass", self.high_pass), ("low_pass", self.low_pass)):
            if corner is not None and corner.quantity_type is not QuantityType.FREQUENCY:
                raise ValueError(f"{name} must be a frequency")
        if self.high_pass is None and self.low_pass is None:
            raise ValueError("a bandpass needs at least one corner; omit it entirely for none")
        if self.high_pass is not None and self.low_pass is not None:
            if _hertz(self.high_pass) >= _hertz(self.low_pass):
                raise ValueError("the high-pass corner is at or above the low-pass corner")
        return self


class MuteSpec(StrictModel):
    """A line through the gather at `offset / velocity + delay`, per channel."""

    #: The apparent velocity the mute follows.
    velocity: QuantitySpec
    #: Added to `offset / velocity`.  Positive keeps more of the record.
    delay: QuantitySpec
    #: Cosine ramp from zero to full amplitude, so the mute edge is not a step -- a step
    #: is broadband and the inversion would fit it.
    taper: QuantitySpec

    @model_validator(mode="after")
    def quantities_are_right(self) -> "MuteSpec":
        if self.velocity.quantity_type is not QuantityType.P_WAVE_VELOCITY:
            raise ValueError("the mute velocity must be a P-wave velocity")
        for name, spec in (("delay", self.delay), ("taper", self.taper)):
            if spec.quantity_type is not QuantityType.TIME:
                raise ValueError(f"the mute {name} must be a time")
        if _seconds(self.taper) < 0:
            raise ValueError("the mute taper cannot be negative")
        if float(np.asarray(self.velocity.value)) <= 0:
            raise ValueError("the mute velocity must be positive")
        return self


#: How the amplitudes of different traces are made comparable, or not.
TraceNormalisation = Literal["none", "rms"]


class SeismicPreprocessingSpec(StrictModel):
    """Everything done to the gathers between the file and the misfit."""

    #: Remove each trace's own mean.
    remove_mean: bool = False
    bandpass: BandpassSpec | None = None
    #: Keep what arrives *after* the line: drops the noise ahead of the first break.
    top_mute: MuteSpec | None = None
    #: Keep what arrives *before* it: drops the ground roll, which is the point of the
    #: pair.
    bottom_mute: MuteSpec | None = None
    #: Multiply by `t ** power`, the usual crude correction for geometrical spreading.
    time_gain_power: float = Field(default=0.0, ge=0.0, le=4.0)
    trace_normalisation: TraceNormalisation = "none"

    def describes_nothing(self) -> bool:
        return (
            not self.remove_mean
            and self.bandpass is None
            and self.top_mute is None
            and self.bottom_mute is None
            and self.time_gain_power == 0.0
            and self.trace_normalisation == "none"
        )


def band_window(sample_count: int, step_s: float, spec: BandpassSpec) -> np.ndarray:
    """The frequency-domain window a bandpass applies."""
    frequencies = np.fft.rfftfreq(sample_count, step_s)
    window = np.ones_like(frequencies)
    if spec.low_pass is not None:
        corner = _hertz(spec.low_pass)
        ramp = np.clip((corner - frequencies) / (0.5 * corner), 0.0, 1.0)
        window *= 0.5 - 0.5 * np.cos(np.pi * ramp)
    if spec.high_pass is not None:
        corner = _hertz(spec.high_pass)
        ramp = np.clip((frequencies - 0.5 * corner) / (0.5 * corner), 0.0, 1.0)
        window *= 0.5 - 0.5 * np.cos(np.pi * ramp)
    return window


def mute_weights(
    offsets_m: np.ndarray,
    sample_count: int,
    step_s: float,
    spec: MuteSpec,
    *,
    keep: Literal["after", "before"] = "after",
) -> np.ndarray:
    """The per-sample weight a mute applies, shaped like the gathers."""
    times = np.arange(sample_count) * step_s
    edge = np.abs(offsets_m) / float(
        np.asarray(
            canonicalize_quantity(
                spec.velocity.value, spec.velocity.unit, spec.velocity.quantity_type
            )
        )
    ) + _seconds(spec.delay)
    # Positive inside the kept side, negative outside it.
    signed = (times[None, None, :] - edge[..., None]) * (1.0 if keep == "after" else -1.0)
    taper = _seconds(spec.taper)
    if taper <= 0:
        return np.asarray(signed >= 0.0, dtype=float)
    ramp = np.clip(signed / taper, 0.0, 1.0)
    return np.asarray(0.5 - 0.5 * np.cos(np.pi * ramp))


def apply_preprocessing(
    gathers: np.ndarray,
    offsets_m: np.ndarray,
    step_s: float,
    spec: SeismicPreprocessingSpec,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Run the declared steps over `(shots, channels, samples)`."""
    if gathers.ndim != 3:
        raise ValueError(f"gathers must be (shots, channels, samples), not {gathers.shape}")
    if offsets_m.shape != gathers.shape[:2]:
        raise ValueError(
            f"one offset per trace is needed: {offsets_m.shape} against {gathers.shape[:2]}"
        )

    processed = np.asarray(gathers, dtype=float)
    applied: list[str] = []

    if spec.remove_mean:
        processed = processed - processed.mean(axis=-1, keepdims=True)
        applied.append("removed each trace's mean")

    if spec.bandpass is not None:
        samples = processed.shape[-1]
        window = band_window(samples, step_s, spec.bandpass)
        processed = np.fft.irfft(np.fft.rfft(processed, axis=-1) * window, n=samples, axis=-1)
        corners = []
        if spec.bandpass.high_pass is not None:
            corners.append(f"above {_hertz(spec.bandpass.high_pass):g} Hz")
        if spec.bandpass.low_pass is not None:
            corners.append(f"below {_hertz(spec.bandpass.low_pass):g} Hz")
        applied.append(f"kept {' and '.join(corners)}, zero-phase")

    sides: tuple[tuple[MuteSpec | None, Literal["after", "before"], str], ...] = (
        (spec.top_mute, "after", "before"),
        (spec.bottom_mute, "before", "after"),
    )
    for mute, keep, word in sides:
        if mute is None:
            continue
        processed = processed * mute_weights(
            offsets_m, processed.shape[-1], step_s, mute, keep=keep
        )
        applied.append(
            f"muted {word} offset / "
            f"{float(np.asarray(mute.velocity.value)):g} "
            f"{mute.velocity.unit} {_seconds(mute.delay):+g} s, "
            f"tapered over {_seconds(mute.taper):g} s"
        )

    if spec.time_gain_power:
        times = np.arange(processed.shape[-1]) * step_s
        processed = processed * times[None, None, :] ** spec.time_gain_power
        applied.append(f"gained by t**{spec.time_gain_power:g}")

    if spec.trace_normalisation == "rms":
        rms = np.sqrt(np.mean(processed**2, axis=-1, keepdims=True))
        # A dead trace stays dead rather than becoming a division by zero.
        processed = np.divide(processed, rms, out=np.zeros_like(processed), where=rms > 0)
        applied.append("normalised each trace by its own RMS")

    return processed, tuple(applied)
