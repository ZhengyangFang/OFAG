"""Retrieval: the structured filters first, the ranking second, the corpus whole."""

import pytest

from ofag.agent.retrieval import (
    Index,
    Kind,
    Passage,
    default_index,
    passages_from_markdown,
    tokens,
)

PROCEDURE_TEXT = """# The procedure

## A. Before an inversion: checks

### A2. Validate conventions against something outside the engine

A convention is checked against a published forward result, never against the
engine's own output. F001 is the example that cost the most.

### A3. Account for every acquisition parameter the file declares

A declared ramp time that is dropped changes the early gates. F054 is the case
where the declared ramp was a thousand times too short.

## B. After a bad misfit: a ladder

### B3. Look at where the residual sits

Plot the residual by gate and by sounding before changing any setting at all.
"""

WRITE_UP_TEXT = """# A case

## The sounding

The transient sounding was inverted with its ramp, and F001 did not arise here
because no gravity was involved in this part of the survey at all.

## Short

Too short.
"""


@pytest.fixture
def index(tmp_path) -> Index:
    procedure = tmp_path / "procedure.md"
    procedure.write_text(PROCEDURE_TEXT, encoding="utf-8")
    write_up = tmp_path / "case.md"
    write_up.write_text(WRITE_UP_TEXT, encoding="utf-8")
    lessons = [
        Passage(
            id="lesson:F001",
            kind=Kind.LESSON,
            source="lessons.yaml",
            heading="F001. The engine's gz is the negative of an anomaly",
            text="The engine's gz is the negative of an anomaly, and nothing said so.",
            stage="A",
            procedure="A2",
            lessons=("F001",),
            methods=("gravity",),
        ),
        Passage(
            id="lesson:F054",
            kind=Kind.LESSON,
            source="lessons.yaml",
            heading="F054. A declared ramp a thousand times too short",
            text="A declared turn-off ramp a thousand times too short, read as it stood.",
            stage="A",
            procedure="A3",
            lessons=("F054",),
            methods=("tdem",),
        ),
    ]
    return Index(
        tuple(
            passages_from_markdown(procedure, procedure_document=True)
            + passages_from_markdown(write_up)
            + lessons
        )
    )


class TestCuttingDocuments:
    def test_a_step_is_a_procedure_passage_with_its_stage(self, index) -> None:
        step = index.get("procedure:A3")

        assert (step.kind, step.stage, step.procedure) == (Kind.PROCEDURE, "A", "A3")
        assert step.lessons == ("F054",)

    def test_a_signpost_under_a_heading_is_not_a_passage(self, index) -> None:
        assert not any(p.heading == "Short" for p in index.passages)

    def test_a_step_does_not_cite_itself(self, tmp_path) -> None:
        """A step's heading names the step; it is not a citation of a lesson."""
        path = tmp_path / "p.md"
        path.write_text(
            "## C. Before reading\n\n### C2. Score an estimator before guarding it\n\n"
            "Score it on data where the answer is known, as the Cedar Rapids run did.\n",
            encoding="utf-8",
        )

        (step,) = passages_from_markdown(path, procedure_document=True)
        assert step.lessons == ()

    def test_plurals_meet_and_stop_words_go(self) -> None:
        assert tokens("The soundings of a sounding") == ["sounding", "sounding"]

    def test_a_possessive_is_its_noun(self) -> None:
        assert tokens("SimPEG's gz") == ["simpeg", "gz"]


class TestFilteringBeforeRanking:
    def test_a_procedure_brings_its_step_and_its_lessons_first(self, index) -> None:
        hits = index.search(procedure="A2")

        assert [h.passage.id for h in hits][:2] == ["procedure:A2", "lesson:F001"]
        assert "procedure:A3" not in [h.passage.id for h in hits]

    def test_a_write_up_that_names_a_covered_lesson_comes_with_it(self, index) -> None:
        ids = [h.passage.id for h in index.search(procedure="A2")]

        assert "case#sounding" in ids

    def test_a_stage_drops_other_stages_and_keeps_the_write_ups(self, index) -> None:
        ids = {h.passage.id for h in index.search(stages=("B",), k=20)}

        assert "procedure:B3" in ids and "case#sounding" in ids
        assert not ids & {"procedure:A2", "procedure:A3", "lesson:F001"}

    def test_a_method_with_no_query_is_a_filter(self, index) -> None:
        ids = {h.passage.id for h in index.search(method="tdem", k=20)}

        assert "lesson:F054" in ids and "lesson:F001" not in ids

    def test_an_unknown_method_is_refused(self, index) -> None:
        with pytest.raises(ValueError, match="no method"):
            index.search("ramp", method="sonar")


class TestRanking:
    def test_the_query_ranks_and_says_why(self, index) -> None:
        best = index.search("declared ramp")[0]

        assert best.passage.id in {"procedure:A3", "lesson:F054"}
        assert set(best.matched) == {"declared", "ramp"}

    def test_a_method_is_a_preference_with_a_query(self, index) -> None:
        """F001 is about gravity and A2 is about no method; both match the query."""
        plain = {h.passage.id: h.score for h in index.search("engine anomaly")}
        preferred = {
            h.passage.id: h.score for h in index.search("engine anomaly", method="gravity")
        }

        assert preferred["lesson:F001"] == pytest.approx(1.5 * plain["lesson:F001"])
        assert preferred["procedure:A2"] == pytest.approx(plain["procedure:A2"])

    def test_the_same_question_gives_the_same_answer(self, index) -> None:
        first = [h.passage.id for h in index.search("ramp sounding residual")]

        assert first == [h.passage.id for h in index.search("ramp sounding residual")]

    def test_nothing_shared_is_nothing_returned(self, index) -> None:
        assert index.search("quaternion") == ()

    def test_repeated_ids_are_refused(self, index) -> None:
        with pytest.raises(ValueError, match="unique"):
            Index(index.passages + index.passages[:1])


KNOWLEDGE_TEXT = """# Magnetotellurics: received practice

The preamble says what the file is, and is not a passage.

## Test dimensionality before choosing a one-dimensional inversion

Stage: A | Step: A14 | Methods: mt

A phase tensor that is not symmetric says the ground is not layered under the
site, and a layered model of it answers a question the data did not ask.

**Check.** Compute the skew for every site and period before inverting.

**Sources.**
- Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor.
  *Geophysical Journal International*, 158(2), 457-469. doi:10.1111/j.1365-246X.2004.02281.x

## Bound a static shift before accepting it

Stage: B | Step: none | Methods: mt, tdem

A shift that fixes the fit at a factor of twenty is absorbing something else;
a nearby transient sounding bounds it (doi:10.1190/1.1442533).
"""


class TestReceivedPractice:
    @staticmethod
    def _write(tmp_path, text: str):
        path = tmp_path / "mt.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_section_is_placed_by_the_line_under_its_heading(self, tmp_path) -> None:
        from ofag.agent.retrieval import passages_from_knowledge

        first, second = passages_from_knowledge(self._write(tmp_path, KNOWLEDGE_TEXT))

        assert first.kind is Kind.RECEIVED and first.id.startswith("received:mt#")
        assert (first.stage, first.procedure, first.methods) == ("A", "A14", ("mt",))
        assert first.dois == ("10.1111/j.1365-246X.2004.02281.x",)
        assert not first.text.startswith("Stage:")
        assert (second.stage, second.procedure, second.methods) == ("B", None, ("mt", "tdem"))
        assert second.dois == ("10.1190/1.1442533",)

    @pytest.mark.parametrize(
        ("old", "new", "refusal"),
        [
            ("Stage: A | Step: A14 | Methods: mt", "Stage: B | Methods: mt", "the line under"),
            ("Methods: mt, tdem", "Methods: mt, sonar", "no method sonar"),
            ("Stage: A | Step: A14", "Stage: B | Step: A14", "not in stage B"),
            ("(doi:10.1190/1.1442533)", "(Jones 1988)", "cites a DOI"),
            ("## Bound a static", "### Bound a static", "only ## sections"),
        ],
    )
    def test_a_section_the_filters_cannot_place_is_refused(
        self, tmp_path, old: str, new: str, refusal: str
    ) -> None:
        from ofag.agent.retrieval import passages_from_knowledge

        assert old in KNOWLEDGE_TEXT
        text = KNOWLEDGE_TEXT.replace(old, new, 1)
        with pytest.raises(ValueError, match=refusal):
            passages_from_knowledge(self._write(tmp_path, text))

    def test_a_doi_keeps_its_own_parentheses_and_drops_the_sentences(self, tmp_path) -> None:
        from ofag.agent.retrieval import passages_from_knowledge

        text = KNOWLEDGE_TEXT.replace(
            "(doi:10.1190/1.1442533)",
            "(doi:10.1190/1.1442533) and doi:10.1016/S0926-9851(99)00028-2.",
        )
        _, second = passages_from_knowledge(self._write(tmp_path, text))

        assert second.dois == ("10.1190/1.1442533", "10.1016/S0926-9851(99)00028-2")

    def test_it_is_filtered_like_a_lesson_and_ordered_after_one(self, index, tmp_path) -> None:
        from ofag.agent.retrieval import passages_from_knowledge

        received = passages_from_knowledge(self._write(tmp_path, KNOWLEDGE_TEXT))
        both = Index(index.passages + tuple(received))

        a_ids = [h.passage.id for h in both.search(stages=("A",), k=20)]
        assert received[0].id in a_ids and received[1].id not in a_ids
        assert a_ids.index(received[0].id) > a_ids.index("lesson:F054")
        assert [h.passage.id for h in both.search(procedure="A14")] == [received[0].id]

    def test_a_brief_marks_it_as_not_measured_here(self, tmp_path) -> None:
        from ofag.agent.retrieval import passages_from_knowledge
        from ofag.agent.roles import RECEIVED_MARK, brief

        received = Index(tuple(passages_from_knowledge(self._write(tmp_path, KNOWLEDGE_TEXT))))
        text = brief("inversion", question="static shift transient", index=received)

        assert f"### {RECEIVED_MARK} " in text
        assert "never a reason to pass or refuse a run" in text


def test_a_step_brings_the_lessons_it_cites_as_well_as_those_placed_at_it(tmp_path) -> None:
    """B1 cites F021, which is placed at A15; asking for B1 has to bring it."""
    path = tmp_path / "p.md"
    path.write_text(
        "## B. After a bad misfit\n\n### B1. Fit a one-parameter model of the same data\n\n"
        "A richer model cannot honestly do worse than a halfspace it contains. *F021.*\n",
        encoding="utf-8",
    )
    lesson = Passage(
        id="lesson:F021",
        kind=Kind.LESSON,
        source="lessons.yaml",
        heading="F021. An unset weight",
        text="A smoothness weight left at None is not neutral.",
        stage="A",
        procedure="A15",
        lessons=("F021",),
    )
    index = Index(tuple(passages_from_markdown(path, procedure_document=True)) + (lesson,))

    assert [h.passage.id for h in index.search(procedure="B1")] == ["procedure:B1", "lesson:F021"]


class TestTheProjectsCorpus:
    """The real documents, checked for what the filters rely on."""

    def test_every_step_of_the_procedure_is_a_passage(self) -> None:
        steps = {p.procedure for p in default_index().passages if p.kind is Kind.PROCEDURE}

        expected = (
            {f"A{i}" for i in range(1, 16)}
            | {f"B{i}" for i in range(1, 8)}
            | {f"C{i}" for i in range(1, 6)}
        )
        assert steps == expected

    def test_every_lesson_is_a_passage(self) -> None:
        from ofag.agent.lessons import load_lessons

        ids = {p.id for p in default_index().passages if p.kind is Kind.LESSON}
        assert ids == {f"lesson:{lesson.id}" for lesson in load_lessons()}

    def test_benchmark_outcome_reports_are_not_indexed(self) -> None:
        sources = {p.source for p in default_index().passages}
        assert not any("/benchmark/results/" in source for source in sources)

    def test_every_method_has_received_practice_at_every_stage_it_is_read(self) -> None:
        """What the cases never touched is covered from the literature, method by method."""
        from ofag.agent.lessons import METHOD_NAMES

        received = [p for p in default_index().passages if p.kind is Kind.RECEIVED]

        assert {m for p in received for m in p.methods} == set(METHOD_NAMES)
        assert {p.stage for p in received} == {"A", "B", "C"}
        assert all(p.dois for p in received)
        assert not any(p.source.endswith("knowledge/README.md") for p in received)

    def test_a_received_step_is_a_step_of_the_procedure(self) -> None:
        passages = default_index().passages
        steps = {p.procedure for p in passages if p.kind is Kind.PROCEDURE}

        received = {p.procedure for p in passages if p.kind is Kind.RECEIVED and p.procedure}
        assert received <= steps

    def test_a_passage_cites_a_file_that_is_there(self) -> None:
        from ofag.agent.lessons import PROJECT_ROOT

        for source in {p.source for p in default_index().passages}:
            assert (PROJECT_ROOT / source).is_file(), source
