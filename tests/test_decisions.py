"""What a choice has to carry, and how many of ours carry it."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ofag.agent.audit import audit_tree
from ofag.agent.decisions import DecisionRecord, Option, Settlement

ROOT = Path(__file__).resolve().parents[1]

#: A real modelling choice, used to exercise the complete decision schema.
DOI_CHOICE = {
    "question": "Use the contractor's investigation depth for Cedar Rapids?",
    "options": [
        Option(
            name="use it",
            cost=(
                "the model's resolved extent depends on an independently produced "
                "bound rather than one derived from its own inversion"
            ),
        ),
        Option(
            name="omit it",
            cost=(
                "the model would assign geology below the depth for which any "
                "delivered sounding has an investigation-depth bound"
            ),
        ),
    ],
    "chose": "use it",
    "because": (
        "the current AEM inversion has no investigation-depth calculation of its own, "
        "while the delivered model has a bound at every sounding"
    ),
    "settlement": Settlement.JUDGED,
    "reverses_if": (
        "the current inversion computes its own validated investigation depth "
        "or the contractor's values prove incompatible with the acquired data"
    ),
    "recorded_at": "scripts/case2_cedar_rapids.py::DOI_COLUMN",
}


def test_a_real_decision_records_completely() -> None:
    record = DecisionRecord(**DOI_CHOICE)

    assert record.chose == "use it"
    assert record.settlement is Settlement.JUDGED
    assert record.measurement is None


def test_one_option_is_not_a_decision() -> None:
    """The thing that goes unrecorded is always the alternative."""
    with pytest.raises(ValidationError, match="at least two options"):
        DecisionRecord(**DOI_CHOICE | {"options": DOI_CHOICE["options"][:1], "chose": "use it"})


def test_a_choice_has_to_be_one_of_the_options() -> None:
    with pytest.raises(ValidationError, match="not one of"):
        DecisionRecord(**DOI_CHOICE | {"chose": "scale it without recording the factor"})


def test_an_option_with_no_cost_is_refused() -> None:
    """"Worse" is not a cost. A cost is in the project's own units."""
    with pytest.raises(ValidationError):
        Option(name="omit it", cost="worse")


def test_a_judged_decision_may_not_name_a_measurement() -> None:
    """A judgement that cites a measurement is a measurement someone declined to believe, and
    the two should not be recorded as the same thing."""
    with pytest.raises(ValidationError, match="names what settled it"):
        DecisionRecord(**DOI_CHOICE | {"measurement": "compared the two depth bounds"})


def test_a_measured_decision_must_name_its_measurement() -> None:
    """The failure mode of an agent that consults its user is asking about a question the
    data can answer, which is F039 from the far side."""
    with pytest.raises(ValidationError, match="names what settled it"):
        DecisionRecord(**DOI_CHOICE | {"settlement": Settlement.MEASURED})

    settled = DecisionRecord(
        **DOI_CHOICE
        | {
            "settlement": Settlement.MEASURED,
            "measurement": "compared the supplied DOI with a new validated calculation",
        }
    )
    assert settled.measurement is not None


def test_a_judgement_may_record_what_it_consulted_and_found_inconclusive() -> None:
    """Consulted and inconclusive is not the same as not consulted."""
    record = DecisionRecord(
        **DOI_CHOICE
        | {"informed_by": ("compared the delivered depth bound with the smooth recovered profile",)}
    )

    assert record.settlement is Settlement.JUDGED
    assert record.measurement is None
    assert "The data does not settle this: compared the delivered" in record.as_comment()


def test_a_reversal_that_repeats_the_reason_is_refused() -> None:
    with pytest.raises(ValidationError, match="repeats because"):
        DecisionRecord(**DOI_CHOICE | {"reverses_if": DOI_CHOICE["because"]})


def test_the_record_renders_to_the_comment_form_the_code_uses() -> None:
    """A record in a store beside the code is one nobody reads; a paragraph in a comment is
    one nothing can check."""
    comment = DecisionRecord(**DOI_CHOICE).as_comment()

    assert all(line.startswith("#:") for line in comment.splitlines())
    assert all(len(line) <= 79 for line in comment.splitlines())
    assert "This is wrong if" in comment
    assert "The data does not settle this, and nothing was run to try." in comment
    assert "Chosen over: omit it -- the model would assign geology" in comment
    # The rendering carries the word the audit reads a choice by, so a block this
    # produces is visible to the same grep as a hand-written one.
    from ofag.agent.audit import CHOICE_MARKERS

    assert any(marker in comment.lower() for marker in CHOICE_MARKERS)


class TestWhereTheTreeStands:
    """The audit's current reading, asserted so that it moves on purpose."""

    def test_the_case_scripts_record_their_choices(self) -> None:
        found = audit_tree(ROOT / "scripts")
        choices = [choice for choice in found if choice.reads_as_choice]

        assert len(found) == 113
        assert len(choices) == 56

    def test_almost_none_of_them_say_what_would_make_them_wrong(self) -> None:
        """Six choices state when their rationale expires."""
        choices = [c for c in audit_tree(ROOT / "scripts") if c.reads_as_choice]
        stated = [choice for choice in choices if choice.states_reversal]

        assert len(stated) == 6
        assert {choice.constant for choice in stated} == {
            "ELEVATION_SOURCE",
            "ERT_COVERAGE_DROP",
            "ERT_LAMBDA_START",
            "SUPPORTED_SHIFT_M",
            "VERDICT_BAND_M",
            "_diagnoses()",
        }

    def test_a_constant_that_only_describes_is_not_counted_as_a_choice(self) -> None:
        """Most documented constants are measurements, and a measurement is not a decision."""
        found = audit_tree(ROOT / "scripts")
        descriptive = [choice for choice in found if not choice.reads_as_choice]

        assert len(descriptive) == 57
        assert all(not choice.incomplete for choice in descriptive)
