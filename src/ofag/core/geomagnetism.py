"""The reference field that makes a magnetic anomaly an anomaly."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.crs import reproject
from ofag.core.units import canonicalize_quantity

#: Above this fraction of a plausible core field, a "magnetic anomaly" is almost
#: certainly a total field that nobody reduced.
TOTAL_FIELD_MEAN_THRESHOLD_NT = 15_000.0


def igrf_total_field_nt(
    easting: np.ndarray,
    northing: np.ndarray,
    elevation_m: np.ndarray,
    *,
    crs: str,
    epoch: datetime,
) -> np.ndarray:
    """The reference core field at each point, in nanotesla."""
    longitude, latitude = reproject(easting, northing, source_crs=crs, target_crs="EPSG:4326")
    # ppigrf wants height above the ellipsoid in kilometres and returns the three
    # components in nanotesla, each shaped (times, points).
    from ppigrf import igrf  # type: ignore[import-untyped]

    east, north, up = igrf(
        longitude, latitude, np.asarray(elevation_m, dtype=float) / 1000.0, epoch
    )
    return np.asarray(
        np.sqrt(
            np.asarray(east).reshape(-1) ** 2
            + np.asarray(north).reshape(-1) ** 2
            + np.asarray(up).reshape(-1) ** 2
        ),
        dtype=float,
    ).reshape(np.asarray(easting).shape)


@dataclass(frozen=True)
class InducingField:
    """The field a magnetic inversion says its rocks are magnetised in."""

    amplitude_nt: float
    #: Positive downwards, which is the field convention and SimPEG's.
    inclination_degrees: float
    #: Clockwise from Northing, positive east.
    declination_degrees: float


def igrf_inducing_field(
    easting: float, northing: float, elevation_m: float, *, crs: str, epoch: datetime
) -> InducingField:
    """Amplitude, inclination and declination of the core field at a point."""
    longitude, latitude = reproject(
        np.asarray([easting]), np.asarray([northing]), source_crs=crs, target_crs="EPSG:4326"
    )
    from ppigrf import igrf

    east, north, up = (
        float(np.asarray(component).ravel()[0])
        for component in igrf(longitude, latitude, np.asarray([elevation_m / 1000.0]), epoch)
    )
    horizontal = float(np.hypot(east, north))
    return InducingField(
        amplitude_nt=float(np.hypot(horizontal, up)),
        inclination_degrees=float(np.degrees(np.arctan2(-up, horizontal))),
        declination_degrees=float(np.degrees(np.arctan2(east, north))),
    )


def looks_like_a_total_field(values_nt: np.ndarray) -> bool:
    """Whether a column called an anomaly is really an unreduced total field."""
    finite = np.asarray(values_nt, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return False
    return bool(np.abs(np.mean(finite)) > TOTAL_FIELD_MEAN_THRESHOLD_NT)


def to_anomaly_nt(
    total_field: np.ndarray,
    easting: np.ndarray,
    northing: np.ndarray,
    elevation_m: np.ndarray,
    *,
    crs: str,
    epoch: datetime,
    total_field_unit: str = "nT",
) -> np.ndarray:
    """A measured total field reduced to an anomaly, in nanotesla."""
    measured = np.asarray(
        canonicalize_quantity(
            np.asarray(total_field, dtype=float),
            total_field_unit,
            QuantityType.MAGNETIC_FLUX_DENSITY,
        ),
        dtype=float,
    )
    # Canonical SI for a flux density is tesla; the reference field and every magnetic
    # importer in OFAG work in nanotesla, so come back to it here rather than leaving
    # each caller to remember the factor.
    measured_nt = measured * 1e9
    reference = igrf_total_field_nt(easting, northing, elevation_m, crs=crs, epoch=epoch)
    return np.asarray(measured_nt - reference, dtype=float)
