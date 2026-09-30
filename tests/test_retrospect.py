"""The arithmetic of the claim the agent layer rests on."""

import pytest

from ofag.agent.lessons import load_lessons
from ofag.agent.retrospect import ENFORCED, Kind, retrospect, unenforced


@pytest.fixture(scope="module")
def lessons():
    return load_lessons()


#: The procedures `docs/agent_validation_and_debugging.md` defines.
PROCEDURES = (
    {f"A{n}" for n in range(1, 16)}
    | {f"B{n}" for n in range(1, 8)}
    | {f"C{n}" for n in range(1, 6)}
)


class TestTheDeclaration:
    def test_every_enforcement_names_a_procedure_that_exists(self) -> None:
        """Or names none, which `refuse_unfitted` does and which is a statement about the
        corpus rather than about the gate."""
        for item in ENFORCED:
            assert item.enforces in PROCEDURES or item.enforces == "", item.what

    def test_no_two_pieces_claim_the_same_procedure(self) -> None:
        """A procedure with two enforcers is a procedure whose boundary nobody has drawn."""
        claimed = [item.enforces for item in ENFORCED if item.enforces]

        assert len(set(claimed)) == len(claimed)

    def test_a_procedure_identifier_is_never_a_lesson_identifier(self, lessons) -> None:
        """C1 to C5 were once both the model-building procedures and Cedar Rapids' lesson
        identifiers."""
        assert not {lesson.id for lesson in lessons} & PROCEDURES
        assert all("procedure" in reach.summary for reach in retrospect(lessons))

    def test_every_kind_is_used(self) -> None:
        assert {item.kind for item in ENFORCED} == set(Kind)


class TestWhatItReaches:
    def test_the_conventions_reach_eight_and_show_one(self, lessons) -> None:
        """Eight of the sixty-nine and seven of them silent, with six carrying a test -- and
        exactly one shown refused."""
        (conventions,) = [r for r in retrospect(lessons) if r.enforcement.kind is Kind.CHECK]

        assert len(conventions.lessons) == 8
        assert conventions.silent == 7
        assert conventions.checked == 6
        assert conventions.shown == ("F001",)

    def test_the_pieces_that_reach_nothing_the_corpus_recorded(self, lessons) -> None:
        """Two, down from four, and for two different reasons."""
        empty = [r.enforcement.what for r in retrospect(lessons) if not r.lessons]

        assert len(empty) == 2
        assert "refuse_unfitted" in empty
        assert "DecisionRecord" in empty

    def test_the_weak_statement_is_smaller_than_the_strong_one(self, lessons) -> None:
        """43 addressed against 38 with a test, which looks backwards and is not: they count
        different things."""
        addressed = {x.id for reach in retrospect(lessons) for x in reach.lessons}
        checked = {x.id for x in lessons if x.covered_by is not None}

        assert len(addressed) == 76
        assert len(checked) == 49
        assert addressed & checked == {
            "F031",
            "F032",
            "F034",
            "F037",
            "F039",
            "F043",
            "F044",
            "F045",
            "F048",
            "F053",
            "F054",
            "F058",
            "F059",
            "F063",
            "F064",
            "F066",
            "F067",
            "F068",
            "F069",
            "F071",
            "F001",
            "F003",
            "F005",
            "F011",
            "F015",
            "F016",
            "F017",
            "F018",
            "F020",
            "F021",
            "F022",
            "F023",
            "F028",
            "F029",
            "F030",
            "F055",
            "F057",
            "F081",
            "F084",
            "F085",
        }
        assert checked - addressed


class TestWhatItDoesNot:
    def test_the_unplaced_are_counted_and_not_dropped(self, lessons) -> None:
        """Four, down from nineteen once two procedures were written for the shapes the
        nineteen kept making."""
        assert {x.id for x in unenforced(lessons)[""]} == {
            "F060",
            "F061",
            "F074",
            "F019",
            "F087",
            "F097",
        }

    def test_the_two_largest_gaps_are_named(self, lessons) -> None:
        """A1, A3 and A4 have gates."""
        gaps = unenforced(lessons)
        widest = sorted(
            ((key, rows) for key, rows in gaps.items() if key), key=lambda kv: -len(kv[1])
        )

        # A14 left this list when one narrow schema arrived for it, and took all eight
        # of its lessons with it although the test shows the refusal on one.
        assert [(key, len(rows)) for key, rows in widest[:2]] == [("A10", 3), ("A7", 3)]
        assert len(gaps[""]) == 6

    def test_everything_is_in_exactly_one_half(self, lessons) -> None:
        """The two halves partition the corpus, so neither can be padded."""
        addressed = {x.id for reach in retrospect(lessons) for x in reach.lessons}
        left = {x.id for rows in unenforced(lessons).values() for x in rows}

        assert addressed | left == {x.id for x in lessons}
        assert not (addressed & left)
