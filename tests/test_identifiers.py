"""A13: an identifier nobody followed."""

from datetime import date

import pytest
from pydantic import ValidationError

from ofag.agent.identifiers import (
    Resolution,
    Source,
    UnresolvedIdentifier,
    refuse_unresolved,
)


def test_an_identifier_nobody_followed_is_refused() -> None:
    """F030, as the row stood. Nothing about it is malformed."""
    terrain = Source(what="Terrain, 3DEP 1/3 arc-second", identifier="10.5066/F7PR7TFT")

    with pytest.raises(UnresolvedIdentifier, match="never followed"):
        refuse_unresolved([terrain])


def test_the_three_that_resolved_to_the_wrong_submission() -> None:
    """And the reason this is a gate rather than a habit."""
    recorded = [
        Source(
            what="Utah FORGE 3D gravity data",
            identifier="10.15121/1559241",
            resolution=Resolution.DEAD,
            checked_on=date(2026, 9, 23),
        ),
        Source(
            what="Utah FORGE TEM and gravity data",
            identifier="10.15121/1452445",
            resolution=Resolution.MISMATCHED,
            resolved_to="a different GDR submission; the release is 10.15121/1452733",
            checked_on=date(2026, 9, 23),
        ),
        Source(
            what="Utah FORGE Phase 3 magnetotelluric data",
            identifier="10.15121/1846183",
            resolution=Resolution.DEAD,
            checked_on=date(2026, 9, 23),
        ),
    ]

    with pytest.raises(UnresolvedIdentifier) as raised:
        refuse_unresolved(recorded)

    message = str(raised.value)
    assert "3 of 3" in message
    assert "1452733" in message, "the refusal has to say what the right one is when it is known"


def test_the_same_three_pass_once_they_point_at_the_thing_in_hand() -> None:
    corrected = [
        Source(
            what="Utah FORGE 3D gravity data",
            identifier="10.15121/1542061",
            resolution=Resolution.CONFIRMED,
            resolved_to="Utah FORGE: 3D Gravity Data, Hardwick and Witter, GDR, 2019-06-24",
            checked_on=date(2026, 9, 23),
        ),
        Source(
            what="Utah FORGE TEM and gravity data",
            identifier="10.15121/1452733",
            resolution=Resolution.CONFIRMED,
            resolved_to="Utah FORGE: TEM and Gravity Data, Hardwick and Nash, GDR, 2018-02-05",
            checked_on=date(2026, 9, 23),
        ),
        Source(
            what="Utah FORGE Phase 3 magnetotelluric data",
            identifier="10.15121/1776598",
            resolution=Resolution.CONFIRMED,
            resolved_to="Utah FORGE: Phase 3 MT Data, Wannamaker and Maris, GDR, 2020-10-01",
            checked_on=date(2026, 9, 23),
        ),
    ]

    assert refuse_unresolved(corrected) == tuple(corrected)


def test_confirmed_has_to_say_what_came_back() -> None:
    """Because "we checked" is the claim, not the evidence."""
    with pytest.raises(ValidationError, match="does not say what"):
        Source(
            what="Utah FORGE 3D gravity data",
            identifier="10.15121/1559241",
            resolution=Resolution.CONFIRMED,
            checked_on=date(2026, 9, 23),
        )


def test_confirmed_has_to_say_when() -> None:
    with pytest.raises(ValidationError, match="decays"):
        Source(
            what="Terrain",
            identifier="10.5066/F7PR7TFT",
            resolution=Resolution.CONFIRMED,
            resolved_to="SRTM 1 Arc-Second Global",
        )


class TestSourcesWithNoIdentifier:
    """The rule was never a bar on data nobody published."""

    def test_no_identifier_is_allowed_when_it_says_where_the_thing_is(self) -> None:
        """3DEP has twelve downloadable collections and exactly one, Seamless 1 m, carries a
        registered DOI."""
        tile = Source(
            what="Terrain, 3DEP 1 m bare-earth lidar, tile 14 x55y340",
            held_at="USGS 3DEP, ScienceBase item 619c3717d34eb622f6931b2b, "
            "project TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA, collected Jan-Feb 2019",
        )

        assert refuse_unresolved([tile]) == (tile,)

    def test_no_identifier_and_no_whereabouts_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="where, when and who"):
            Source(what="a survey somebody ran", held_at="on the server")

    def test_nothing_to_follow_cannot_have_been_followed(self) -> None:
        with pytest.raises(ValidationError, match="nothing to follow"):
            Source(
                what="our own survey",
                held_at="collected by this group in March 2026, held on the group NAS",
                resolution=Resolution.CONFIRMED,
                resolved_to="itself",
                checked_on=date(2026, 9, 23),
            )


def test_a_clean_table_passes_and_comes_back_in_order() -> None:
    table = [
        Source(
            what="Llano geoelectric and seismic data",
            identifier="10.5066/F72Z14G6",
            resolution=Resolution.CONFIRMED,
            resolved_to="Ikard and others, 2019, USGS data release",
            checked_on=date(2026, 9, 23),
        ),
        Source(
            what="Terrain, 3DEP 1 m lidar",
            held_at="USGS 3DEP, ScienceBase 619c3717d34eb622f6931b2b, collected Jan-Feb 2019",
        ),
    ]

    assert [s.what for s in refuse_unresolved(table)] == [s.what for s in table]
