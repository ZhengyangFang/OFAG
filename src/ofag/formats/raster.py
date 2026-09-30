"""Sampling a raster at points, which for OFAG means a DEM at stations."""

from importlib.util import find_spec
from pathlib import Path
from typing import Literal

import numpy as np

from ofag.core.constants import QuantityType
from ofag.core.crs import reproject
from ofag.core.units import canonicalize_quantity


def dependency_available() -> bool:
    return find_spec("rasterio") is not None


def sample_elevation(
    raster_path: Path | str,
    easting: np.ndarray,
    northing: np.ndarray,
    *,
    crs: str,
    elevation_unit: str,
    method: Literal["bilinear", "nearest"] = "bilinear",
) -> np.ndarray:
    """Elevations at the given points, in canonical metres."""
    if not dependency_available():
        raise ValueError(
            "sampling a raster needs rasterio; install the optional extra with "
            "`uv sync --extra raster`"
        )
    import rasterio  # type: ignore[import-untyped]

    source = Path(raster_path)
    if not source.is_file():
        raise ValueError(f"raster does not exist: {source}")
    east = np.asarray(easting, dtype=float)
    north = np.asarray(northing, dtype=float)
    if east.shape != north.shape:
        raise ValueError("the two coordinate arrays must have the same shape")

    with rasterio.open(source) as dataset:
        raster_crs = str(dataset.crs) if dataset.crs is not None else None
        if raster_crs is None:
            raise ValueError(
                f"{source} declares no coordinate system, so points cannot be placed in it"
            )
        if raster_crs != crs:
            east, north = reproject(east, north, source_crs=crs, target_crs=raster_crs)
        band = dataset.read(1, masked=True).astype(float).filled(np.nan)
        rows, columns = _pixel_coordinates(dataset.transform, east, north)
        outside = (
            (columns < 0) | (columns > dataset.width - 1) | (rows < 0) | (rows > dataset.height - 1)
        )
        if outside.any():
            raise ValueError(
                f"{int(outside.sum())} of {east.size} points fall outside {source.name}; "
                "fetch a raster that covers them rather than leaving them without an elevation"
            )
        values = (
            _bilinear(band, rows, columns)
            if method == "bilinear"
            else _nearest(band, rows, columns)
        )

    if not np.isfinite(values).all():
        raise ValueError(
            f"{int((~np.isfinite(values)).sum())} points land on no-data cells in {source.name}"
        )
    converted = canonicalize_quantity(values, elevation_unit, QuantityType.LENGTH)
    return np.asarray(converted, dtype=float).reshape(east.shape)


def _pixel_coordinates(
    transform: object, east: np.ndarray, north: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Fractional row and column of each point, pixel centres at whole numbers."""
    inverse = ~transform  # type: ignore[operator]
    columns, rows = inverse @ (east, north)
    # An affine transform maps to pixel corners; subtracting a half puts a pixel's
    # centre at its own index, which is what interpolation assumes.
    return np.asarray(rows, dtype=float) - 0.5, np.asarray(columns, dtype=float) - 0.5


def _nearest(band: np.ndarray, rows: np.ndarray, columns: np.ndarray) -> np.ndarray:
    return np.asarray(band[np.rint(rows).astype(int), np.rint(columns).astype(int)], dtype=float)


def _bilinear(band: np.ndarray, rows: np.ndarray, columns: np.ndarray) -> np.ndarray:
    """The four neighbouring cells, weighted by how near the point is to each."""
    height, width = band.shape
    row0 = np.clip(np.floor(rows).astype(int), 0, height - 1)
    column0 = np.clip(np.floor(columns).astype(int), 0, width - 1)
    row1 = np.clip(row0 + 1, 0, height - 1)
    column1 = np.clip(column0 + 1, 0, width - 1)
    down = np.clip(rows - row0, 0.0, 1.0)
    right = np.clip(columns - column0, 0.0, 1.0)
    return np.asarray(
        band[row0, column0] * (1 - down) * (1 - right)
        + band[row0, column1] * (1 - down) * right
        + band[row1, column0] * down * (1 - right)
        + band[row1, column1] * down * right,
        dtype=float,
    )
