"""Stack repeated TEM sweeps into one decay per configuration, with its scatter."""

import math
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import Field, model_validator

from ofag.core.schemas import CoordinateConvention, StrictModel
from ofag.formats.usf import SoundingFile, Sweep, read_usf
from ofag.services.import_store import DEFAULT_IMPORT_ROOT, ImportStore

__all__ = ["TemImportRequest", "StackedCurve", "ImportedTemSoundings", "TemImportService"]

#: Volts per amp per square metre is already normalised by the transmitter current and
#: the receiver's effective area, so the recorded number is the rate of change of the
#: field per unit source current.
NORMALISED_VOLTAGE_UNIT = "V/AM2"

#: The same measurement with the transmitter current left in.
UNNORMALISED_VOLTAGE_UNIT = "V/M2"

#: A recorded voltage and the field's rate of change point opposite ways.
VOLTAGE_TO_FIELD_DERIVATIVE = -1.0

#: The only z convention this service handles; see `VOLTAGE_TO_FIELD_DERIVATIVE`.
SUPPORTED_Z_DIRECTION = "DOWN"


def equal_area_radius_m(side_a: float, side_b: float) -> float:
    """The circular loop that encloses the same area as a rectangular one."""
    if side_a <= 0 or side_b <= 0:
        raise ValueError(f"a transmitter loop cannot have sides {side_a} by {side_b}")
    return float(np.sqrt(side_a * side_b / np.pi))


@dataclass(frozen=True)
class StackedCurve:
    """One configuration at one site, averaged over its repeats."""

    sounding_id: str
    easting_m: float
    northing_m: float
    elevation_m: float
    times_s: np.ndarray
    #: Mean of the accepted sweeps as dB/dt per amp of source current, in T/s/A, which
    #: is the recorded V/Am² with Faraday's sign applied.
    values: np.ndarray
    #: Standard error of that mean. Measured, not declared.
    uncertainty: np.ndarray
    repeats: np.ndarray
    loop_side_m: tuple[float, float]
    receiver_area_m2: float
    frequency_hz: float
    ramp_time_s: float
    observations_path: str

    @property
    def loop_radius_m(self) -> float:
        return equal_area_radius_m(*self.loop_side_m)

    @property
    def configuration_id(self) -> str:
        return (
            f"{self.loop_side_m[0]:.0f}x{self.loop_side_m[1]:.0f}m"
            f"-{self.receiver_area_m2:.0f}m2-{self.frequency_hz:.0f}Hz"
        )


@dataclass(frozen=True)
class ImportedTemSoundings:
    dataset_id: UUID
    curves: tuple[StackedCurve, ...]
    sweeps_read: int
    sweeps_rejected_as_noise: int
    gates_read: int
    gates_rejected_by_instrument: int
    gates_dropped_for_too_few_repeats: int
    #: Gates rejected as too soon after the turn-off to be a measurement of the ground,
    #: by `earliest_gate_ramp_multiples`.
    gates_dropped_as_too_early: int
    directory: str


class TemImportRequest(StrictModel):
    """Where the soundings are, and what the files do not say about themselves."""

    source_directory: str = Field(min_length=1)
    coordinate_convention: CoordinateConvention
    #: A gate needs repeats before its scatter means anything.
    minimum_repeats: int = Field(default=5, ge=1)
    #: Sweeps the instrument recorded with the transmitter off.
    include_noise_sweeps: bool = False
    #: Apply the per-sweep `/TIME_DELAY` and `/FIELD_SHIFT_FACTOR` the instrument states
    #: about itself.
    apply_instrument_calibration: bool = True
    #: Gates earlier than this many turn-off ramps are rejected.
    earliest_gate_ramp_multiples: float = Field(default=3.0, ge=0.0)
    #: What the file's declared ramp times have to be multiplied by.
    declared_ramp_time_scale: float = Field(default=1.0, gt=0.0)
    #: Easting, northing and elevation for files that declare no `/LOCATION`.
    default_location_m: tuple[float, float, float] | None = None
    #: Which way z points, for files that declare no `/Z_DIRECTION`.
    default_z_direction: str | None = None

    @model_validator(mode="after")
    def the_directory_holds_soundings(self) -> "TemImportRequest":
        directory = Path(self.source_directory)
        if not directory.is_dir():
            raise ValueError(f"{self.source_directory} is not a directory")
        if not any(directory.glob("*.usf")):
            raise ValueError(f"{self.source_directory} holds no .usf soundings")
        return self


@dataclass(frozen=True)
class TemImportService:
    import_root: Path = DEFAULT_IMPORT_ROOT

    def import_usf_directory(self, request: TemImportRequest) -> ImportedTemSoundings:
        store = ImportStore(root=self.import_root)
        dataset_id, directory = store.new_dataset()
        files = sorted(Path(request.source_directory).glob("*.usf"))
        soundings = [
            read_usf(
                path,
                location=request.default_location_m,
                z_direction=request.default_z_direction,
            )
            for path in files
        ]
        for sounding in soundings:
            if sounding.z_direction.strip().upper() != SUPPORTED_Z_DIRECTION:
                raise ValueError(
                    f"{sounding.source_path} records z as "
                    f"{sounding.z_direction.strip() or 'nothing'}, and this service handles "
                    f"{SUPPORTED_Z_DIRECTION}: Faraday's sign is applied on that assumption, so "
                    "the other convention would invert the negative of the ground"
                )
        soundings = [_normalised_by_current(sounding) for sounding in soundings]

        identifiers = [_identifier(sounding) for sounding in soundings]
        clashing = sorted({name for name in identifiers if identifiers.count(name) > 1})
        if clashing:
            raise ValueError(
                "two soundings would be written to the same file: " + ", ".join(clashing)
            )

        curves: list[StackedCurve] = []
        read = noise = gates = rejected = thin = early = 0
        for sounding in soundings:
            read += len(sounding.sweeps)
            usable = [
                sweep
                for sweep in sounding.sweeps
                if request.include_noise_sweeps or not sweep.is_noise
            ]
            noise += len(sounding.sweeps) - len(usable)
            for sweep in sounding.sweeps:
                gates += sweep.accepted.size
                rejected += int((~sweep.accepted).sum())
            for configuration in sorted({sweep.configuration for sweep in usable}):
                group = [sweep for sweep in usable if sweep.configuration == configuration]
                stacked, dropped = _stack(group, request.minimum_repeats)
                thin += dropped
                if stacked is None:
                    continue
                times, voltages, spread, repeats = stacked
                shift = group[0].field_shift_factor if request.apply_instrument_calibration else 1.0
                delay = group[0].time_delay_s if request.apply_instrument_calibration else 0.0
                times = times + delay
                values = VOLTAGE_TO_FIELD_DERIVATIVE * shift * voltages
                spread = shift * spread
                ramp_s = group[0].ramp_time_s * request.declared_ramp_time_scale
                _refuse_an_impossible_ramp(
                    ramp_s, group[0].loop_side_m, group[0].current_a, _identifier(sounding)
                )
                usable_gates = times >= request.earliest_gate_ramp_multiples * ramp_s
                early += int((~usable_gates).sum())
                if not usable_gates.any():
                    continue
                times, values = times[usable_gates], values[usable_gates]
                spread, repeats = spread[usable_gates], repeats[usable_gates]
                identifier = f"{_identifier(sounding)}-{_configuration_id(group[0])}"
                path = directory / f"{identifier}.csv"
                _write(path, times, values, spread)
                curves.append(
                    StackedCurve(
                        sounding_id=identifier,
                        easting_m=sounding.easting_m,
                        northing_m=sounding.northing_m,
                        elevation_m=sounding.elevation_m,
                        times_s=times,
                        values=values,
                        uncertainty=spread,
                        repeats=repeats,
                        loop_side_m=group[0].loop_side_m,
                        receiver_area_m2=group[0].receiver_area_m2,
                        frequency_hz=group[0].frequency_hz,
                        ramp_time_s=ramp_s,
                        observations_path=path.as_posix(),
                    )
                )
        return ImportedTemSoundings(
            dataset_id=dataset_id,
            curves=tuple(curves),
            sweeps_read=read,
            sweeps_rejected_as_noise=noise,
            gates_read=gates,
            gates_rejected_by_instrument=rejected,
            gates_dropped_for_too_few_repeats=thin,
            gates_dropped_as_too_early=early,
            directory=directory.as_posix(),
        )


def _stack(
    group: list[Sweep], minimum_repeats: int
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None, int]:
    """Average one configuration's repeats gate by gate, and measure the scatter."""
    times = np.unique(np.concatenate([sweep.times_s for sweep in group]))
    values: list[float] = []
    spread: list[float] = []
    repeats: list[int] = []
    kept: list[float] = []
    dropped = 0
    for time in times:
        samples = [
            float(sweep.voltages[index])
            for sweep in group
            for index in np.flatnonzero((sweep.times_s == time) & sweep.accepted)
        ]
        stated = [
            float(sweep.errors[index])
            for sweep in group
            if sweep.errors is not None
            for index in np.flatnonzero((sweep.times_s == time) & sweep.accepted)
        ]
        if len(samples) < max(1, minimum_repeats):
            dropped += 1
            continue
        column = np.asarray(samples, dtype=float)
        if column.size >= 2:
            # The standard error of the mean, which is what the stacked value's own
            # uncertainty is.
            uncertainty = float(column.std(ddof=1) / np.sqrt(column.size))
        elif stated:
            # Measured once, so there is no scatter to take; the instrument's own error
            # bar is the only statement about this gate there is.
            uncertainty = float(stated[0])
        else:
            raise ValueError(
                f"the gate at {time:.6g} s was measured once and the file states no error bar "
                "for it, so it has no uncertainty; raise minimum_repeats or use a file that "
                "carries one"
            )
        kept.append(float(time))
        values.append(float(column.mean()))
        spread.append(uncertainty)
        repeats.append(column.size)
    if not kept:
        return None, dropped
    return (
        np.asarray(kept),
        np.asarray(values),
        np.asarray(spread),
        np.asarray(repeats, dtype=int),
    ), dropped


#: The most a ground TEM transmitter is taken to put across its loop, in volts.
MAX_TRANSMITTER_VOLTS = 2000.0

#: Past this a "ramp" is something else -- a base frequency, a gate, a typo.
LONGEST_CREDIBLE_RAMP_S = 5e-3


def _square_loop_inductance_h(side_m: float, conductor_radius_m: float = 0.005) -> float:
    """A square loop's self-inductance, to the order the check needs."""
    return 2 * 4e-7 * side_m * (math.log(side_m / conductor_radius_m) - 0.774)


def _refuse_an_impossible_ramp(
    ramp_s: float, loop_m: tuple[float, float], current_a: float, sounding_id: str
) -> None:
    """A declared ramp no transmitter could produce is refused, not used."""
    if ramp_s == 0.0:
        return
    side_m = max(loop_m)
    floor_s = _square_loop_inductance_h(side_m) * abs(current_a) / MAX_TRANSMITTER_VOLTS
    if floor_s <= ramp_s <= LONGEST_CREDIBLE_RAMP_S:
        return
    inductance_mh = _square_loop_inductance_h(side_m) * 1e3
    raise ValueError(
        f"sounding {sounding_id} declares a turn-off ramp of {ramp_s:.3g} s. A {side_m:g} m "
        f"loop is about {inductance_mh:.2f} mH, so switching {abs(current_a):g} A out of it "
        f"needs at least {floor_s:.3g} s even at {MAX_TRANSMITTER_VOLTS:g} V, and anything "
        f"past {LONGEST_CREDIBLE_RAMP_S:g} s is not a turn-off. Used as declared the "
        f"earliest-gate rule compares the gates against a threshold that reaches none of "
        f"them and drops nothing; set declared_ramp_time_scale if the file's unit is wrong."
    )


def _identifier(sounding: SoundingFile) -> str:
    """A name for this sounding that is actually unique."""
    stem = "".join(char if char.isalnum() else "-" for char in sounding.source_path.stem)
    return stem.strip("-")


def _configuration_id(sweep: Sweep) -> str:
    return (
        f"{sweep.loop_side_m[0]:.0f}x{sweep.loop_side_m[1]:.0f}m"
        f"-{sweep.receiver_area_m2:.0f}m2-{sweep.frequency_hz:.0f}Hz"
    )


#: The column the TDEM plugins read a decay from, for this quantity.
RESPONSE_COLUMN = "magnetic_flux_density_time_derivative_t_s"


def _write(path: Path, times: np.ndarray, values: np.ndarray, spread: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"time_s,{RESPONSE_COLUMN},uncertainty_t_s"]
    lines += [f"{t:.9e},{v:.9e},{s:.9e}" for t, v, s in zip(times, values, spread, strict=True)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _normalised_by_current(sounding: SoundingFile) -> SoundingFile:
    """Divide the transmitter current out, where the file has not."""
    unit = sounding.voltage_unit.upper().replace(" ", "")
    if unit == NORMALISED_VOLTAGE_UNIT:
        return sounding
    if unit != UNNORMALISED_VOLTAGE_UNIT:
        raise ValueError(
            f"{sounding.source_path} records {sounding.voltage_unit}, and this service reads "
            f"{NORMALISED_VOLTAGE_UNIT} or {UNNORMALISED_VOLTAGE_UNIT}: a voltage normalised by "
            "neither would need the receiver effective area, which varies sweep to sweep"
        )
    sweeps = []
    for sweep in sounding.sweeps:
        if sweep.current_a <= 0:
            raise ValueError(
                f"{sounding.source_path} states {sounding.voltage_unit} but declares a "
                f"transmitter current of {sweep.current_a} A, so it cannot be divided out"
            )
        # The error bar is scaled with the value it belongs to.
        sweeps.append(
            replace(
                sweep,
                voltages=sweep.voltages / sweep.current_a,
                errors=None if sweep.errors is None else sweep.errors / sweep.current_a,
            )
        )
    return replace(sounding, sweeps=tuple(sweeps), voltage_unit=NORMALISED_VOLTAGE_UNIT)
