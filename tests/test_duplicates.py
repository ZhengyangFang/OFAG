"""A8: two copies of a quantity, differenced and then settled."""

import numpy as np
import pytest

from ofag.agent.duplicates import (
    UnresolvedCopies,
    difference,
    refuse_unresolved,
    second_difference_scatter,
)

FOOT_M = 0.3048

#: ERT1 as `electrodes_xyz.txt` gives it: forty-eight electrodes climbing seven whole-
#: foot contours, which is F048's finding and this one's fixture.
TABLE = np.repeat(np.arange(953, 960) * FOOT_M, 7)[:48]
#: The `.dat`'s own block: the same elevations, pairing scrambled.
BLOCK = np.random.default_rng(0).permutation(TABLE)

CRITERION = (
    "the scatter of its second difference is 0.23 m against the block's 1.35, a factor of "
    "six on the same ground, and a surveyed line varies smoothly"
)


def _copies(agree_within: float = 0.05):
    return difference(
        "surface elevation, ERT1",
        BLOCK,
        TABLE,
        unit="m",
        first_from="the .dat's own topography block",
        second_from="electrodes_xyz.txt",
        agree_within=agree_within,
    )


class TestDifferencingThem:
    def test_the_two_lists_are_1_83_m_apart_at_worst(self) -> None:
        assert _copies().largest == pytest.approx(6 * FOOT_M, abs=1e-3)

    def test_a_scrambled_pairing_is_reported_as_one(self) -> None:
        """The fault is not that the elevations differ -- sorted they are identical -- it is
        that the pairing does."""
        copies = _copies()

        assert copies.same_values_reordered
        assert "the pairing is what differs" in copies.summary
        assert np.allclose(np.sort(BLOCK), np.sort(TABLE))

    def test_two_genuinely_different_lists_are_not_called_scrambled(self) -> None:
        shifted = TABLE + 2.44

        assert not difference(
            "surface elevation",
            shifted,
            TABLE,
            unit="m",
            first_from="the lidar",
            second_from="electrodes_xyz.txt",
            agree_within=0.05,
        ).same_values_reordered

    def test_two_copies_of_different_length_are_refused(self) -> None:
        """Differencing them would measure the alignment and not the quantity."""
        with pytest.raises(ValueError, match="not aligned"):
            difference(
                "surface elevation",
                TABLE[:40],
                TABLE,
                unit="m",
                first_from="the block",
                second_from="the table",
                agree_within=0.05,
            )

    def test_a_scalar_pair_works_the_same_way(self) -> None:
        """F002: a survey README naming one reduction density and the modelling using
        another, both shipped in the same folder and neither wrong."""
        copies = difference(
            "reduction density",
            2.67,
            2.60,
            unit="g/cm3",
            first_from="the modelling",
            second_from="the survey's own README",
            agree_within=0.01,
        )

        assert copies.count == 1
        assert not copies.agree
        assert not copies.same_values_reordered


class TestSettlingTheDisagreement:
    def test_copies_that_agree_need_nothing(self) -> None:
        """Differencing them was the test and it passed."""
        assert refuse_unresolved(_copies(agree_within=2.0)).agree

    def test_a_disagreement_nobody_settled_is_refused(self) -> None:
        with pytest.raises(UnresolvedCopies, match="Name which copy was taken"):
            refuse_unresolved(_copies())

    def test_taking_the_first_one_is_not_a_criterion(self) -> None:
        with pytest.raises(UnresolvedCopies, match="made invisible rather than made"):
            refuse_unresolved(
                _copies(),
                took="electrodes_xyz.txt",
                because="it was first in the folder and looked reasonable enough",
            )

    def test_a_criterion_about_the_copies_settles_it(self) -> None:
        assert refuse_unresolved(_copies(), took="electrodes_xyz.txt", because=CRITERION)

    def test_taking_something_that_is_not_one_of_the_two_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="which is neither"):
            refuse_unresolved(_copies(), took="the lidar", because=CRITERION)

    def test_a_criterion_too_short_to_say_anything_is_refused(self) -> None:
        with pytest.raises(UnresolvedCopies, match="Say what separates the two"):
            refuse_unresolved(_copies(), took="electrodes_xyz.txt", because="smoother")


class TestTheCriterionThatSettledIt:
    def test_the_scatter_separates_a_survey_from_a_scramble(self) -> None:
        """0.23 against 1.35 on the real lists, a factor of six."""
        assert second_difference_scatter(TABLE) < second_difference_scatter(BLOCK) / 5

    def test_a_series_too_short_to_curve_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="at least three values"):
            second_difference_scatter([1.0, 2.0])


class TestWhenAThirdSourceSettlesThem:
    """F049, and the reason `took` is not restricted to the two."""

    THIRD = (
        "1 m lidar and the 1/3 arc-second DEM agree with each other to 6 cm and sit 2.4 m "
        "above both lists, which is the eight feet the two lists differ by"
    )

    def test_neither_is_an_outcome_and_not_a_refusal_to_choose(self) -> None:
        from ofag.agent.duplicates import NEITHER

        assert refuse_unresolved(_copies(), took=NEITHER, because=self.THIRD)

    def test_it_still_has_to_name_what_settled_them(self) -> None:
        from ofag.agent.duplicates import NEITHER

        with pytest.raises(UnresolvedCopies, match="Say what separates the two"):
            refuse_unresolved(_copies(), took=NEITHER, because="a DEM")

    def test_a_third_name_that_is_not_the_sentinel_is_an_error(self) -> None:
        """Because then `took` would be free text and the two copies would stop being the
        thing the gate is about."""
        with pytest.raises(ValueError, match="Pass NEITHER"):
            refuse_unresolved(_copies(), took="dem/llano_3dep_1m.tif", because=self.THIRD)
