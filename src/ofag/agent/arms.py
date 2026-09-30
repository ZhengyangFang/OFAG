"""Scoring a replay answer that did not arrive as a record."""

import re
from dataclasses import dataclass

from ofag.agent.replay import Replay

__all__ = ["Element", "ProseScore", "score_prose", "ELEMENTS"]


@dataclass(frozen=True)
class Element:
    """One thing a decision record would have made mandatory."""

    name: str
    #: Any of these, as a regular expression over the lowered prose.
    pattern: str
    why: str


#: Deliberately generous.
ELEMENTS: tuple[Element, ...] = (
    Element(
        name="an alternative",
        pattern=r"\b(alternativ|other option|instead of|rather than|the other|either\b|"
        r"option (a|b|one|two)|could also)",
        why="a decision record needs two options; one option is a description of what happened",
    ),
    Element(
        name="what the alternative costs",
        pattern=r"\b(cost|would lose|loses|at the price|trade-?off|sacrific|gives up|"
        r"would mean|risk of|penalt)",
        why="an option without a cost is a name",
    ),
    Element(
        name="measured or judged, said",
        pattern=r"\b(cannot be settled|can'?t be settled|no measurement|not measurable|"
        r"judgement|judgment|the data (does not|cannot|can'?t)|nothing in the data|"
        r"settled by|the measurement (that|which)|measured rather than)",
        why="claiming a measurement settled a judgement is F039, and the schema refuses it",
    ),
    Element(
        name="a reversal condition",
        pattern=r"\b(would be wrong if|wrong if|reverse[sd]? if|revisit if|"
        r"if .{0,40}(appear|arrive|turn(s|ed) up|becomes available|is found)|"
        r"unless .{0,40}(appear|shows|turns)|should be revisited|change.{0,20}if)",
        why="the field three of this project's hundred-odd constants carry",
    ),
)


@dataclass(frozen=True)
class ProseScore:
    """A free-text answer against the same rubric the record is graded on."""

    lesson: str
    #: Facts from `must_name` the answer never used.
    missed: tuple[str, ...]
    #: Elements a decision record would have made mandatory and the prose has.
    present: tuple[str, ...]
    #: And the ones it has not.
    absent: tuple[str, ...]

    @property
    def named_everything(self) -> bool:
        return not self.missed

    @property
    def summary(self) -> str:
        return (
            f"{self.lesson}: at least {len(self.present)} of {len(ELEMENTS)} elements present"
            + (f", missing {', '.join(self.absent)}" if self.absent else "")
            + (f"; never used {'; '.join(self.missed)}" if self.missed else "; used every fact")
        )


def score_prose(replay: Replay, answer: str) -> ProseScore:
    """Grade a control answer by the rubric the schema would have enforced."""
    said = answer.lower()
    return ProseScore(
        lesson=replay.lesson,
        missed=tuple(
            " or ".join(group)
            for group in replay.must_name
            if not any(term.lower() in said for term in group)
        ),
        present=tuple(item.name for item in ELEMENTS if re.search(item.pattern, said)),
        absent=tuple(item.name for item in ELEMENTS if not re.search(item.pattern, said)),
    )
