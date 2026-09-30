"""What has to happen before a question may be put to a person."""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field

from ofag.agent.decisions import DecisionRecord, Option, Settlement
from ofag.core.schemas import StrictModel

__all__ = [
    "MEASURE_RATHER_THAN_ASK_SECONDS",
    "Next",
    "Finding",
    "Probe",
    "ProbeCost",
    "Question",
    "Classified",
    "Settled",
    "Posed",
    "AskedWhatCouldBeMeasured",
    "classify",
    "settle",
    "pose",
    "AlreadyRecorded",
    "place",
]

#: Seconds below which a measurement is run rather than a question asked.
MEASURE_RATHER_THAN_ASK_SECONDS = 120.0


class Next(StrEnum):
    """What to do with a question, in the order the options are tried."""

    #: Something cheap separates the options. Run it.
    MEASURE = "measure"
    #: Something separates them and its cost is a guess.
    TIME_IT_FIRST = "time it first"
    #: Nothing separates them, or what would is genuinely expensive and a clock has said
    #: so.
    ASK = "ask"


@dataclass(frozen=True)
class Finding:
    """What a probe came back with."""

    #: The option the measurement favours, or empty if it did not separate them.
    favours: str
    #: The numbers, in the project's own units.
    result: str


@dataclass(frozen=True)
class Probe:
    """Something runnable that would separate a question's options."""

    #: What would be run, in the project's own terms. "invert the profile flat and at
    #: elevation and compare chi-squared", not "test it".
    what: str
    seconds: float
    #: Where `seconds` came from.
    timing: Literal["measured", "estimated"]
    run: Callable[[], Finding] = field(repr=False)

    @property
    def cheap(self) -> bool:
        return self.seconds <= MEASURE_RATHER_THAN_ASK_SECONDS


class ProbeCost(StrictModel):
    """A probe as it crosses a boundary: what it is and what it costs."""

    what: str = Field(min_length=8, max_length=300)
    seconds: float = Field(ge=0)
    timing: Literal["measured", "estimated"]

    def described(self) -> Probe:
        """The probe, with a `run` that says why it cannot be run here."""

        def run() -> Finding:
            raise RuntimeError(f"{self.what!r} was described, not handed over; run it yourself")

        return Probe(what=self.what, seconds=self.seconds, timing=self.timing, run=run)


@dataclass(frozen=True)
class Question:
    """Something that has come up, before anything has been done about it."""

    question: str
    options: tuple[Option, ...]
    #: Where the answer will live, as the audit reads it: a path and the constant the
    #: `#:` block goes above.
    at: str
    #: Everything runnable that bears on it, cheapest first.
    probes: tuple[Probe, ...] = ()

    def __post_init__(self) -> None:
        if len(self.options) < 2:
            raise ValueError(
                "a question needs at least two options: one option is a description of what is "
                "about to happen, and the alternative is the thing that goes unrecorded"
            )


@dataclass(frozen=True)
class Classified:
    """What to do with a question, and the reason."""

    next: Next
    because: str
    probe: Probe | None = None


@dataclass(frozen=True)
class Settled:
    """A question a measurement closed."""

    record: DecisionRecord
    finding: Finding


class AskedWhatCouldBeMeasured(RuntimeError):
    """A question was put to a person that something cheap would have closed."""


def classify(probes: Sequence[Probe]) -> Classified:
    """Whether to measure, to time a measurement first, or to ask."""
    if not probes:
        return Classified(Next.ASK, "nothing runnable was offered that separates the options")

    ordered = sorted(probes, key=lambda probe: probe.seconds)
    for probe in ordered:
        if probe.cheap and probe.timing == "measured":
            return Classified(
                Next.MEASURE,
                f"{probe.what} takes {probe.seconds:.0f} s on a clock, under the "
                f"{MEASURE_RATHER_THAN_ASK_SECONDS:.0f} s a question costs",
                probe,
            )
    for probe in ordered:
        if probe.cheap:
            return Classified(
                Next.MEASURE,
                f"{probe.what} is estimated at {probe.seconds:.0f} s, under the "
                f"{MEASURE_RATHER_THAN_ASK_SECONDS:.0f} s a question costs even if the "
                "estimate is optimistic",
                probe,
            )
    cheapest = ordered[0]
    if cheapest.timing == "estimated":
        return Classified(
            Next.TIME_IT_FIRST,
            f"{cheapest.what} is estimated at {cheapest.seconds:.0f} s and nothing has timed "
            "it; an estimate is not evidence that a measurement is expensive (F055)",
            cheapest,
        )
    return Classified(
        Next.ASK,
        f"{cheapest.what} is the cheapest thing that would separate them and a clock puts it "
        f"at {cheapest.seconds:.0f} s, over the {MEASURE_RATHER_THAN_ASK_SECONDS:.0f} s a "
        "question costs",
        cheapest,
    )


def settle(question: Question, *, reverses_if: str, lesson: str | None = None) -> Settled | None:
    """Run the cheapest probe and record what it found."""
    verdict = classify(question.probes)
    if verdict.next is not Next.MEASURE or verdict.probe is None:
        raise ValueError(f"nothing to run: {verdict.because}")

    finding = verdict.probe.run()
    if not finding.favours:
        return None

    names = [option.name for option in question.options]
    if finding.favours not in names:
        raise ValueError(f"the probe favours {finding.favours!r}, which is not one of {names}")
    return Settled(
        DecisionRecord(
            question=question.question,
            options=question.options,
            chose=finding.favours,
            because=finding.result,
            settlement=Settlement.MEASURED,
            measurement=f"{verdict.probe.what}: {finding.result}",
            reverses_if=reverses_if,
            recorded_at=question.at,
            lesson=lesson,
        ),
        finding,
    )


@dataclass(frozen=True)
class Posed:
    """A question laid out for a person, with what was done before asking."""

    question: Question
    recommend: str
    because: str
    reverses_if: str
    #: Why this reached a person.
    why_not_measured: str
    #: What was run and did not separate the options, if anything was.
    informed_by: tuple[str, ...] = ()

    def as_prompt(self) -> str:
        """What the person is shown."""
        lines = [self.question.question, ""]
        for option in self.question.options:
            mark = "->" if option.name == self.recommend else "  "
            lines.append(f" {mark} {option.name}")
            lines.append(f"      {option.cost}")
        lines += ["", f"Recommended: {self.recommend}. {self.because}"]
        if self.informed_by:
            lines.append(
                "Measured first, and it did not separate them: " + "; ".join(self.informed_by)
            )
        lines += [
            f"Not measured because {self.why_not_measured}",
            f"Reverses if {self.reverses_if}",
            "",
            f"The answer will be written at {self.question.at}",
        ]
        return "\n".join(lines)

    def accept(self, chose: str, *, because: str | None = None) -> DecisionRecord:
        """The person's answer, as the record that goes into the code."""
        return DecisionRecord(
            question=self.question.question,
            options=self.question.options,
            chose=chose,
            because=because or self.because,
            settlement=Settlement.JUDGED,
            informed_by=self.informed_by,
            reverses_if=self.reverses_if,
            recorded_at=self.question.at,
        )


def pose(
    question: Question,
    *,
    recommend: str,
    because: str,
    reverses_if: str,
    informed_by: tuple[str, ...] = (),
) -> Posed:
    """Lay a question out for a person, or refuse to."""
    verdict = classify(question.probes)
    if verdict.next is not Next.ASK:
        raise AskedWhatCouldBeMeasured(
            f"{question.question!r} is not a question yet -- {verdict.next.value}: "
            f"{verdict.because}"
        )
    names = [option.name for option in question.options]
    if recommend not in names:
        raise ValueError(f"recommended {recommend!r}, which is not one of {names}")
    return Posed(
        question=question,
        recommend=recommend,
        because=because,
        reverses_if=reverses_if,
        why_not_measured=verdict.because,
        informed_by=informed_by,
    )


class AlreadyRecorded(RuntimeError):
    """The constant already carries a `#:` block, and this would erase it."""


def place(record: DecisionRecord, *, root: Path, apply: bool = False) -> str:
    """Put the record above the constant it belongs to, and return the file."""
    location, _, name = record.recorded_at.partition("::")
    if not name:
        raise ValueError(
            f"recorded_at is {record.recorded_at!r}: it has to name a file and a constant, "
            "as path/to/file.py::CONSTANT_NAME"
        )
    path = root / location
    text = path.read_text(encoding="utf-8")

    anchor = re.compile(rf"^(?:{re.escape(name)}\s*[:=]|def {re.escape(name)}\s*\()", re.M)
    match = anchor.search(text)
    if match is None:
        raise ValueError(f"{location} has no constant or function called {name}")
    if re.search(r"(?:^#:[^\n]*\n)+\Z", text[: match.start()], re.M):
        raise AlreadyRecorded(
            f"{name} in {location} already has a `#:` block. Read it before replacing it: "
            "two decisions about one constant means one of them was reversed, and a reversal "
            "is a thing to write down rather than to overwrite."
        )
    placed = text[: match.start()] + record.as_comment() + "\n" + text[match.start() :]
    if apply:
        path.write_text(placed, encoding="utf-8")
    return placed
