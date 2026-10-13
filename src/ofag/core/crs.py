"""Coordinate convention, metric-CRS validation, and projection between them."""

import numpy as np
from pyproj import CRS, Transformer

LOCAL_CARTESIAN_METRIC = "LOCAL_CARTESIAN_METRIC"


class CRSValidationError(ValueError):
    """A run attempted to construct a numerical mesh in a non-metric CRS."""


def validate_metric_crs(crs_value: str) -> None:
    if crs_value == LOCAL_CARTESIAN_METRIC:
        return
    try:
        crs = CRS.from_user_input(crs_value)
    except Exception as error:  # pyproj has multiple parser exception classes
        raise CRSValidationError(f"invalid CRS {crs_value!r}") from error
    if crs.is_geographic:
        raise CRSValidationError(
            "geographic coordinates cannot create a numerical mesh; project them to a metric CRS"
        )
    horizontal_axes = [axis for axis in crs.axis_info if axis.direction in {"east", "north"}]
    if not horizontal_axes or any(axis.unit_conversion_factor != 1.0 for axis in horizontal_axes):
        raise CRSValidationError("the horizontal CRS axes must use metres")


def reproject(
    easting: np.ndarray, northing: np.ndarray, *, source_crs: str, target_crs: str
) -> tuple[np.ndarray, np.ndarray]:
    """Coordinates moved from one CRS to another, in the target's own metres."""
    for role, value in (("source_crs", source_crs), ("target_crs", target_crs)):
        if value == LOCAL_CARTESIAN_METRIC:
            raise CRSValidationError(
                f"{role} is {LOCAL_CARTESIAN_METRIC}, a local grid with no position on the "
                "Earth; it cannot be projected to or from"
            )
    east = np.asarray(easting, dtype=float)
    north = np.asarray(northing, dtype=float)
    if east.shape != north.shape:
        raise CRSValidationError("the two coordinate arrays must have the same shape")
    if source_crs == target_crs:
        return east, north
    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
    except Exception as error:  # pyproj has multiple parser exception classes
        raise CRSValidationError(f"cannot project {source_crs!r} to {target_crs!r}") from error
    projected_east, projected_north = transformer.transform(east, north)
    projected_east = np.asarray(projected_east, dtype=float)
    projected_north = np.asarray(projected_north, dtype=float)
    if not (np.isfinite(projected_east).all() and np.isfinite(projected_north).all()):
        raise CRSValidationError(
            f"coordinates fall outside the domain of {source_crs!r}; the most common cause is "
            "the two columns being the other way round, since this takes the east-like "
            "coordinate first"
        )
    return projected_east, projected_north


def is_geographic(crs_value: str) -> bool:
    """Whether a CRS measures in degrees, which decides if a unit applies."""
    if crs_value == LOCAL_CARTESIAN_METRIC:
        return False
    try:
        return bool(CRS.from_user_input(crs_value).is_geographic)
    except Exception as error:  # pyproj has multiple parser exception classes
        raise CRSValidationError(f"invalid CRS {crs_value!r}") from error
