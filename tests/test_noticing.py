"""Silent replays: work with a defect in it, and nothing saying so."""

import textwrap

import pytest

from ofag.agent.lessons import load_lessons
from ofag.agent.noticing import (
    load_bearing,
    load_silent_replays,
    refuse_hinting_tasks,
    score_noticing,
)


@pytest.fixture(scope="module")
def replays():
    return load_silent_replays()


@pytest.fixture(scope="module")
def f034(replays):
    (one,) = [r for r in replays if r.lesson == "F034"]
    return one


class TestTheTasksDoNotGiveItAway:
    def test_the_real_corpus_does_not_hint(self, replays) -> None:
        """Loading it is the assertion -- the loader refuses otherwise."""
        assert refuse_hinting_tasks(replays) == ()

    def test_a_task_holding_a_word_its_tell_is_scored_on_is_refused(self, tmp_path) -> None:
        """F011's first draft, which is where this check came from: the task listed what the
        run directories hold, and one of the things they hold is the coverage array that
        *is* the observable."""
        corpus = tmp_path / "hinting.yaml"
        corpus.write_text(
            textwrap.dedent("""
            silent:
              - lesson: X1
                task: >-
                  Read the run directory, which holds the model, the mesh and a
                  coverage array, and say how deep it supports a claim.
                gates: [refuse_unstated_reach]
                on_path: false
                tells:
                  - what: the mesh was built deeper than the data reaches
                    names: ["coverage", "sensitivity"]
                  - what: a depth has to say where it came from
                    names: ["declared", "provenance"]
                cost: >-
                  A first model that claimed the aquifer to forty metres on
                  resistivity whose own coverage array stops at fourteen.
            """),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="coverage"):
            load_silent_replays(corpus)

    def test_a_task_that_says_something_is_wrong_is_refused(self, tmp_path) -> None:
        corpus = tmp_path / "warning.yaml"
        corpus.write_text(
            textwrap.dedent("""
            silent:
              - lesson: X2
                task: >-
                  Build the cell grid over the box, and make sure the depths are
                  measured from somewhere sensible.
                gates: [refuse_unmeasured_terrain]
                on_path: true
                tells:
                  - what: the ground is not flat
                    names: ["relief", "topograph"]
                  - what: the cells hang from a plane
                    names: ["above the ground", "drape"]
                cost: >-
                  Thirty-six metres between the fifth and ninety-fifth
                  percentiles of the ground inside a box modelled to a hundred
                  and twenty metres.
            """),
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="make sure"):
            load_silent_replays(corpus)

    def test_every_task_asks_for_work_and_not_for_an_opinion(self, replays) -> None:
        """A silent replay that asks "which would you choose" is a judgement replay wearing
        the wrong name, and the judgement harness already has those."""
        for replay in replays:
            assert "?" not in replay.task, replay.lesson


class TestScoring:
    def test_a_convincing_blind_answer_scores_zero(self, f034) -> None:
        """The hard case, not the easy one."""
        blind = (
            "Grid: 60 columns east by 30 north by 60 layers, 108,000 cells of 50 x 50 x 2 m. "
            "Cell centres sit at the middle of each cell, the first at 603525 E, 4650025 N. "
            "Depth is measured downwards from the top of the model volume, z = 0, so cell "
            "centres run 1 m to 119 m. The datum for z is the top face of the box."
        )

        scored = score_noticing(f034, blind)

        assert scored.saw == ()
        assert not scored.noticed

    def test_an_answer_that_sees_it_can_score_full_marks(self, f034) -> None:
        seeing = (
            "Before laying the grid out I looked at the ground under the box. The DTM runs "
            "195.4 m to 273.4 m inside it, 36 m between the fifth and ninety-fifth "
            "percentiles, so a single flat top face would leave part of the box tens of "
            "metres out -- cells in the air over the valley wall. I hung each column from "
            "its own ground elevation."
        )

        scored = score_noticing(f034, seeing)

        assert scored.noticed
        assert "everything" in scored.summary

    def test_half_seen_is_not_noticed(self, f034) -> None:
        """The bar is every tell, because a defect half-seen is one that gets written up as a
        caveat and inverted anyway."""
        half = "The ground under the box has 58 m of relief, which is worth noting."

        scored = score_noticing(f034, half)

        assert len(scored.saw) == 1
        assert not scored.noticed
        assert "missed" in scored.summary


class TestTheCorpus:
    def test_every_replay_names_the_gate_it_is_asking_about(self) -> None:
        """There is no second arm, so the gate is not a condition -- it is the thing the run
        decides the fate of."""
        assert load_bearing() == {
            "F034": ("refuse_unmeasured_terrain",),
            "F011": ("refuse_unstated_reach",),
            "F043": ("refuse_unsound_picks",),
            "F031": ("refuse_out_of_domain",),
            "F049": ("refuse_unmeasured_terrain",),
            "F047": ("refuse_out_of_domain",),
        }

    def test_the_corpus_is_not_all_on_the_path(self, replays) -> None:
        """The first three were all on-path and all three were noticed, which measures less
        than it looks: the task asked a question whose answer was the tell."""
        on, off = [r for r in replays if r.on_path], [r for r in replays if not r.on_path]

        assert len(off) >= len(on) / 2, "the off-path half is the half that measures"
        # Keep off-path tasks focused on deliverables.
        for replay in off:
            assert any(
                word in replay.task.lower()
                for word in ("produce", "prepare", "read it and", "set up", "build")
            ), replay.lesson

    def test_every_replay_is_a_lesson_that_ran_clean(self, replays) -> None:
        """A silent replay of a failure that announced itself is not a silent replay."""
        lessons = {lesson.id: lesson for lesson in load_lessons()}
        for replay in replays:
            assert replay.lesson in lessons, replay.lesson
            assert lessons[replay.lesson].silent, replay.lesson

    def test_every_replay_has_at_least_two_tells(self, replays) -> None:
        """One observable is a keyword, and a keyword is guessable."""
        for replay in replays:
            assert len(replay.tells) >= 2, replay.lesson

    def test_every_replay_says_what_the_defect_cost(self, replays) -> None:
        for replay in replays:
            assert len(replay.cost) > 80, replay.lesson
