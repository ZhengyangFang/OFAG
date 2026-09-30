"""What a project cannot reconstruct from its own artifacts."""

import pytest

from ofag.agent.dispatch import Dispatcher, ToolError
from ofag.agent.remembering import Journal, Kind, UnsupportedNote, journal_for
from ofag.agent.tools import Tier

#: The message that is the reason this module exists.
FOUR_ASKS = (
    "a memory",
    "reach the web for knowledge",
    "operate every function of the software independently",
    "spawn a subagent to write code",
)


@pytest.fixture
def book(tmp_path) -> Journal:
    return journal_for(tmp_path)


@pytest.fixture
def dispatcher(tmp_path):
    return Dispatcher(
        artifact_root=tmp_path / "artifacts",
        granted=(Tier.READ, Tier.COMPUTE, Tier.WRITE),
    )


class TestAnAskIsOwedUntilSomethingAnswersIt:
    def test_the_four_that_went_missing(self, book) -> None:
        """The case this was built for."""
        for ask in FOUR_ASKS:
            book.note(Kind.ASKED, ask)

        assert [note.what for note in book.still_owed()] == list(FOUR_ASKS)

    def test_satisfying_one_leaves_the_rest_owed(self, book) -> None:
        for ask in FOUR_ASKS:
            book.note(Kind.ASKED, ask)

        book.satisfy(
            "operate every function of the software independently",
            by="18 tools, all 18 callable; fourteen readers and the cell grid",
        )

        assert len(book.still_owed()) == 3
        assert "operate every function" not in " ".join(n.what for n in book.still_owed())

    def test_the_ask_survives_being_satisfied(self, book) -> None:
        """Append-only, like the ledger."""
        book.note(Kind.ASKED, FOUR_ASKS[0])
        book.satisfy(FOUR_ASKS[0], by="a journal beside the runs")

        assert [note.kind for note in book.notes] == [Kind.ASKED, Kind.SATISFIED]
        assert book.still_owed() == ()

    def test_satisfying_something_nobody_asked_for_is_refused(self, book) -> None:
        """Either a typo or a different ask, and both are worth stopping for."""
        book.note(Kind.ASKED, FOUR_ASKS[0])

        with pytest.raises(UnsupportedNote, match="nothing was asked for in these words"):
            book.satisfy("something else entirely", by="a thing I did")

    def test_the_refusal_says_what_is_actually_owed(self, book) -> None:
        book.note(Kind.ASKED, FOUR_ASKS[0])

        with pytest.raises(UnsupportedNote, match="a memory"):
            book.satisfy("mis-typed ask", by="x")

    def test_owed_is_derived_and_not_a_flag(self, book) -> None:
        """So an ask cannot be marked done by anything except a satisfaction that names it --
        the `replayable: true` problem from `lessons`."""
        book.note(Kind.ASKED, FOUR_ASKS[1])
        book.note(Kind.TRIED, "something unrelated", because="it did not work for a stated reason")

        assert [note.what for note in book.still_owed()] == [FOUR_ASKS[1]]


class TestWhatWasTriedAndDropped:
    def test_an_approach_has_to_say_why_it_was_dropped(self, book) -> None:
        """The next reader has the same good idea."""
        with pytest.raises(UnsupportedNote, match="the same good idea"):
            book.note(Kind.TRIED, "a smoothing spline through the pooled sweeps", because="no")

    def test_the_two_an_agent_volunteered_because_there_was_nowhere_to_put_them(self, book) -> None:
        book.note(
            Kind.TRIED,
            "flag gathers by disagreement with an overlapping sweep",
            because="no two sweeps share a gate time, so it needs interpolation across a "
            "decay whose slope swings between -1.2 and -3.7, and the bias swamps the signal",
        )
        book.note(
            Kind.TRIED,
            "a smoothing spline through the pooled sweeps",
            because="it simply followed the bad tails",
        )

        assert len(book.of(Kind.TRIED)) == 2
        assert "spline" in book.report()


class TestARefutationIsAClaimToo:
    def test_ruling_something_out_has_to_say_where_it_was_measured(self, book) -> None:
        """F052: the model norm was ruled out of ERT1's diagnosis on a figure that is the gap
        between two global maxima, twenty metres below the band and outside the window the
        claim is read in."""
        with pytest.raises(UnsupportedNote, match="twenty metres below the band"):
            book.note(
                Kind.RULED_OUT,
                "the model norm changes nothing in the 5-15 m band",
                because="it moved the band by 1 ohm.m",
            )

    def test_the_corrected_one_records_the_window(self, book) -> None:
        note = book.note(
            Kind.RULED_OUT,
            "the model norm barely moves the 5-15 m band",
            because="median 150.9 to 263.1 and maximum 311.6 to 618.5, so it moves it a lot",
            measured_where="the x = 48-76 m window at 5-15 m, not the global maxima at 33 m",
        )

        assert "48-76" in note.measured_where

    def test_a_refutation_still_needs_its_reason(self, book) -> None:
        with pytest.raises(UnsupportedNote, match="the same good idea"):
            book.note(
                Kind.RULED_OUT, "a hypothesis", because="no", measured_where="somewhere specific"
            )


class TestReadingItBack:
    def test_it_survives_a_reopen(self, tmp_path) -> None:
        first = journal_for(tmp_path)
        first.note(Kind.ASKED, FOUR_ASKS[0])
        first.note(Kind.TRIED, "an approach", because="a reason long enough to be one")

        again = journal_for(tmp_path)

        assert len(again.notes) == 2
        assert [note.what for note in again.still_owed()] == [FOUR_ASKS[0]]

    def test_looking_for_a_good_idea_finds_it_was_already_had(self, book) -> None:
        book.note(
            Kind.TRIED,
            "a smoothing spline through the pooled sweeps",
            because="it simply followed the bad tails",
        )

        assert book.about("spline")
        assert not book.about("kriging")

    def test_a_note_about_nothing_is_refused(self, book) -> None:
        with pytest.raises(UnsupportedNote, match="what it is about"):
            book.note(Kind.ASKED, "   ")


class TestThroughTheToolSurface:
    def test_reading_is_read_and_noting_is_write(self, dispatcher) -> None:
        by_name = {tool.name: tool for tool in dispatcher.manifest()}

        assert by_name["ofag.journal"].tier is Tier.READ
        assert by_name["ofag.note"].tier is Tier.WRITE

    def test_the_journal_starts_empty_and_says_so(self, dispatcher) -> None:
        assert dispatcher.call("ofag.journal", {}) == {
            "still_owed": [],
            "lessons_proposed": [],
            "tried_and_dropped": [],
            "ruled_out": [],
            "notes": 0,
        }

    def test_an_ask_noted_through_the_surface_comes_back_owed(self, dispatcher) -> None:
        dispatcher.call("ofag.note", {"kind": "asked", "what": FOUR_ASKS[0]})

        assert dispatcher.call("ofag.journal", {})["still_owed"] == [FOUR_ASKS[0]]

    def test_a_refutation_with_no_place_is_refused_readably(self, dispatcher) -> None:
        with pytest.raises(ToolError, match="does not say where it was measured"):
            dispatcher.call(
                "ofag.note",
                {
                    "kind": "ruled_out",
                    "what": "a hypothesis",
                    "because": "a reason long enough to count",
                },
            )

    def test_an_unknown_kind_says_what_the_kinds_are(self, dispatcher) -> None:
        with pytest.raises(ToolError, match="ruled_out"):
            dispatcher.call("ofag.note", {"kind": "remembered", "what": "something"})

    def test_asking_what_is_known_about_something(self, dispatcher) -> None:
        dispatcher.call(
            "ofag.note",
            {
                "kind": "tried",
                "what": "a smoothing spline through the pooled sweeps",
                "because": "it simply followed the bad tails",
            },
        )

        found = dispatcher.call("ofag.journal", {"about": "spline"})

        assert len(found["notes"]) == 1
        assert found["notes"][0]["kind"] == "tried"
