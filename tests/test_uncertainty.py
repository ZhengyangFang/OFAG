"""A4: an error bar carried as two things, because it is two things."""

import math

import pytest
from pydantic import ValidationError

from ofag.agent.uncertainty import (
    Budget,
    RepeatabilityAlone,
    refuse_repeatability_alone,
    what_the_misfit_implies,
)

#: F018, as the first inversion had it: the bar is the repeats and nothing else.
BARE = Budget(
    quantity="transient voltage, per gate",
    unit="per cent",
    repeatability=0.17,
    repeatability_from="the scatter of the fifty sweeps stacked into each gate",
    model_error=0.0,
    model_error_from="nothing was stated; the bar was the repeatability alone",
)

#: F003, once the budget was taken from the terms rather than from the meter.
GRAVITY = Budget(
    quantity="Bouguer anomaly",
    unit="mGal",
    repeatability=0.001,
    repeatability_from="the meter's own repeatability after processing, as delivered",
    model_error=0.015,
    model_error_from="0.3086 mGal per metre of free-air gradient on stations levelled to 0.05 m",
)


class TestRefusingOneNumberWhereThereAreTwo:
    def test_a_budget_that_is_only_the_instrument_is_refused(self) -> None:
        with pytest.raises(RepeatabilityAlone, match="143,838"):
            refuse_repeatability_alone(BARE)

    def test_a_budget_with_both_ends_passes_and_comes_back(self) -> None:
        assert refuse_repeatability_alone(GRAVITY) is GRAVITY

    def test_the_two_combine_in_quadrature(self) -> None:
        assert GRAVITY.sigma == pytest.approx(math.hypot(0.001, 0.015))

    def test_which_end_dominates_is_reported_rather_than_assumed(self) -> None:
        """The gravity budget is fifteen times more model than meter, and the transient one
        before its repair was all meter."""
        assert GRAVITY.dominated_by == "the model"
        assert BARE.dominated_by == "the instrument"

    def test_a_repeatability_with_no_measurement_behind_it_will_not_construct(self) -> None:
        with pytest.raises(ValidationError):
            Budget(
                quantity="transient voltage",
                unit="per cent",
                repeatability=0.17,
                repeatability_from="measured",
                model_error=2.0,
                model_error_from="what a layered earth achieves on ground like this one",
            )


class TestSayingWhichEnd:
    def test_an_enormous_misfit_points_at_the_denominator(self) -> None:
        """143,838 against 0.17 per cent implies a model error of 64 per cent, which is not a
        model error -- it is the statement that the bar was never the right quantity."""
        implied = what_the_misfit_implies(143_838.0, BARE)

        assert implied.model_error == pytest.approx(0.17 * math.sqrt(143_837.0))
        assert "about the denominator" in implied.verdict

    def test_a_credible_misfit_on_a_real_budget_points_at_the_model(self) -> None:
        """The check has to be able to say this, or it is a check that always blames the bar."""
        implied = what_the_misfit_implies(2.4, GRAVITY)

        assert implied.times_the_stated < 0.1
        assert "about the numerator" in implied.verdict

    def test_a_misfit_under_one_is_a_question_from_the_other_side(self) -> None:
        """An error bar that cannot be contradicted is not evidence that the model is right."""
        assert "cannot be contradicted" in what_the_misfit_implies(0.3, GRAVITY).verdict

    def test_a_stated_model_error_of_zero_gives_an_infinite_ratio(self) -> None:
        assert what_the_misfit_implies(10.0, BARE).times_the_stated == math.inf

    def test_a_chi_squared_that_is_not_positive_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="a chi-squared is positive"):
            what_the_misfit_implies(0.0, GRAVITY)


class TestTheLoopItRefusesToClose:
    def test_a_tolerance_read_off_the_misfit_will_not_construct(self) -> None:
        """A5, guarded here because this is the object that would carry it."""
        with pytest.raises(ValidationError, match="closes the loop"):
            Budget(
                quantity="Bouguer anomaly",
                unit="mGal",
                repeatability=0.001,
                repeatability_from="the meter's own repeatability after processing",
                model_error=0.5,
                model_error_from="a floor measured from the rms of the fit across all stations",
            )

    @pytest.mark.parametrize("phrase", ["misfit", "chi squared", "residual"])
    def test_each_way_of_saying_it_is_caught(self, phrase: str) -> None:
        with pytest.raises(ValidationError, match="closes the loop"):
            Budget(
                quantity="Bouguer anomaly",
                unit="mGal",
                repeatability=0.001,
                repeatability_from="the meter's own repeatability after processing",
                model_error=0.5,
                model_error_from=f"scaled until the {phrase} came out near one, as is customary",
            )

    def test_a_legitimate_provenance_is_not_caught(self) -> None:
        """Taken from a second method over the same ground, which is what A4 asks for and
        what the guard must not refuse."""
        assert Budget(
            quantity="Bouguer anomaly",
            unit="mGal",
            repeatability=0.001,
            repeatability_from="the meter's own repeatability after processing",
            model_error=0.02,
            model_error_from="what the published inversion of this survey achieved on the "
            "same stations, which is an independent statement about the ground",
        ).model_error == pytest.approx(0.02)
