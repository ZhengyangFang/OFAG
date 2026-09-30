"""The reference field, and the two ways it goes wrong quietly."""

from datetime import datetime

import numpy as np
import pytest

from ofag.core.geomagnetism import (
    igrf_inducing_field,
    igrf_total_field_nt,
    looks_like_a_total_field,
    to_anomaly_nt,
)

#: The centre of the Stillwater airborne survey, in the project's own system, and the
#: day it was flown.
EAST, NORTH, ELEVATION = 578_000.0, 5_031_000.0, 2_300.0
CRS = "EPSG:26912"
FLOWN = datetime(2000, 5, 10)


def test_the_reference_field_matches_what_the_survey_measured() -> None:
    """An external check: the survey's own median total field is 55,762 nT, and a reference
    field that disagreed by thousands would mean the epoch, the place or the projection
    was wrong."""
    field = igrf_total_field_nt(
        np.asarray([EAST]), np.asarray([NORTH]), np.asarray([ELEVATION]), crs=CRS, epoch=FLOWN
    )

    assert abs(field[0] - 55_762.0) < 1_000.0


def test_the_inducing_field_points_where_montana_says_it_does() -> None:
    """Steeply down and a little east, which is what 45 degrees north gives."""
    field = igrf_inducing_field(EAST, NORTH, ELEVATION, crs=CRS, epoch=FLOWN)

    assert 65.0 < field.inclination_degrees < 75.0
    assert 10.0 < field.declination_degrees < 18.0
    assert 54_000 < field.amplitude_nt < 58_000


def test_a_total_field_is_told_apart_from_an_anomaly_by_size() -> None:
    """The one mistake OFAG's unit policy cannot catch, because nanotesla is the right unit
    for both and the dimensions agree."""
    assert looks_like_a_total_field(np.asarray([55_762.0, 55_800.0, 55_700.0])) is True
    assert looks_like_a_total_field(np.asarray([12.0, -300.0, 45.0])) is False
    assert looks_like_a_total_field(np.asarray([])) is False


def test_reducing_a_total_field_leaves_a_crustal_anomaly() -> None:
    """Not a number still carrying the core field."""
    measured = np.asarray([55_762.0, 56_500.0])
    anomaly = to_anomaly_nt(
        measured,
        np.asarray([EAST, EAST]),
        np.asarray([NORTH, NORTH]),
        np.asarray([ELEVATION, ELEVATION]),
        crs=CRS,
        epoch=FLOWN,
    )

    assert np.all(np.abs(anomaly) < 2_000.0)
    # The difference between two readings survives the reduction untouched.
    assert anomaly[1] - anomaly[0] == pytest.approx(738.0, abs=1e-6)


def test_the_epoch_changes_the_reference_field() -> None:
    """Which is why a survey is reduced against the year it was flown."""
    flown = igrf_total_field_nt(
        np.asarray([EAST]), np.asarray([NORTH]), np.asarray([ELEVATION]), crs=CRS, epoch=FLOWN
    )
    today = igrf_total_field_nt(
        np.asarray([EAST]),
        np.asarray([NORTH]),
        np.asarray([ELEVATION]),
        crs=CRS,
        epoch=datetime(2026, 5, 10),
    )

    assert abs(flown[0] - today[0]) > 50.0
