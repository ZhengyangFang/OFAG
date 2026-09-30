"""Moving coordinates between systems, and refusing the ways it goes wrong."""

import numpy as np
import pytest

from ofag.core.crs import (
    LOCAL_CARTESIAN_METRIC,
    CRSValidationError,
    is_geographic,
    reproject,
)

# A collar from the Stillwater drill core release, and where UTM zone 12N puts it.
LONGITUDE, LATITUDE = -110.028343, 45.387322


def test_longitude_comes_first_whatever_the_crs_declares() -> None:
    """EPSG:4326 declares latitude first."""
    east, north = reproject(
        np.asarray([LONGITUDE]),
        np.asarray([LATITUDE]),
        source_crs="EPSG:4326",
        target_crs="EPSG:26912",
    )

    # Zone 12N is centred on 111 W, so a point at 110 W sits east of its false easting,
    # and 45.4 N is about five million metres up.
    assert 500_000 < east[0] < 600_000
    assert 5_020_000 < north[0] < 5_060_000


def test_the_columns_the_other_way_round_are_refused_rather_than_projected() -> None:
    """A latitude read as a longitude is outside almost every projected CRS's domain, and
    pyproj answers infinity rather than raising."""
    with pytest.raises(CRSValidationError, match="other way round"):
        reproject(
            np.asarray([LATITUDE]),
            np.asarray([LONGITUDE]),
            source_crs="EPSG:4326",
            target_crs="EPSG:26912",
        )


def test_the_collar_lands_where_the_survey_that_flew_over_it_is() -> None:
    """An external check rather than a check of pyproj's arithmetic."""
    east, north = reproject(
        np.asarray([LONGITUDE]),
        np.asarray([LATITUDE]),
        source_crs="EPSG:4326",
        target_crs="EPSG:26912",
    )

    assert 555_850 <= east[0] <= 600_939
    assert 5_019_262 <= north[0] <= 5_042_484


def test_a_metric_survey_can_be_asked_where_it_is_in_degrees() -> None:
    """An earlier version refused this, confusing an invariant about meshes with one about
    conversions."""
    longitude, latitude = reproject(
        np.asarray([578_000.0]),
        np.asarray([5_031_000.0]),
        source_crs="EPSG:26912",
        target_crs="EPSG:4326",
    )

    assert -111.0 < longitude[0] < -109.0
    assert 45.0 < latitude[0] < 46.0


def test_a_local_grid_cannot_be_projected_to_or_from() -> None:
    """It is metres, but metres from an origin nobody stated."""
    for source, target in (
        (LOCAL_CARTESIAN_METRIC, "EPSG:26912"),
        ("EPSG:4326", LOCAL_CARTESIAN_METRIC),
    ):
        with pytest.raises(CRSValidationError, match="no position on the"):
            reproject(np.asarray([0.0]), np.asarray([0.0]), source_crs=source, target_crs=target)


def test_the_same_crs_is_returned_unchanged() -> None:
    east, north = reproject(
        np.asarray([600_000.0, 601_000.0]),
        np.asarray([5_030_000.0, 5_031_000.0]),
        source_crs="EPSG:26912",
        target_crs="EPSG:26912",
    )

    assert east.tolist() == [600_000.0, 601_000.0]
    assert north.tolist() == [5_030_000.0, 5_031_000.0]


def test_mismatched_array_shapes_are_refused() -> None:
    with pytest.raises(CRSValidationError, match="same shape"):
        reproject(
            np.asarray([1.0, 2.0]),
            np.asarray([1.0]),
            source_crs="EPSG:4326",
            target_crs="EPSG:26912",
        )


def test_whether_a_crs_is_in_degrees_is_answerable() -> None:
    """Which is what decides if a coordinate unit applies at all."""
    assert is_geographic("EPSG:4326") is True
    assert is_geographic("EPSG:26912") is False
    assert is_geographic(LOCAL_CARTESIAN_METRIC) is False
