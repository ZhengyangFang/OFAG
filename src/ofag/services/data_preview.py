"""What a survey looks like before it is inverted, computed from its imported files."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "Pseudosection",
    "TraveltimeCurves",
    "StationValues",
    "SoundingCurves",
    "station_values",
    "sounding_directory",
    "pseudosection",
    "traveltime_curves",
    "PSEUDO_DEPTH_FACTOR",
]

#: Pseudo-depth as a fraction of the four electrodes' spread (Edwards, 1977).
PSEUDO_DEPTH_FACTOR = 0.2


@dataclass(frozen=True)
class Pseudosection:
    midpoint_m: np.ndarray
    pseudo_depth_m: np.ndarray
    apparent_resistivity_ohm_m: np.ndarray
    electrodes_x_m: np.ndarray
    #: Readings dropped because their apparent resistivity is not positive or not
    #: finite: a reversed polarity or a singular geometry, shown as a count rather than
    #: silently as a gap.
    dropped: int


@dataclass(frozen=True)
class TraveltimeCurves:
    #: One entry per shot: the shot's position, and its receivers' positions and
    #: traveltimes in seconds, ordered by position.
    shots: tuple[tuple[float, np.ndarray, np.ndarray], ...]


def _read_column(path: str | Path) -> np.ndarray:
    """The single numeric column of an OFAG observations CSV (a header, then values)."""
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=1).astype(float).reshape(-1)


def pseudosection(
    electrodes_path: str | Path, quadrupoles_path: str | Path, observations_path: str | Path
) -> Pseudosection:
    """Apparent resistivity at each reading's midpoint and pseudo-depth."""
    electrodes = np.asarray(np.load(electrodes_path, allow_pickle=False), dtype=float)
    quadrupoles = np.asarray(np.load(quadrupoles_path, allow_pickle=False), dtype=int)
    resistance = _read_column(observations_path)
    if quadrupoles.ndim != 2 or quadrupoles.shape[1] != 4:
        raise ValueError(
            f"quadrupoles have shape {quadrupoles.shape}; expected (n, 4) as A, B, M, N"
        )
    if quadrupoles.shape[0] != resistance.shape[0]:
        raise ValueError(
            f"{quadrupoles.shape[0]} quadrupoles and {resistance.shape[0]} readings: the files "
            "are not one survey"
        )
    positions = electrodes[:, : min(3, electrodes.shape[1])]

    def inverse_distance(first: np.ndarray, second: np.ndarray) -> np.ndarray:
        present = (first >= 0) & (second >= 0)
        out = np.zeros(first.shape[0])
        distance = np.linalg.norm(positions[first[present]] - positions[second[present]], axis=1)
        with np.errstate(divide="ignore"):
            out[present] = np.where(distance > 0, 1.0 / distance, np.inf)
        return out

    a, b, m, n = (quadrupoles[:, i] for i in range(4))
    denominator = (
        inverse_distance(a, m)
        - inverse_distance(a, n)
        - inverse_distance(b, m)
        + inverse_distance(b, n)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        factor = 2.0 * np.pi / denominator
        apparent = factor * resistance
    x = positions[:, 0]
    used = np.where(quadrupoles >= 0, x[np.clip(quadrupoles, 0, None)], np.nan)
    midpoint = np.nanmean(used, axis=1)
    spread = np.nanmax(used, axis=1) - np.nanmin(used, axis=1)
    keep = np.isfinite(apparent) & (apparent > 0) & np.isfinite(midpoint)
    return Pseudosection(
        midpoint_m=midpoint[keep],
        pseudo_depth_m=PSEUDO_DEPTH_FACTOR * spread[keep],
        apparent_resistivity_ohm_m=apparent[keep],
        electrodes_x_m=x.copy(),
        dropped=int((~keep).sum()),
    )


def traveltime_curves(
    sensors_path: str | Path, pairs_path: str | Path, observations_path: str | Path
) -> TraveltimeCurves:
    """Each shot's first-arrival picks, by receiver position."""
    sensors = np.asarray(np.load(sensors_path, allow_pickle=False), dtype=float)
    pairs = np.asarray(np.load(pairs_path, allow_pickle=False), dtype=int)
    times = _read_column(observations_path)
    if pairs.shape[0] != times.shape[0]:
        raise ValueError(f"{pairs.shape[0]} shot-receiver pairs and {times.shape[0]} picks")
    x = sensors[:, 0]
    shots = []
    for shot in np.unique(pairs[:, 0]):
        rows = pairs[:, 0] == shot
        receivers = x[pairs[rows, 1]]
        order = np.argsort(receivers)
        shots.append((float(x[shot]), receivers[order], times[rows][order]))
    return TraveltimeCurves(shots=tuple(shots))


# -- station surveys and sounding folders ---------------------------------------

#: The permeability of free space, for apparent resistivity from impedance.
MU_0 = 4.0e-7 * np.pi

#: Beyond this many soundings the preview draws an even sample and says so: a thousand
#: overlapping curves show the envelope and nothing else.
MOST_CURVES = 300


@dataclass(frozen=True)
class StationValues:
    x_m: np.ndarray
    y_m: np.ndarray
    values: np.ndarray
    #: The value column's own name, e.g. "gravity_mgal" or "z_m".
    label: str


@dataclass(frozen=True)
class SoundingCurves:
    """Every sounding in a folder, as its method is read."""

    kind: str
    names: tuple[str, ...]
    x: tuple[np.ndarray, ...]
    y: tuple[np.ndarray, ...]
    phase_degrees: tuple[np.ndarray, ...] = ()
    total: int = 0


def station_values(csv_path: str | Path) -> StationValues:
    """A survey of stations -- x, y, then its value in the last column."""
    with open(csv_path, encoding="utf-8") as handle:
        header = handle.readline().strip().split(",")
    data = np.loadtxt(csv_path, delimiter=",", skiprows=1, ndmin=2)
    return StationValues(x_m=data[:, 0], y_m=data[:, 1], values=data[:, -1], label=header[-1])


def sounding_directory(directory: str | Path) -> SoundingCurves | None:
    """The soundings an importer wrote as one CSV each, or None if it wrote none."""
    folder = Path(directory)
    files = sorted(p for p in folder.glob("*.csv") if not p.stem.endswith("_walk"))
    readable = []
    for path in files:
        with open(path, encoding="utf-8") as handle:
            header = handle.readline().strip().split(",")
        readable.append((path, header))
    if not readable:
        return None
    total = len(readable)
    if total > MOST_CURVES:
        picks = np.linspace(0, total - 1, MOST_CURVES).astype(int)
        readable = [readable[i] for i in picks]
    names, xs, ys, phases = [], [], [], []
    kind = ""
    for path, header in readable:
        data = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
        if header[0] == "time_s" and data.shape[1] >= 2:
            kind = "decay"
            xs.append(data[:, 0])
            ys.append(np.abs(data[:, 1]))
        elif header[0] == "frequency_hz" and data.shape[1] >= 3:
            kind = "mt"
            frequency = data[:, 0]
            impedance = data[:, 1] + 1j * data[:, 2]
            xs.append(1.0 / frequency)
            ys.append(np.abs(impedance) ** 2 / (2.0 * np.pi * frequency * MU_0))
            phases.append(np.degrees(np.angle(impedance)))
        elif data.shape[1] == 1:
            kind = "channels"
            xs.append(np.arange(1, data.shape[0] + 1, dtype=float))
            ys.append(data[:, 0])
        else:
            continue
        names.append(path.stem)
    if not names:
        return None
    return SoundingCurves(
        kind=kind,
        names=tuple(names),
        x=tuple(xs),
        y=tuple(ys),
        phase_degrees=tuple(phases),
        total=total,
    )
