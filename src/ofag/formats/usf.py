"""Reading the Universal Sounding Format that ground TEM instruments write."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

__all__ = ["Sweep", "SoundingFile", "read_usf"]


@dataclass(frozen=True)
class Sweep:
    """One transmitter cycle's decay, with the settings it was recorded at."""

    times_s: np.ndarray
    voltages: np.ndarray
    accepted: np.ndarray
    is_noise: bool
    current_a: float
    frequency_hz: float
    loop_side_m: tuple[float, float]
    receiver_area_m2: float
    ramp_time_s: float
    #: The instrument's own error bar per gate, in the voltage's unit, where the file
    #: carries one.
    errors: np.ndarray | None
    #: What the instrument says to add to every gate time, in seconds, and what to
    #: multiply every voltage by.
    time_delay_s: float
    field_shift_factor: float
    channel: str

    @property
    def configuration(self) -> tuple[float, ...]:
        """What makes two sweeps the same measurement, and so stackable."""
        return (
            self.loop_side_m[0],
            self.loop_side_m[1],
            self.receiver_area_m2,
            self.frequency_hz,
            self.ramp_time_s,
            self.time_delay_s,
            self.field_shift_factor,
        )


@dataclass(frozen=True)
class SoundingFile:
    name: str
    easting_m: float
    northing_m: float
    elevation_m: float
    voltage_unit: str
    length_unit: str
    z_direction: str
    sweeps: tuple[Sweep, ...]
    source_path: Path
    #: False where the caller supplied the position the file does not carry.
    location_declared: bool = True


def read_usf(
    path: Path,
    *,
    location: tuple[float, float, float] | None = None,
    z_direction: str | None = None,
) -> SoundingFile:
    """Every sweep in one `.usf`, with the file's own declarations."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    header = _tags(lines)
    required_tags = ["VOLTAGE_UNITS", "LENGTH_UNITS", "LOOP_SIZE"]
    if location is None:
        required_tags.append("LOCATION")
    if z_direction is None:
        required_tags.append("Z_DIRECTION")
    for required in required_tags:
        if required not in header:
            raise ValueError(
                f"{path} does not declare /{required}"
                + (
                    "; pass location= to place a sounding whose file does not"
                    if required == "LOCATION"
                    else ""
                )
            )
    if header["LENGTH_UNITS"].upper() != "M":
        raise ValueError(f"{path} states lengths in {header['LENGTH_UNITS']}, not metres")
    declared = "LOCATION" in header
    place = (
        [float(part) for part in header["LOCATION"].split(",")]
        if declared
        else list(location or ())
    )
    if len(place) != 3:
        raise ValueError(f"{path} /LOCATION must be easting, northing, elevation")
    loop = tuple(float(part) for part in header["LOOP_SIZE"].split(","))
    if len(loop) != 2:
        raise ValueError(f"{path} /LOOP_SIZE must be two side lengths")

    sweeps = tuple(_sweep(block, loop, path) for block in _blocks(lines) if _has_table(block))
    if not sweeps:
        raise ValueError(f"{path} holds no sweeps")
    # `/POINTS` is per sweep in one dialect and the sounding's total in the other,
    # declared once above the first sweep.
    total = sum(sweep.times_s.size for sweep in sweeps)
    if "POINTS" in header and not any("POINTS" in _tags(b) for b in _blocks(lines)):
        if int(float(header["POINTS"])) != total:
            raise ValueError(
                f"{path} declares {header['POINTS']} points and its {len(sweeps)} sweeps "
                f"carry {total}"
            )
    return SoundingFile(
        name=header.get("SOUNDING_NAME", Path(path).stem),
        easting_m=place[0],
        northing_m=place[1],
        elevation_m=place[2],
        voltage_unit=header["VOLTAGE_UNITS"],
        location_declared=declared,
        length_unit=header["LENGTH_UNITS"],
        z_direction=header.get("Z_DIRECTION", z_direction or ""),
        sweeps=sweeps,
        source_path=Path(path),
    )


def _tags(lines: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("/") or stripped.startswith("//") or ":" not in stripped:
            continue
        key, _, value = stripped[1:].partition(":")
        found.setdefault(key.strip(), value.strip())
    return found


def _blocks(lines: list[str]) -> list[list[str]]:
    """The file split at each `/SWEEP_NUMBER`, so a tag belongs to one sweep."""
    blocks: list[list[str]] = []
    for line in lines:
        if line.strip().startswith("/SWEEP_NUMBER:"):
            blocks.append([])
        if blocks:
            blocks[-1].append(line)
    return blocks


def _sweep(block: list[str], loop: tuple[float, ...], path: Path) -> Sweep:
    tags = _tags(block)
    columns = _columns(block, path, tags.get("SWEEP_NUMBER"))
    width = max(columns.values()) + 1
    rows = [_row(line, width) for line in block]
    samples = np.array([row for row in rows if row is not None], dtype=float)
    if "POINTS" in tags and samples.shape[0] != int(float(tags["POINTS"])):
        raise ValueError(
            f"{path} sweep {tags.get('SWEEP_NUMBER')} declares {tags['POINTS']} points "
            f"and carries {samples.shape[0]}"
        )
    quality = columns.get("QUALITY")
    error = columns.get("ERROR_BAR")
    return Sweep(
        times_s=samples[:, columns["TIME"]],
        voltages=samples[:, columns["VOLTAGE"]],
        # The instrument's own verdict on each gate.
        accepted=(
            samples[:, quality].astype(int) == 1
            if quality is not None
            else np.ones(samples.shape[0], dtype=bool)
        ),
        errors=samples[:, error] if error is not None else None,
        is_noise=tags.get("SWEEP_IS_NOISE") == "1",
        current_a=float(tags.get("CURRENT", "0")),
        frequency_hz=float(tags.get("FREQUENCY", "0")),
        loop_side_m=(float(loop[0]), float(loop[1])),
        receiver_area_m2=float(tags.get("COIL_SIZE", "0")),
        ramp_time_s=float(tags.get("RAMP_TIME", "0")),
        time_delay_s=float(tags.get("TIME_DELAY", "0")),
        field_shift_factor=float(tags.get("FIELD_SHIFT_FACTOR", "1")),
        channel=tags.get("CHANNEL", ""),
    )


#: What each column of a sweep's table can be called.
_KNOWN_COLUMNS = ("INDEX", "TIME", "VOLTAGE", "QUALITY", "ERROR_BAR")


def _columns(block: list[str], path: Path, sweep: str | None) -> dict[str, int]:
    """Where each named column sits, read from the table's own heading."""
    for line in block:
        parts = [part.strip().upper() for part in line.replace(",", " ").split() if part.strip()]
        if parts and all(part in _KNOWN_COLUMNS for part in parts):
            found = {name: position for position, name in enumerate(parts)}
            missing = [name for name in ("TIME", "VOLTAGE") if name not in found]
            if missing:
                raise ValueError(
                    f"{path} sweep {sweep} names its columns {parts} and has no "
                    f"{' or '.join(missing)}"
                )
            return found
    raise ValueError(
        f"{path} sweep {sweep} carries no column heading, so which column is the "
        f"traveltime and which the voltage would have to be assumed"
    )


def _has_table(block: list[str]) -> bool:
    """Whether this sweep block carries a table of gates rather than only tags."""
    try:
        _columns(block, Path("."), None)
    except ValueError:
        return False
    return True


def _row(line: str, width: int) -> tuple[float, ...] | None:
    parts = [part for part in line.replace(",", " ").split() if part]
    if len(parts) < width:
        return None
    try:
        return tuple(float(part) for part in parts[:width])
    except ValueError:
        return None


def summarise(soundings: list[SoundingFile]) -> dict[str, Any]:
    """Counts worth printing before anything is inverted."""
    sweeps = [sweep for sounding in soundings for sweep in sounding.sweeps]
    accepted = sum(int(sweep.accepted.sum()) for sweep in sweeps)
    gates = sum(sweep.accepted.size for sweep in sweeps)
    return {
        "soundings": len(soundings),
        "sweeps": len(sweeps),
        "noise_sweeps": sum(1 for sweep in sweeps if sweep.is_noise),
        "configurations": len({sweep.configuration for sweep in sweeps if not sweep.is_noise}),
        "gates": gates,
        "gates_accepted": accepted,
    }
