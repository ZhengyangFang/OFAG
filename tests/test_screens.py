"""A6: an index used as a filter, against what it claims to filter for."""

import pytest
from pydantic import ValidationError

from ofag.agent.screens import Screen, UnpredictiveScreen, refuse_unpredictive

#: F016, as measured: the magnetotelluric admissibility index against the misfit it was
#: about to be tuned on.
ADMISSIBILITY = Screen(
    what="admissibility index |Zxy+Zyx| / |Zxy-Zyx|",
    filters_for="whether a site fits a layered inversion, as chi-squared",
    association=-0.06,
    n=102,
    measured_on="the 102 admitted sites of the Utah FORGE Phase 3 survey",
)


def test_the_index_that_screened_topsoil_is_refused() -> None:
    """Reject a screen with no detectable association."""
    assert ADMISSIBILITY.standard_error == pytest.approx(0.1005, abs=1e-4)
    assert not ADMISSIBILITY.distinguishable_from_zero

    with pytest.raises(UnpredictiveScreen, match=r"r = -0\.060"):
        refuse_unpredictive([ADMISSIBILITY])


def test_the_refusal_names_the_sample_that_decided_it() -> None:
    """Because the refusal is the sample's and not a constant's, and a reader who disagrees
    should be arguing with n rather than with a threshold."""
    with pytest.raises(UnpredictiveScreen) as raised:
        refuse_unpredictive([ADMISSIBILITY])

    message = str(raised.value)
    assert "n = 102" in message
    assert "one standard error is 0.101" in message


def test_the_same_association_passes_once_the_sample_is_large_enough() -> None:
    """The bar is the sample's, so it moves with the sample."""
    on_many = ADMISSIBILITY.model_copy(update={"n": 5_000, "measured_on": "a much larger survey"})

    assert on_many.distinguishable_from_zero
    assert refuse_unpredictive([on_many]) == (on_many,)


#: F022's replacement, measured.
SKEW = Screen(
    what="phase-tensor skew",
    filters_for="whether a site fits a layered inversion, as chi-squared",
    association=0.054,
    n=82,
    measured_on="the 82 Utah FORGE sites the skew screen admitted, against their "
    "inverted chi-squared; the old departure index on the same 82 gives +0.133",
    contaminated_by="galvanic distortion, which is what moved the index it replaced",
    invariant_because="the phase tensor is invariant to a real distortion matrix by "
    "construction: distortion cancels in Re(Z)^-1 Im(Z)",
)


def test_the_replacement_screen_does_not_predict_either() -> None:
    """Measured here, and it was not measured before."""
    assert not SKEW.distinguishable_from_zero

    with pytest.raises(UnpredictiveScreen, match=r"r = \+0\.054"):
        refuse_unpredictive([SKEW])


def test_a_screen_that_predicts_is_accepted() -> None:
    """Constructed, and labelled: no measured screen in this project passes."""
    strong = Screen(
        what="a constructed screen, for the accepting branch",
        filters_for="an outcome it was measured against",
        association=0.62,
        n=82,
        measured_on="a sample this project does not have",
    )

    assert refuse_unpredictive([strong]) == (strong,)


class TestTheNuisance:
    def test_naming_a_nuisance_and_not_answering_it_is_refused(self) -> None:
        """F022: the index was multiplied by galvanic distortion, so it was reporting the few
        metres under the electrodes."""
        with pytest.raises(ValidationError, match="screened topsoil"):
            Screen(
                what="admissibility index",
                filters_for="departure from a layered earth",
                association=0.4,
                n=102,
                measured_on="the survey",
                contaminated_by="galvanic distortion",
            )

    def test_naming_no_nuisance_is_allowed_and_is_not_a_claim(self) -> None:
        """Allowed because a gate that demanded one would collect the word 'none', and that
        is not the same as there being none."""
        assert refuse_unpredictive(
            [
                Screen(
                    what="a constructed screen naming no nuisance",
                    filters_for="whether a reading is sound",
                    association=0.55,
                    n=1_506,
                    measured_on="a constructed sample",
                )
            ]
        )


class TestWhatItSaysAboutThisProject:
    def test_the_projects_own_keyword_rubric_is_refused_for_its_sample(self) -> None:
        """F057, and the right answer."""
        rubric = Screen(
            what="the silent-replay keyword rubric",
            filters_for="whether an agent noticed the defect",
            association=1.0,
            n=6,
            measured_on="the six silent replays",
        )

        assert rubric.standard_error == pytest.approx(0.577, abs=1e-3)
        with pytest.raises(UnpredictiveScreen):
            refuse_unpredictive([rubric])

    def test_a_sample_too_small_to_have_a_standard_error_will_not_construct(self) -> None:
        with pytest.raises(ValidationError):
            Screen(
                what="an index tried three times",
                filters_for="anything",
                association=0.9,
                n=3,
                measured_on="three runs",
            )


def test_a_mixed_table_refuses_only_what_is_absent_and_names_it() -> None:
    good = Screen(
        what="a constructed screen that passes",
        filters_for="whether a reading is sound",
        association=0.55,
        n=1_506,
        measured_on="a constructed sample",
    )

    with pytest.raises(UnpredictiveScreen) as raised:
        refuse_unpredictive([good, ADMISSIBILITY])

    assert "1 of 2" in str(raised.value)
    assert "a constructed screen that passes" not in str(raised.value)
