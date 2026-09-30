"""Finding a lesson by what it is rather than by what it sounds like."""

import pytest

from ofag.agent.lessons import Decision, load_lessons, search


@pytest.fixture(scope="module")
def lessons():
    return load_lessons()


def test_no_filter_returns_everything_in_a_stable_order(lessons) -> None:
    """An agent comparing two runs of a search wants a difference that is real."""
    first, second = search(lessons), search(lessons)

    assert len(first) == len(lessons)
    assert [x.id for x in first] == [x.id for x in second]


def test_a_procedure_gathers_the_failures_it_was_written_for(lessons) -> None:
    conventions = search(lessons, procedure="A2")

    assert {x.id for x in conventions} == {
        "F068",
        "F073",
        "F001",
        "F023",
        "F028",
        "F029",
        "F032",
        "F033",
    }
    assert all(x.procedure == "A2" for x in conventions)


def test_the_text_match_misses_the_sharpest_sign_lesson(lessons) -> None:
    """The weak half, pinned rather than hidden."""
    by_word = {x.id for x in search(lessons, text="sign")}
    by_procedure = {x.id for x in search(lessons, procedure="A2")}

    assert "F001" not in by_word
    assert "F001" in by_procedure


def test_the_filters_compose(lessons) -> None:
    """What an agent about to make a choice would ask for: the judgements nobody has written
    a check for yet."""
    open_judgements = search(lessons, decision=Decision.JUDGEMENT, uncovered_only=True)

    assert {x.id for x in open_judgements} == {
        "F060",
        "F072",
        "F002",
        "F009",
        "F014",
        "F024",
        "F042",
    }
    assert all(x.covered_by is None for x in open_judgements)


def test_a_decision_may_be_given_as_its_name(lessons) -> None:
    """A tool call arrives as JSON, so the enum has to accept a string."""
    assert search(lessons, decision="judgement") == search(lessons, decision=Decision.JUDGEMENT)


def test_a_query_that_matches_nothing_says_so_rather_than_guessing(lessons) -> None:
    assert search(lessons, text="magnetotelluric anisotropy in the mantle") == ()
    assert search(lessons, procedure="A99") == ()
