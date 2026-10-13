"""Reading a magnetotelluric EDI, including the spectra form that carries no impedance."""

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "Station",
    "read_edi",
    "SCALAR_IMPEDANCES",
    "scalar_impedance",
    "scalar_uncertainty_ohm",
    "effective_impedance",
    "one_dimensionality",
    "rotate",
    "phase_tensor",
    "phase_tensor_invariants",
    "PhaseTensorInvariants",
    "apparent_resistivity_ohm_m",
    "impedance_phase_degrees",
    "impedance_uncertainty_ohm",
]

#: Magnetic permeability of free space, for apparent resistivity.
MU0 = 4.0e-7 * np.pi

#: What an EDI means by its numbers, which it never says.
EDI_IMPEDANCE_TO_OHM = 1.0e3 * MU0


@dataclass(frozen=True)
class Station:
    """One site: where it is, and its spectra at every frequency."""

    name: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    channels: tuple[str, ...]
    frequencies_hz: np.ndarray
    #: `(frequency, channel, channel)` Hermitian cross-power matrices.
    spectra: np.ndarray
    #: How many spectral estimates each block averages, from its own AVGF.
    averages: np.ndarray
    source_path: Path

    def channel(self, name: str, occurrence: int = 0) -> int:
        """Where a channel sits in the spectral matrix."""
        found = [index for index, label in enumerate(self.channels) if label == name.upper()]
        if len(found) <= occurrence:
            raise ValueError(
                f"{self.name} has {len(found)} {name.upper()} channels, and #{occurrence} "
                f"was asked for; it records {', '.join(self.channels)}"
            )
        return found[occurrence]

    def impedance(self, remote: bool = True) -> np.ndarray:
        """The impedance tensor at every frequency in ohms, as `(frequency, 2, 2)`."""
        ex, ey = self.channel("EX"), self.channel("EY")
        hx, hy = self.channel("HX"), self.channel("HY")
        if remote:
            rx, ry = self.channel("HX", 1), self.channel("HY", 1)
        else:
            rx, ry = hx, hy
        tensor = np.empty((len(self.frequencies_hz), 2, 2), dtype=complex)
        for index in range(len(self.frequencies_hz)):
            s = self.spectra[index]
            left = np.array([[s[hx, rx], s[hy, rx]], [s[hx, ry], s[hy, ry]]])
            for row, electric in enumerate((ex, ey)):
                right = np.array([s[electric, rx], s[electric, ry]])
                tensor[index, row] = np.linalg.solve(left, right)
        return tensor * EDI_IMPEDANCE_TO_OHM


def _impedance_uncertainty(station: "Station", tensor: np.ndarray) -> np.ndarray:
    """One standard deviation on each impedance element, from the spectra."""
    ex, ey = station.channel("EX"), station.channel("EY")
    hx, hy = station.channel("HX"), station.channel("HY")
    deviation = np.empty((len(station.frequencies_hz), 2, 2))
    for index in range(len(station.frequencies_hz)):
        spectra = station.spectra[index]
        magnetic = np.array(
            [[spectra[hx, hx], spectra[hx, hy]], [spectra[hy, hx], spectra[hy, hy]]]
        )
        inverse = np.linalg.inv(magnetic)
        for row, electric in enumerate((ex, ey)):
            impedance = tensor[index, row] / EDI_IMPEDANCE_TO_OHM
            cross = np.array([spectra[electric, hx], spectra[electric, hy]])
            residual = float(
                np.real(spectra[electric, electric] - np.sum(impedance * np.conj(cross)))
            )
            freedom = max(1, int(station.averages[index]))
            variance = max(residual, 0.0) * np.real(np.diag(inverse)) / freedom
            deviation[index, row] = np.sqrt(np.maximum(variance, 0.0))
    return deviation * EDI_IMPEDANCE_TO_OHM


def read_edi(path: Path) -> Station:
    """One station from an EDI in the spectra form."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    head = _head(text)
    channels = _channels(text)
    if not channels:
        raise ValueError(f"{path} declares no channels in its DEFINEMEAS block")
    blocks = list(re.finditer(r">SPECTRA\s+([^\n]*)\n(.*?)(?=^>|\Z)", text, re.S | re.M))
    if not blocks:
        raise ValueError(
            f"{path} holds no >SPECTRA blocks; an EDI carrying an impedance directly "
            "is a different form and this does not read it"
        )
    count = len(channels)
    frequencies: list[float] = []
    matrices: list[np.ndarray] = []
    counts: list[int] = []
    for block in blocks:
        frequency = re.search(r"FREQ\s*=\s*([\dEe.+-]+)", block.group(1))
        if frequency is None:
            raise ValueError(f"{path} has a >SPECTRA block with no FREQ")
        values = np.array([float(item) for item in block.group(2).split()], dtype=float)
        if values.size != count * count:
            raise ValueError(
                f"{path} at {frequency.group(1)} Hz carries {values.size} numbers for "
                f"{count} channels, and a cross-power matrix needs {count * count}"
            )
        frequencies.append(float(frequency.group(1)))
        matrices.append(_hermitian(values.reshape(count, count)))
        averaged = re.search(r"AVGF\s*=\s*(\d+)", block.group(1))
        counts.append(int(averaged.group(1)) if averaged else 1)
    return Station(
        name=head.get("SECTID") or head.get("DATAID") or Path(path).stem,
        latitude_deg=_degrees(head["LAT"]),
        longitude_deg=_degrees(head["LONG"]),
        elevation_m=float(head.get("ELEV", "0")),
        channels=channels,
        frequencies_hz=np.asarray(frequencies),
        spectra=np.asarray(matrices),
        averages=np.asarray(counts, dtype=int),
        source_path=Path(path),
    )


def _hermitian(raw: np.ndarray) -> np.ndarray:
    """Rebuild the complex cross-power matrix from the way an EDI stores it."""
    real = np.tril(raw)
    imaginary = np.triu(raw, 1)
    lower = real + 1j * imaginary.T
    return lower + np.conjugate(np.tril(lower, -1)).T


def _head(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in re.finditer(r"^\s*([A-Z]+)\s*=\s*\"?([^\"\n]+?)\"?\s*$", text, re.M):
        found.setdefault(match.group(1), match.group(2).strip())
    return found


def _channels(text: str) -> tuple[str, ...]:
    """Channel order as DEFINEMEAS declares it, which is the matrix's order."""
    return tuple(
        match.group(1).upper()
        for match in re.finditer(r"^>[EH]MEAS\b[^\n]*?CHTYPE\s*=\s*(\w+)", text, re.M)
    )


def _degrees(text: str) -> float:
    """A latitude written as degrees:minutes:seconds, or already decimal."""
    stripped = text.strip()
    sign = -1.0 if stripped.startswith("-") else 1.0
    parts = stripped.lstrip("+-").split(":")
    total = 0.0
    for power, part in enumerate(parts):
        total += float(part) / 60.0**power
    return sign * total


#: The scalar impedances a layered inversion can be given, and what each one is.
SCALAR_IMPEDANCES = ("xy", "yx", "average", "determinant")


def scalar_impedance(tensor: np.ndarray, kind: str = "xy") -> np.ndarray:
    """One impedance per frequency from the tensor, as `(frequency,)`."""
    if kind not in SCALAR_IMPEDANCES:
        raise ValueError(f"unknown scalar impedance {kind!r}; one of {SCALAR_IMPEDANCES}")
    tensor = np.asarray(tensor)
    zxx, zxy = tensor[..., 0, 0], tensor[..., 0, 1]
    zyx, zyy = tensor[..., 1, 0], tensor[..., 1, 1]
    if kind == "xy":
        return np.asarray(-zxy)
    if kind == "yx":
        return np.asarray(zyx)
    if kind == "average":
        return np.asarray((zyx - zxy) / 2.0)
    return np.asarray(-np.sqrt(np.asarray(zxx * zyy - zxy * zyx, dtype=complex)))


def scalar_uncertainty_ohm(deviation: np.ndarray, kind: str = "xy") -> np.ndarray:
    """The uncertainty on `scalar_impedance`, from the per-element one."""
    if kind not in SCALAR_IMPEDANCES:
        raise ValueError(f"unknown scalar impedance {kind!r}; one of {SCALAR_IMPEDANCES}")
    deviation = np.asarray(deviation)
    if kind == "xy":
        return np.asarray(deviation[..., 0, 1])
    if kind == "yx":
        return np.asarray(deviation[..., 1, 0])
    return np.asarray(0.5 * np.hypot(deviation[..., 0, 1], deviation[..., 1, 0]))


def effective_impedance(tensor: np.ndarray) -> np.ndarray:
    """The average of the two off-diagonals."""
    return scalar_impedance(tensor, "average")


def one_dimensionality(tensor: np.ndarray) -> np.ndarray:
    """How far each frequency is from the layered case, from 0 to 1."""
    tensor = np.asarray(tensor)
    zxy, zyx = tensor[..., 0, 1], tensor[..., 1, 0]
    difference = np.abs(zyx - zxy)
    # Divided only where it can be.
    return np.asarray(
        np.divide(
            np.abs(zxy + zyx),
            difference,
            out=np.full(np.shape(difference), np.inf),
            where=difference > 0,
        )
    )


def rotate(tensor: np.ndarray, degrees: float) -> np.ndarray:
    """The tensor as it would read with the axes turned clockwise by `degrees`."""
    angle = np.radians(degrees)
    rotation = np.array(
        [[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]], dtype=float
    )
    return np.asarray(rotation @ np.asarray(tensor) @ rotation.T)


def phase_tensor(tensor: np.ndarray) -> np.ndarray:
    """The phase tensor, as `(frequency, 2, 2)` and real."""
    tensor = np.asarray(tensor)
    real, imaginary = np.real(tensor), np.imag(tensor)
    determinant = real[..., 0, 0] * real[..., 1, 1] - real[..., 0, 1] * real[..., 1, 0]
    inverse = np.empty_like(real)
    inverse[..., 0, 0] = real[..., 1, 1]
    inverse[..., 1, 1] = real[..., 0, 0]
    inverse[..., 0, 1] = -real[..., 0, 1]
    inverse[..., 1, 0] = -real[..., 1, 0]
    inverse = inverse / determinant[..., None, None]
    return np.asarray(inverse @ imaginary)


@dataclass(frozen=True)
class PhaseTensorInvariants:
    """What the phase tensor says about the ground, free of distortion."""

    #: Principal values. Equal over a layered earth.
    minimum: np.ndarray
    maximum: np.ndarray
    #: The skew angle beta.
    skew_degrees: np.ndarray
    #: Regional strike, modulo 90 degrees -- the tensor cannot tell which of two
    #: perpendicular directions is along structure.
    strike_degrees: np.ndarray
    #: `(max - min) / (max + min)`, zero over a layered earth and one where the two
    #: principal directions could not be more different.
    ellipticity: np.ndarray


def phase_tensor_invariants(tensor: np.ndarray) -> PhaseTensorInvariants:
    """The rotational invariants of `phase_tensor`, per frequency."""
    phi = phase_tensor(tensor)
    trace_half = (phi[..., 0, 0] + phi[..., 1, 1]) / 2.0
    skew_half = (phi[..., 0, 1] - phi[..., 1, 0]) / 2.0
    determinant = phi[..., 0, 0] * phi[..., 1, 1] - phi[..., 0, 1] * phi[..., 1, 0]
    # Caldwell's Phi_1, Phi_2, Phi_3.
    centre = np.hypot(trace_half, skew_half)
    radius = np.sqrt(np.maximum(centre**2 - np.abs(determinant), 0.0))
    maximum, minimum = centre + radius, centre - radius
    beta = 0.5 * np.arctan2(phi[..., 0, 1] - phi[..., 1, 0], phi[..., 0, 0] + phi[..., 1, 1])
    alpha = 0.5 * np.arctan2(phi[..., 0, 1] + phi[..., 1, 0], phi[..., 0, 0] - phi[..., 1, 1])
    total = maximum + minimum
    return PhaseTensorInvariants(
        minimum=np.asarray(minimum),
        maximum=np.asarray(maximum),
        skew_degrees=np.asarray(np.degrees(beta)),
        strike_degrees=np.asarray(np.degrees(alpha - beta) % 90.0),
        ellipticity=np.asarray(
            np.divide(maximum - minimum, total, out=np.ones_like(total), where=np.abs(total) > 0)
        ),
    )


def apparent_resistivity_ohm_m(impedance_ohm: np.ndarray, frequencies_hz: np.ndarray) -> np.ndarray:
    """Apparent resistivity from an impedance already in ohms."""
    omega = 2.0 * np.pi * np.asarray(frequencies_hz)
    impedance = np.asarray(impedance_ohm)
    shape = (-1,) + (1,) * (impedance.ndim - 1)
    return np.asarray(np.abs(impedance) ** 2 / (omega.reshape(shape) * MU0))


def impedance_phase_degrees(impedance: np.ndarray) -> np.ndarray:
    """The impedance phase, which unit errors cannot reach."""
    return np.asarray(np.degrees(np.angle(np.asarray(impedance))))


def impedance_uncertainty_ohm(station: "Station", tensor: np.ndarray) -> np.ndarray:
    """Public name for the measured impedance uncertainty, as `(frequency, 2, 2)`."""
    return _impedance_uncertainty(station, tensor)
