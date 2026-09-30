"""Decisions posed again, and the rules that keep the posing honest."""

import sys
from pathlib import Path

import pytest

from ofag.agent.decisions import Settlement
from ofag.agent.lessons import Decision, load_lessons
from ofag.agent.replay import load_replays, score

ROOT = Path(__file__).resolve().parents[1]


#: The field releases are not in the repository: each case note under docs/ names the
#: release by its DOI and the reader fetches it.
FETCH_HINT = "the field release is not on disk; fetch it from the DOI in the case note under docs/"


@pytest.fixture(scope="module")
def replays():
    return load_replays()


@pytest.fixture(scope="module")
def lessons():
    return {lesson.id: lesson for lesson in load_lessons()}


def test_the_set_covers_the_judgements_whose_data_is_still_here(replays, lessons) -> None:
    """Eight of fourteen have their release on disk; six of the eight can actually be run."""
    if not all(lessons[replay.lesson].data_present for replay in replays):
        pytest.skip(FETCH_HINT)
    assert len(replays) == 8
    for replay in replays:
        lesson = lessons[replay.lesson]
        assert lesson.decision is Decision.JUDGEMENT, f"{replay.lesson} is not a judgement"
        assert lesson.data_present, f"{replay.lesson} has no data left to replay against"

    judgements = {i for i, x in lessons.items() if x.decision is Decision.JUDGEMENT}
    assert {r.lesson for r in replays} == {i for i in judgements if lessons[i].data_present}


def test_every_named_probe_is_there(replays) -> None:
    """Six probes exist and run."""
    for replay in replays:
        if replay.probe is not None:
            assert (ROOT / replay.probe).is_file(), replay.probe
            assert replay.runnable
    assert sum(replay.runnable for replay in replays) == 6
    assert sum(replay.blind for replay in replays) == 5
    assert [r.lesson for r in replays if r.runnable and not r.blind] == ["F014"]


def test_the_ones_that_cannot_be_run_say_what_stops_them(replays) -> None:
    """Three, and not for the same reason."""
    blocked = [replay for replay in replays if replay.blocked_by is not None]

    assert {replay.lesson for replay in blocked} == {"F002", "F009", "F014"}
    assert {replay.lesson for replay in blocked if replay.probe is None} == {"F002", "F009"}
    for replay in blocked:
        assert len(replay.blocked_by or "") > 60


def test_a_situation_this_project_has_since_tidied_says_so(replays) -> None:
    """F024's release warned about a model in prose and shipped its surface under a neutral
    name."""
    altered = [replay for replay in replays if replay.caveat is not None]

    assert {replay.lesson for replay in altered} == {"F024"}
    assert "renamed" in (altered[0].caveat or "")


@pytest.mark.parametrize("lesson", ["F037", "F043", "F015", "F024"])
def test_the_quick_probes_run_and_print_a_situation(replays, lessons, lesson) -> None:
    """Runnable means the probe runs."""
    import subprocess

    if not lessons[lesson].data_present:
        pytest.skip(f"{lesson}: {FETCH_HINT}")

    replay = next(r for r in replays if r.lesson == lesson)
    assert replay.probe is not None
    finished = subprocess.run(
        [sys.executable, replay.probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )

    assert finished.returncode == 0, finished.stderr[-800:]
    assert len(finished.stdout.splitlines()) > 5
    # The probe prints the situation. It must not print the answer.
    if replay.historical is not None:
        assert replay.historical.chose.lower() not in finished.stdout.lower()


def test_a_probe_reads_the_release_and_not_the_write_up(replays) -> None:
    """The situation has to come from the data."""
    for replay in replays:
        if replay.probe is None:
            continue
        source = (ROOT / replay.probe).read_text(encoding="utf-8")
        assert "docs/" not in source, f"{replay.probe} reads the write-ups"
        assert "data/" in source, f"{replay.probe} reads no release data"


def test_the_question_does_not_point_at_where_the_answer_lives(replays) -> None:
    """`recorded_at` names a constant, and a constant is a short way to the answer for
    anything that can read the tree."""
    for replay in replays:
        if replay.historical is None:
            continue
        constant = replay.historical.recorded_at.rsplit("::", 1)[-1]
        assert constant.lower() not in replay.question.lower()
        assert replay.historical.because.lower() not in replay.question.lower()


def test_the_probes_do_not_name_the_lesson_they_replay(replays) -> None:
    """A lesson identifier in a probe is a lookup key for the write-up that holds the answer."""
    for replay in replays:
        if replay.probe is None:
            continue
        source = (ROOT / replay.probe).read_text(encoding="utf-8")
        body = source[source.index('"""', source.index('"""') + 3) :]
        assert f" {replay.lesson} " not in body, f"{replay.probe} names {replay.lesson}"


def test_every_one_of_them_is_expected_to_be_a_judgement(replays) -> None:
    """An answer of `measured` is scored wrong, and is the interesting kind of wrong: it has
    either found something this project missed or claimed a measurement nobody ran, which
    is F039."""
    assert {replay.expect for replay in replays} == {Settlement.JUDGED}


def test_what_was_actually_decided_passes_its_own_rubric(replays) -> None:
    """A rubric the historical answer fails is a rubric, not a result."""
    written = [replay for replay in replays if replay.historical is not None]
    assert len(written) == 3

    for replay in written:
        assert replay.historical is not None
        got = score(replay, replay.historical)
        assert got.settlement_correct
        assert not got.missed, f"{replay.lesson} missed {got.missed}"
        assert got.complete


def test_an_answer_that_calls_a_judgement_settled_is_marked_wrong(replays) -> None:
    replay = next(r for r in replays if r.lesson == "F037")
    assert replay.historical is not None
    pretending = replay.historical.model_copy(
        update={"settlement": Settlement.MEASURED, "measurement": "compared the two lists"}
    )

    assert not score(replay, pretending).settlement_correct


def test_an_answer_that_skips_the_evidence_is_marked_incomplete(replays) -> None:
    """The rubric's crude half: facts the probe put on the table that the answer has to have
    used."""
    replay = next(r for r in replays if r.lesson == "F037")
    assert replay.historical is not None
    vague = replay.historical.model_copy(
        update={
            "because": "the separate table is the one that looks right for this survey",
            "informed_by": (),
            # Also blanked, because a reversal condition that cites the cost earns the
            # credit the reason threw away -- which is correct, and would make this test
            # check one group instead of two.
            "reverses_if": "somebody turns up who knows this site and says otherwise",
            "options": tuple(
                option.model_copy(update={"cost": "worse than the other one by a good deal"})
                for option in replay.historical.options
            ),
        }
    )

    got = score(replay, vague)
    assert got.settlement_correct
    assert len(got.missed) == 2
    assert not got.complete
