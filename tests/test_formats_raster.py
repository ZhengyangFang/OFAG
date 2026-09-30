"""Sampling a raster at points, and the errors that would otherwise be silent."""

from pathlib import Path

import numpy as np
import pytest

from ofag.formats.raster import sample_elevation

rasterio = pytest.importorskip("rasterio")

EAST0, NORTH0, PIXEL = 600_000.0, 5_031_000.0, 100.0


def _raster(path: Path, values: np.ndarray, crs: str = "EPSG:26912") -> Path:
    from rasterio.transform import from_origin

    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float32",
        crs=crs,
        transform=from_origin(EAST0, NORTH0, PIXEL, PIXEL),
    ) as target:
        target.write(values.astype("float32"), 1)
    return path


def test_a_point_gets_the_value_of_the_cell_it_is_in(tmp_path: Path) -> None:
    values = np.arange(25, dtype=float).reshape(5, 5)
    path = _raster(tmp_path / "ramp.tif", values)

    # The centre of the top-left pixel.
    sampled = sample_elevation(
        path,
        np.asarray([EAST0 + PIXEL / 2]),
        np.asarray([NORTH0 - PIXEL / 2]),
        crs="EPSG:26912",
        elevation_unit="m",
        method="nearest",
    )

    assert sampled[0] == pytest.approx(values[0, 0])


def test_bilinear_reads_between_cells_where_nearest_jumps(tmp_path: Path) -> None:
    """A thirty-metre posting sampled nearest can be twenty-one metres from the point asked
    about."""
    east = np.arange(5)[None, :] * np.ones((5, 1))
    path = _raster(tmp_path / "slope.tif", east * 100.0)
    # Halfway between the first two pixel centres.
    query_east = np.asarray([EAST0 + PIXEL])
    query_north = np.asarray([NORTH0 - PIXEL / 2])

    nearest = sample_elevation(
        path, query_east, query_north, crs="EPSG:26912", elevation_unit="m", method="nearest"
    )
    bilinear = sample_elevation(
        path, query_east, query_north, crs="EPSG:26912", elevation_unit="m", method="bilinear"
    )

    assert bilinear[0] == pytest.approx(50.0)
    assert nearest[0] in (0.0, 100.0)


def test_a_point_outside_the_raster_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    """This is how the Stillwater terrain grid was found to be too small: a 4 km margin
    around the survey reached past the DEM that had been fetched."""
    path = _raster(tmp_path / "small.tif", np.ones((5, 5)))

    with pytest.raises(ValueError, match="fall outside"):
        sample_elevation(
            path,
            np.asarray([EAST0 + 10_000.0]),
            np.asarray([NORTH0]),
            crs="EPSG:26912",
            elevation_unit="m",
        )


def test_points_in_another_system_are_projected_before_sampling(tmp_path: Path) -> None:
    """So a caller never has to match its survey to the raster by hand."""
    path = _raster(tmp_path / "flat.tif", np.full((20, 20), 2000.0))

    from ofag.core.crs import reproject

    longitude, latitude = reproject(
        np.asarray([EAST0 + 500.0]),
        np.asarray([NORTH0 - 500.0]),
        source_crs="EPSG:26912",
        target_crs="EPSG:4326",
    )
    sampled = sample_elevation(path, longitude, latitude, crs="EPSG:4326", elevation_unit="m")

    assert sampled[0] == pytest.approx(2000.0)


def test_the_elevation_unit_is_applied(tmp_path: Path) -> None:
    """Older USGS elevation products are in feet, and a GeoTIFF rarely states the unit of its
    band."""
    path = _raster(tmp_path / "feet.tif", np.full((5, 5), 1000.0))

    metres = sample_elevation(
        path,
        np.asarray([EAST0 + 150.0]),
        np.asarray([NORTH0 - 150.0]),
        crs="EPSG:26912",
        elevation_unit="ft",
    )

    assert metres[0] == pytest.approx(304.8)


def test_a_raster_with_no_coordinate_system_is_refused(tmp_path: Path) -> None:
    path = _raster(tmp_path / "nocrs.tif", np.ones((5, 5)), crs=None)

    with pytest.raises(ValueError, match="declares no coordinate system"):
        sample_elevation(
            path, np.asarray([EAST0]), np.asarray([NORTH0]), crs="EPSG:26912", elevation_unit="m"
        )
