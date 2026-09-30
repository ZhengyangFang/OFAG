"""A3: a file's acquisition parameters, each used or refused by name."""

import pytest
from pydantic import ValidationError

from ofag.agent.declared import (
    Accounted,
    Disposition,
    UnaccountedParameter,
    UnreachedParameter,
    refuse_unaccounted,
    refuse_unreached,
)

DECLARED = ("/RAMP_TIME", "/TIME_DELAY", "/FIELD_SHIFT_FACTOR", "/CURRENT")

ACCOUNTED = (
    Accounted(
        parameter="/RAMP_TIME",
        disposition=Disposition.USED,
        arrives_at="physics.waveform.ramp_time_s",
    ),
    Accounted(
        parameter="/TIME_DELAY",
        disposition=Disposition.USED,
        arrives_at="physics.waveform.time_delay_s",
    ),
    Accounted(
        parameter="/FIELD_SHIFT_FACTOR",
        disposition=Disposition.IGNORED,
        because="the contractor states it was already applied to the delivered curve, and "
        "applying it twice is a factor nothing downstream would question",
    ),
    Accounted(
        parameter="/CURRENT",
        disposition=Disposition.USED,
        arrives_at="dataset.transmitter_current_a",
    ),
)

#: The specification as it was: the waveform exists and is empty.
BEFORE = {"physics": {"waveform": {}}, "dataset": {"transmitter_current_a": 9.5}}
#: And after the three were wired through.
AFTER = {
    "physics": {"waveform": {"ramp_time_s": 3e-6, "time_delay_s": 0.0}},
    "dataset": {"transmitter_current_a": 9.5},
}


class TestAccountingForThem:
    def test_a_parameter_nothing_mentions_is_refused(self) -> None:
        with pytest.raises(UnaccountedParameter, match="/TIME_DELAY, /FIELD_SHIFT_FACTOR"):
            refuse_unaccounted(DECLARED, ACCOUNTED[:1] + ACCOUNTED[3:])

    def test_the_accounting_comes_back_in_the_file_s_order(self) -> None:
        """So a caller prints what it did with each, rather than learning only that nothing
        was missed."""
        got = refuse_unaccounted(DECLARED, reversed(ACCOUNTED))

        assert tuple(item.parameter for item in got) == DECLARED

    def test_accounting_for_something_the_file_does_not_declare_is_refused(self) -> None:
        """An accounting that covers parameters the file has not got is one nobody compared
        with the file."""
        invented = Accounted(
            parameter="/STACK_COUNT",
            disposition=Disposition.IGNORED,
            because="not something this inversion has any use for whatsoever",
        )

        with pytest.raises(UnaccountedParameter, match="does not declare"):
            refuse_unaccounted(DECLARED, (*ACCOUNTED, invented))


class TestReachingTheThingThatNeededIt:
    def test_a_parameter_read_and_never_reached_is_caught(self) -> None:
        """F017. Both waveform terms were read somewhere and the specification the inversion
        runs on has neither."""
        with pytest.raises(UnreachedParameter, match="/RAMP_TIME at physics.waveform.ramp_time_s"):
            refuse_unreached(ACCOUNTED, BEFORE)

    def test_once_they_arrive_the_paths_come_back(self) -> None:
        assert refuse_unreached(ACCOUNTED, AFTER) == (
            "physics.waveform.ramp_time_s",
            "physics.waveform.time_delay_s",
            "dataset.transmitter_current_a",
        )

    def test_an_ignored_parameter_is_not_looked_for(self) -> None:
        """It was left out on purpose; demanding it arrive somewhere would make the only
        honest disposition impossible to state."""
        assert "/FIELD_SHIFT_FACTOR" not in " ".join(refuse_unreached(ACCOUNTED, AFTER))

    def test_a_path_that_runs_through_a_leaf_does_not_pass(self) -> None:
        """`physics.waveform` holding a number rather than a mapping means the value is not
        there, and following the path must say so rather than raise something a caller
        reads as a bug."""
        shallow = {"physics": {"waveform": 3e-6}, "dataset": {"transmitter_current_a": 9.5}}

        with pytest.raises(UnreachedParameter):
            refuse_unreached(ACCOUNTED, shallow)


class TestWhatADispositionOwes:
    def test_used_has_to_name_where_it_arrives(self) -> None:
        """"We read it" was true of `/RAMP_TIME` and useless."""
        with pytest.raises(ValidationError, match="names nowhere it arrives"):
            Accounted(parameter="/RAMP_TIME", disposition=Disposition.USED)

    def test_ignored_has_to_say_what_makes_it_safe(self) -> None:
        with pytest.raises(ValidationError, match="say what makes it safe"):
            Accounted(
                parameter="/FIELD_SHIFT_FACTOR",
                disposition=Disposition.IGNORED,
                because="not needed",
            )

    def test_a_parameter_cannot_be_used_and_excused_at_once(self) -> None:
        with pytest.raises(ValidationError, match="carries a reason for being ignored"):
            Accounted(
                parameter="/RAMP_TIME",
                disposition=Disposition.USED,
                arrives_at="physics.waveform.ramp_time_s",
                because="also we did not really need it after all, on reflection",
            )
