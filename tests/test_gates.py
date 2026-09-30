"""The check between a number and a claim about the ground."""

import pytest

from ofag.agent.diagnosis import Diagnosis, RuledOut
from ofag.agent.gates import UnfittedRun, refuse_unfitted, unfitted

#: Case 3's, shortened. The full one is in `scripts/case3_llano.py`.
DIAGNOSIS = Diagnosis(
    misfit=3.090,
    target=2.0,
    where="17 of 243 readings over 15 per cent at two stretches, median reading 4.1 per cent",
    ruled_out=(
        RuledOut(
            hypothesis="the terrain, which the release states twice and inconsistently",
            measurement="inverted the profile flat and on each of the two elevation lists",
            result="3.074 flat against 3.090: flat is marginally the better of the two",
        ),
    ),
    remaining="the two-dimensional assumption, which this survey cannot test",
)

#: What case 3 actually holds: one profile over its bar, one under, a refraction line
#: well under, and a sounding far over that is not read into the model at all.
MISFITS = {"ERT1": 3.090, "ERT2": 0.762, "SRT2": 0.532}
BARS = {"ERT1": 2.0, "ERT2": 2.0, "SRT2": 2.0}


def test_a_run_over_its_bar_stops_a_model_being_built_on_it() -> None:
    with pytest.raises(UnfittedRun, match="ERT1 at chi squared 3.090"):
        refuse_unfitted(MISFITS, BARS)


def test_a_diagnosis_lets_it_through_and_a_sentence_does_not() -> None:
    """The gate took a sentence once."""
    assert refuse_unfitted(MISFITS, BARS, {"ERT1": DIAGNOSIS}) == ("ERT1",)

    with pytest.raises(TypeError, match="not a sentence"):
        refuse_unfitted(MISFITS, BARS, {"ERT1": "the misfit is only at two stretches"})


def test_a_key_with_nothing_behind_it_is_not_a_diagnosis() -> None:
    """Membership was the test once, so an empty string passed the gate by being a key."""
    for nothing in ("", None, 0):
        with pytest.raises(TypeError):
            refuse_unfitted(MISFITS, BARS, {"ERT1": nothing})


def test_an_acknowledged_misfit_is_still_returned_to_be_printed() -> None:
    """A diagnosis that silences a run is the same as having no gate."""
    assert refuse_unfitted(MISFITS, BARS, {"ERT1": DIAGNOSIS}) == ("ERT1",)


def test_a_run_with_no_misfit_reported_is_not_judged() -> None:
    """A forward model and a batch that reports a median rather than a value both come
    through here, and neither has a chi squared to hold to a bar."""
    assert unfitted({"forward": None}, {"forward": 2.0}) == ()


def test_a_run_with_no_bar_is_not_judged() -> None:
    """Held to a bar somebody set, not to one this function invented."""
    assert unfitted({"TDEM": 10.105}, {}) == ()


def test_everything_fitting_passes_quietly() -> None:
    assert refuse_unfitted({"ERT2": 0.762}, {"ERT2": 2.0}) == ()
