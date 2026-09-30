"""Proposed lessons: held for a person, never written into the corpus."""

import pytest

from ofag.agent.candidates import Candidate, UnsupportedCandidate, candidates_for
from ofag.agent.dispatch import ToolError
from ofag.agent.lessons import DEFAULT_CORPUS
from ofag.agent.roles import Role, dispatcher_for

GOOD = {
    "title": "A second transmitter current in the header is not a second measurement",
    "evidence": "/CURRENT: 7.6 and, forty lines on, /TX_CURRENT: 7.58, both read as data",
    "seen_at": "data/case1_Utah FORGE/tem/site_12.usf, lines 14 and 55",
    "methods": ["tdem"],
    "procedure": "A8",
}


def test_any_role_can_propose_and_the_journal_shows_it(tmp_path) -> None:
    corpus_before = DEFAULT_CORPUS.read_bytes()
    answer = dispatcher_for(Role.AUDIT, tmp_path).call("ofag.propose_lesson", GOOD)

    assert answer["by"] == "audit" and answer["awaiting_a_person"] == 1
    journal = dispatcher_for(Role.LEAD, tmp_path).call("ofag.journal", {})
    assert journal["lessons_proposed"] == [GOOD["title"]]
    assert DEFAULT_CORPUS.read_bytes() == corpus_before, "a proposal never writes the corpus"


def test_proposals_survive_a_reload(tmp_path) -> None:
    dispatcher_for(Role.DATA, tmp_path).call("ofag.propose_lesson", GOOD)

    (item,) = candidates_for(tmp_path).items
    assert item.methods == ("tdem",) and item.procedure == "A8" and item.proposed_by == "data"


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        ({"title": "ramp bad"}, "too short"),
        ({"evidence": "it was wrong"}, "quotation"),
        ({"seen_at": "  "}, "where it was seen"),
        ({"methods": ["sonar"]}, "no method"),
        ({"procedure": "D9"}, "not a step"),
    ],
)
def test_a_proposal_without_what_a_lesson_carries_is_refused(tmp_path, change, complaint) -> None:
    book = candidates_for(tmp_path)
    fields = {**GOOD, **change, "proposed_by": "audit"}
    fields["methods"] = tuple(fields["methods"])

    with pytest.raises(UnsupportedCandidate, match=complaint):
        book.propose(Candidate(**fields))


def test_the_same_title_twice_is_refused_through_the_surface(tmp_path) -> None:
    surface = dispatcher_for(Role.INVERSION, tmp_path)
    surface.call("ofag.propose_lesson", GOOD)

    with pytest.raises(ToolError, match="already been proposed"):
        surface.call("ofag.propose_lesson", {**GOOD, "title": GOOD["title"].upper()})
