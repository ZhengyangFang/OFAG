"""The corpus of recorded failures, and the claims it is allowed to make."""

import re
from pathlib import Path

import pytest

from ofag.agent.lessons import (
    DEFAULT_CORPUS,
    Decision,
    Tier,
    judgements,
    load_lessons,
    uncovered,
)

ROOT = Path(__file__).resolve().parents[1]
PROCEDURES = ROOT / "docs" / "agent_validation_and_debugging.md"


@pytest.fixture(scope="module")
def lessons():
    return load_lessons()


def test_the_corpus_loads_and_every_identifier_is_its_own(lessons) -> None:
    """Sixty-one from three cases and one from building the agent layer."""
    assert len(lessons) == 101
    assert len({lesson.id for lesson in lessons}) == 101
    assert {lesson.source for lesson in lessons} >= {"agent"}


def test_a_claimed_check_names_a_file_that_exists(lessons) -> None:
    """A corpus that claims coverage it does not have is worse than one that claims none: the
    gaps are what it is counted for."""
    missing = [
        f"{lesson.id} -> {lesson.covered_by}"
        for lesson in lessons
        if lesson.covered_by is not None and not (ROOT / lesson.covered_by).is_file()
    ]
    assert not missing, f"covered_by names files that are not there: {missing}"


def test_a_cited_procedure_is_a_step_that_exists(lessons) -> None:
    """The procedures are renumbered as they grow -- A9 was inserted ahead of what is now A11
    -- so a citation has to be checked rather than trusted."""
    document = PROCEDURES.read_text(encoding="utf-8")
    missing = sorted(
        {
            lesson.procedure
            for lesson in lessons
            if lesson.procedure is not None and f"### {lesson.procedure}." not in document
        }
    )
    assert not missing, f"no such step in {PROCEDURES.name}: {missing}"


def test_every_lesson_from_our_own_cases_is_measured(lessons) -> None:
    """Sixty-one failures we hit ourselves, on data still in hand."""
    assert {lesson.tier for lesson in lessons} == {Tier.MEASURED}
    assert all(lesson.gates_work for lesson in lessons)


def test_most_of_them_ran_clean(lessons) -> None:
    """The reason this corpus exists rather than a list of stack traces."""
    silent = [lesson for lesson in lessons if lesson.silent]
    assert len(silent) == 82


def test_a_third_of_them_were_decisions_nobody_recorded(lessons) -> None:
    """Fourteen judgements and twelve that the data could have settled."""
    assert len(list(judgements(lessons))) == 14
    assert len([x for x in lessons if x.decision is Decision.MEASURABLE]) == 12


def test_the_coverage_gap_is_stated_rather_than_rounded_off(lessons) -> None:
    """Fifty-two of a hundred and one have no check that fires on them."""
    assert len(list(uncovered(lessons))) == 52


def test_the_corpus_lives_where_the_prose_it_came_from_does() -> None:
    assert DEFAULT_CORPUS.is_file()
    assert DEFAULT_CORPUS.parent.name == "lessons"


class TestTheIdentifiers:
    """Renumbered on 2026-09-24 from site letters (P, C, L, S) to F and three digits, because
    C1 to C5 were both lessons and procedure steps."""

    def test_every_identifier_is_f_and_three_digits(self, lessons) -> None:
        assert all(re.fullmatch(r"F\d{3}", lesson.id) for lesson in lessons)

    def test_no_lesson_can_be_read_as_a_procedure_step(self, lessons) -> None:
        steps = set(re.findall(r"^### ([ABC]\d+)\.", PROCEDURES.read_text("utf-8"), re.M))

        assert steps and not {lesson.id for lesson in lessons} & steps

    def test_a_former_identifier_still_finds_its_lesson(self, lessons) -> None:
        from ofag.agent.lessons import find

        assert find(lessons, "P19").id == "F001"
        assert find(lessons, "c4").id == find(lessons, "F034").id

    def test_every_former_identifier_is_kept_once(self, lessons) -> None:
        """The 75 renumbered on 2026-09-24 kept theirs; those added since never had one."""
        former = [lesson.former_id for lesson in lessons if lesson.former_id]

        assert len(former) == len(set(former)) == 75
        assert all(lesson.former_id is None for lesson in lessons[75:])

    def test_a_malformed_identifier_is_refused(self, tmp_path) -> None:
        corpus = tmp_path / "lessons.yaml"
        corpus.write_text(
            "lessons:\n  - id: P19\n    title: t\n    source: case1_forge\n    tier: measured\n"
            "    silent: true\n    decision: none\n    evidence: e\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="F and three digits"):
            load_lessons(corpus)


class TestTheNewFields:
    def test_methods_come_from_the_vocabulary(self, lessons) -> None:
        from ofag.agent.lessons import METHOD_NAMES

        assert all(set(lesson.methods) <= set(METHOD_NAMES) for lesson in lessons)

    def test_the_defects_an_agent_found_are_the_ones_the_plan_counts(self, lessons) -> None:
        """Five defects an agent found that nothing else had, and the harness leak an agent
        reported makes six."""
        from ofag.agent.lessons import FoundBy

        found = {lesson.id for lesson in lessons if lesson.found_by is FoundBy.AGENT}
        assert found == {"F052", "F053", "F054", "F056", "F091", "F092"}

    def test_an_unknown_method_is_refused(self, tmp_path) -> None:
        corpus = tmp_path / "lessons.yaml"
        corpus.write_text(
            "lessons:\n  - id: F001\n    title: t\n    source: case1_forge\n    tier: measured\n"
            "    silent: true\n    decision: none\n    evidence: e\n    methods: [sonar]\n",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="sonar"):
            load_lessons(corpus)


def test_every_evidence_is_quoted_from_a_document_that_still_says_it(lessons) -> None:
    """The README promises the evidence is quoted, so the record cannot drift."""
    words = lambda text: " ".join(re.findall(r"[a-z0-9]+", text.lower()))  # noqa: E731
    docs = [
        words(path.read_text("utf-8"))
        for path in (ROOT / "docs").rglob("*.md")
        if path != ROOT / "docs" / "lessons" / "README.md"
    ]
    drifted = [x.id for x in lessons if not any(words(x.evidence) in doc for doc in docs)]

    assert drifted == []
