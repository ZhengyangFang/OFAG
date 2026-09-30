"""What the mechanism reaches, counted on this project's own record."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ofag.agent.lessons import Lesson, load_lessons

__all__ = ["Kind", "Enforcement", "Reach", "ENFORCED", "retrospect", "unenforced"]


class Kind(StrEnum):
    """How a piece of the mechanism refuses."""

    #: Stands between a result and a claim about the ground, and raises.
    GATE = "gate"
    #: Owed before a stage may run, tracked in the ledger.
    OBLIGATION = "obligation"
    #: A model that will not construct, so the bad value never exists.
    SCHEMA = "schema"
    #: Compares an engine with something outside it, before any real run.
    CHECK = "check"


@dataclass(frozen=True)
class Enforcement:
    """One thing in the mechanism, and the procedure it enforces."""

    what: str
    enforces: str
    kind: Kind
    #: What happens when it fires, in the project's own terms.
    note: str
    #: The recorded failures a test *shows* this firing on, by reproducing the defect
    #: and asserting the refusal.
    reaches: tuple[str, ...] = ()


#: Everything in the mechanism that refuses, against the procedure it enforces.
ENFORCED: tuple[Enforcement, ...] = (
    Enforcement(
        what="refuse_out_of_domain, and the declared-ramp floor in tem_import",
        enforces="A1",
        kind=Kind.GATE,
        # Check imports against physical ranges.
        note="a column is checked against what the ground puts the quantity between, "
        "and a declared acquisition parameter against what its own instrument could "
        "have produced, before either is used",
        reaches=("F058", "F005", "F031", "F054"),
    ),
    Enforcement(
        what="refuse_unaccounted and refuse_unreached",
        enforces="A3",
        kind=Kind.GATE,
        note="every parameter a file declares is used -- naming where its value arrives "
        "-- or ignored for a stated reason, and a used one has to have got there",
        reaches=("F017",),
    ),
    Enforcement(
        what="Budget and refuse_repeatability_alone",
        enforces="A4",
        kind=Kind.SCHEMA,
        note="an error bar is carried as repeatability and model error, each with the "
        "measurement behind it, and a chi-squared against the first alone is refused",
        reaches=("F003", "F018"),
    ),
    Enforcement(
        what="difference and refuse_unresolved",
        enforces="A8",
        kind=Kind.GATE,
        note="two statements of one quantity are differenced, and a disagreement is settled "
        "on a criterion about the copies rather than on which was opened first",
        # F037 and not the codebase half.
        reaches=("F037",),
    ),
    Enforcement(
        what="refuse_unsound_picks",
        enforces="A9",
        kind=Kind.GATE,
        note="a keep-mask handed to a traveltime inversion may not hold a picker's default, "
        "a gather whose earliest arrival is not at its shot, or a ray of no length",
        # Classify the gather check under A9.
        reaches=("F043", "F044"),
    ),
    Enforcement(
        what="refuse_unmeasured_terrain",
        enforces="A12",
        kind=Kind.GATE,
        note="a geometry may not be built on ground whose relief and quantum are unstated",
        # F034 and not F035.
        reaches=("F034",),
    ),
    Enforcement(
        what="Screen and refuse_unpredictive",
        enforces="A6",
        kind=Kind.SCHEMA,
        # No threshold, because setting one would need a measured association from a
        # screen that worked and this project does not have one.
        note="an index used as a filter carries its measured association with the thing it "
        "filters for, and is refused where that is indistinguishable from zero on its own "
        "sample",
        reaches=("F016", "F022", "F057"),
    ),
    Enforcement(
        what="Behaviour and refuse_unaccounted_calls, and CoverageConvention in "
        "interpretation_service",
        enforces="A15",
        kind=Kind.SCHEMA,
        # Two pieces and one procedure, like A1's.
        note="what a call does when a parameter is unset, or what it returns, is recorded "
        "against what was run to find out, and a run says which calls it leans on",
        reaches=("F021", "F053"),
    ),
    Enforcement(
        what="Source and refuse_unresolved",
        enforces="A13",
        kind=Kind.SCHEMA,
        # Reaches one of the three.
        note="an identifier is refused until the record says it was followed and what came "
        "back, and a source with none says where it is instead",
        reaches=("F030",),
    ),
    Enforcement(
        what="Borehole.log_kind",
        enforces="A14",
        kind=Kind.SCHEMA,
        # The first thing to reach A14, which is the corpus's widest gap, and it reaches
        # one of the eight.
        note="a log that crosses a unit twice will not construct as a pile, so its "
        "interval tops are never read as points on one surface",
        reaches=("F071",),
    ),
    Enforcement(
        what="refuse_unstated_reach",
        enforces="C1",
        kind=Kind.GATE,
        note="a section read into a model says how deep it resolved and how it knows",
        reaches=("F011",),
    ),
    Enforcement(
        what="classify, and pose refusing what it would not admit",
        enforces="A11",
        kind=Kind.GATE,
        note="a question something cheap would settle is measured instead of asked",
        # F039's own question, posed with F039's own probe, refused because one more
        # inversion would have settled it.
        reaches=("F039",),
    ),
    Enforcement(
        what="GuardedRuns.take, the sampled walk",
        enforces="C4",
        kind=Kind.OBLIGATION,
        note="a run estimated over a minute walks a smaller version first",
    ),
    Enforcement(
        what="Diagnosis",
        enforces="C5",
        kind=Kind.SCHEMA,
        note="a misfit above its bar with nothing ruled out will not construct",
    ),
    Enforcement(
        what="DecisionRecord",
        enforces="",
        kind=Kind.SCHEMA,
        note="a decision without two options, a cost and a reversal will not construct",
    ),
    Enforcement(
        what="ConventionCheck, with fault injection on six of thirteen",
        enforces="A2",
        kind=Kind.CHECK,
        note="an engine's convention is compared with something outside the engine",
        # One, not six.
        reaches=("F001",),
    ),
    Enforcement(
        what="refuse_unfitted",
        enforces="",
        kind=Kind.GATE,
        note="a model may not be built on a run that missed its bar undiagnosed",
    ),
)


@dataclass(frozen=True)
class Reach:
    """One enforcement, and the recorded failures its procedure covers."""

    enforcement: Enforcement
    lessons: tuple[Lesson, ...]

    @property
    def silent(self) -> int:
        """How many of them ran clean and were wrong."""
        return sum(lesson.silent for lesson in self.lessons)

    @property
    def checked(self) -> int:
        """How many also have a test that fails if the defect returns."""
        return sum(lesson.covered_by is not None for lesson in self.lessons)

    @property
    def shown(self) -> tuple[str, ...]:
        """The failures a test reproduces and watches this refuse."""
        return self.enforcement.reaches

    @property
    def summary(self) -> str:
        placed = (
            f"procedure {self.enforcement.enforces}"
            if self.enforcement.enforces
            else "no procedure the corpus uses"
        )
        return (
            f"{self.enforcement.what} ({self.enforcement.kind.value}) enforces {placed}: "
            f"{len(self.lessons)} recorded failures, {self.silent} of them silent, "
            f"{self.checked} with a test, {len(self.shown)} shown refused"
        )


def retrospect(lessons: Sequence[Lesson] | None = None) -> tuple[Reach, ...]:
    """What each piece of the mechanism reaches, in the order it is declared."""
    corpus = tuple(lessons if lessons is not None else load_lessons())
    return tuple(
        Reach(
            enforcement=enforcement,
            lessons=tuple(
                lesson
                for lesson in corpus
                if enforcement.enforces and lesson.procedure == enforcement.enforces
            ),
        )
        for enforcement in ENFORCED
    )


def unenforced(lessons: Sequence[Lesson] | None = None) -> dict[str, tuple[Lesson, ...]]:
    """Procedures the corpus places failures in and nothing enforces."""
    corpus = tuple(lessons if lessons is not None else load_lessons())
    enforced = {item.enforces for item in ENFORCED if item.enforces}
    remaining: dict[str, list[Lesson]] = {}
    for lesson in corpus:
        procedure = lesson.procedure or ""
        if procedure in enforced:
            continue
        remaining.setdefault(procedure, []).append(lesson)
    return {key: tuple(value) for key, value in sorted(remaining.items())}
