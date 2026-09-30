"""What a run that missed its target owes before its result is used."""

import pytest
from pydantic import ValidationError

from ofag.agent.diagnosis import Diagnosis, RuledOut
from ofag.agent.gates import UnfittedRun, UnmeasuredReach, refuse_unfitted, refuse_unstated_reach

TOPOGRAPHY = RuledOut(
    hypothesis="the terrain, which the release states twice and inconsistently",
    measurement="inverted the profile flat, and on each of the two elevation lists",
    result="3.074 flat, 3.090 on the table, 3.165 on the block: flat is marginally the best",
)


def _diagnosis(**overrides) -> Diagnosis:
    return Diagnosis(
        **{
            "misfit": 3.090,
            "target": 2.0,
            "where": (
                "17 of 243 readings over 15 per cent at two stretches, while the median "
                "reading fits to 4.1 per cent"
            ),
            "ruled_out": (TOPOGRAPHY,),
            "remaining": "the two-dimensional assumption, which this survey cannot test",
        }
        | overrides
    )


def test_a_miss_with_nothing_ruled_out_is_a_number_not_a_diagnosis() -> None:
    with pytest.raises(ValidationError, match="not a diagnosis"):
        _diagnosis(ruled_out=())


def test_a_run_that_fit_owes_no_explanation() -> None:
    """Demanding a record from a run that fit would make the record a formality, and a
    formality is what stops being read."""
    fitted = _diagnosis(misfit=0.762, ruled_out=())

    assert fitted.fitted
    assert fitted.ruled_out == ()


def test_an_excluded_explanation_has_to_name_its_measurement() -> None:
    """A hypothesis without a measurement is a hypothesis that was not tested, which is F039."""
    with pytest.raises(ValidationError):
        RuledOut(
            hypothesis="the terrain, which the release states twice over",
            measurement="checked",
            result="it was fine, as far as anybody could tell at the time",
        )


def test_the_summary_says_what_was_excluded_and_what_is_left() -> None:
    summary = _diagnosis().summary

    assert "chi squared 3.090 against 2" in summary
    assert "Ruled out: the terrain" in summary
    assert "What is left: the two-dimensional assumption" in summary


def test_a_model_may_not_be_built_on_an_undiagnosed_miss() -> None:
    misfits = {"ERT1": 3.090, "ERT2": 0.762}
    bars = {"ERT1": 2.0, "ERT2": 2.0}

    with pytest.raises(UnfittedRun, match="ERT1 at chi squared 3.090"):
        refuse_unfitted(misfits, bars)

    assert refuse_unfitted(misfits, bars, {"ERT1": _diagnosis()}) == ("ERT1",)


def test_an_acknowledged_miss_is_still_returned_to_be_printed() -> None:
    """A diagnosis that silences a run is the same as having no gate."""
    used = refuse_unfitted({"ERT1": 3.090}, {"ERT1": 2.0}, {"ERT1": _diagnosis()})

    assert used == ("ERT1",)


def test_a_section_read_into_a_model_says_how_deep_it_resolved() -> None:
    """C1. A section read to the bottom of its mesh is read past its data, and case 3's first
    model claimed the aquifer to 40 m on resistivity that resolves 17."""
    with pytest.raises(UnmeasuredReach, match="TDEM"):
        refuse_unstated_reach(
            {"ERT": (16.7, "measured from the coverage array"), "TDEM": (60.0, "")}
        )


def test_a_declared_reach_is_allowed_and_named() -> None:
    """Sometimes declared is all there is."""
    declared = refuse_unstated_reach(
        {
            "ERT1 and ERT2": (16.7, "measured from each run's own coverage array"),
            "TDEM": (60.0, "declared: nothing here computes a depth of investigation"),
        }
    )

    assert declared == ("TDEM",)


def test_a_model_whose_reaches_are_all_measured_returns_nothing_to_flag() -> None:
    assert refuse_unstated_reach({"ERT": (16.7, "measured from coverage")}) == ()


class TestTheRecordedFailureItWouldHaveRefused:
    """F011, reproduced and put in front of the gate."""

    def test_a_reach_with_no_provenance_is_refused(self) -> None:
        with pytest.raises(UnmeasuredReach, match="the resistivity lines"):
            refuse_unstated_reach({"the resistivity lines": (40.0, "")})

    def test_the_mesh_depth_is_sayable_and_has_to_be_owned(self) -> None:
        """The gate does not know 40 m is the mesh."""
        declared = refuse_unstated_reach(
            {"the resistivity lines": (40.0, "declared: the depth the parameter mesh was built to")}
        )

        assert declared == ("the resistivity lines",)

    def test_the_measured_reach_passes_and_is_not_flagged(self) -> None:
        assert (
            refuse_unstated_reach(
                {"the resistivity lines": (13.9, "measured from each run's own coverage array")}
            )
            == ()
        )
