"""What a choice has to carry before it counts as recorded."""

from enum import StrEnum

from pydantic import Field, model_validator

from ofag.core.schemas import StrictModel

__all__ = ["Settlement", "Option", "DecisionRecord"]

#: Below this a reason is a gesture.
_MEANINGFUL = 24


class Settlement(StrEnum):
    """How the choice was closed, which is not the same as who made it."""

    #: The data decided. `measurement` names what was run.
    MEASURED = "measured"
    #: The data could not decide.
    JUDGED = "judged"


class Option(StrictModel):
    """One of the ways this could have gone, and what it would have cost."""

    name: str = Field(min_length=1, max_length=120)
    #: In the project's own units. "loses half the resistivity coverage", "moves the
    #: section up to 2.44 m vertically", "the 5.4 m answer stops being reproducible from
    #: the scripts".
    cost: str = Field(min_length=_MEANINGFUL, max_length=400)


class DecisionRecord(StrictModel):
    """A choice, with everything a later reader needs to revisit it."""

    question: str = Field(min_length=_MEANINGFUL, max_length=300)
    options: tuple[Option, ...]
    #: Must be one of the options' names, so a record cannot quietly choose a fourth
    #: thing nobody weighed.
    chose: str = Field(min_length=1)
    #: The criterion, not the conclusion. "the embedded block steps 2.4 m between
    #: electrodes 4 m apart" is a criterion; "it is better" is not.
    because: str = Field(min_length=_MEANINGFUL, max_length=1200)
    settlement: Settlement
    #: What *settled* it, for a MEASURED settlement.
    measurement: str | None = None
    #: Measurements that were run and did not settle it.
    informed_by: tuple[str, ...] = ()
    #: What would make this wrong. Required.
    reverses_if: str = Field(min_length=_MEANINGFUL, max_length=400)
    #: Where the decision lives: a path, ideally a path and a constant.
    recorded_at: str = Field(min_length=1)
    #: The lesson this decision answers, where there is one.
    lesson: str | None = None

    @model_validator(mode="after")
    def the_record_holds_together(self) -> "DecisionRecord":
        if len(self.options) < 2:
            raise ValueError(
                "a decision needs at least two options: one option is a description of what "
                "happened, and the thing that goes unrecorded is the alternative"
            )
        names = [option.name for option in self.options]
        if len(set(names)) != len(names):
            raise ValueError(f"two options share a name: {names}")
        if self.chose not in names:
            raise ValueError(f"chose {self.chose!r}, which is not one of {names}")
        if (self.settlement is Settlement.MEASURED) != (self.measurement is not None):
            raise ValueError(
                "a measured decision names what settled it and a judged one does not -- a "
                "measurement a judgement consulted goes in informed_by: settlement is "
                f"{self.settlement.value} and measurement is "
                f"{'set' if self.measurement else 'unset'}"
            )
        # A reversal condition that restates the reason is not a reversal condition.
        if self.reverses_if.strip().lower() in self.because.strip().lower():
            raise ValueError(
                "reverses_if repeats because: it has to name a future fact that would make "
                "this choice wrong, not the reason it was right"
            )
        return self

    def as_comment(self, width: int = 76) -> str:
        """The record as the `#:` block that goes above the constant."""
        import textwrap

        chosen = next(option for option in self.options if option.name == self.chose)
        others = [option for option in self.options if option.name != self.chose]
        paragraphs = [
            self.question,
            f"{self.chose}. {self.because}",
            # "Chosen over" rather than "against ... would ...", because a cost is
            # written as a clause as often as as a verb phrase and the verb phrase was
            # the only one that came out grammatical.
            "Chosen over: "
            + "; ".join(f"{option.name} -- {option.cost}" for option in others)
            + f". This one -- {chosen.cost}.",
            (
                f"Settled by {self.measurement}."
                if self.measurement
                else (
                    "The data does not settle this: " + "; ".join(self.informed_by) + "."
                    if self.informed_by
                    else "The data does not settle this, and nothing was run to try."
                )
            ),
            f"This is wrong if {self.reverses_if}",
        ]
        lines: list[str] = []
        for index, paragraph in enumerate(paragraphs):
            if index:
                lines.append("#:")
            lines += textwrap.wrap(
                paragraph, width=width, initial_indent="#: ", subsequent_indent="#: "
            )
        return chr(10).join(lines)
