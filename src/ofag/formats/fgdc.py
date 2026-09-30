"""Read what a data release says about its own data, before inverting it."""

import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Statement", "DeclaredUnit", "ReleaseNotes", "read_release_notes"]

#: The narrative fields worth reading, and what each is for in the standard.
_NARRATIVE = {
    "attraccr": "attribute accuracy",
    "logic": "logical consistency",
    "complete": "completeness",
    "horizpar": "horizontal positional accuracy",
    "vertaccr": "vertical positional accuracy",
    "procdesc": "process step",
    "supplinf": "supplemental information",
    "abstract": "abstract",
    "purpose": "purpose",
}

#: Terms that mark a sentence as the author conceding something.
_ADMISSION_TERMS = (
    "velocity inversion",
    "proprietary",
    "equivalence",
    "discrepanc",
    "uncertain",
    "not corrected",
    "uncorrected",
    "approximate",
    "estimated",
    "assumed",
    "may be subject",
    "erroneous",
    "limitation",
    "not available",
    "unknown",
    "missing",
    "caution",
    "should not",
)

#: Terms that mark a sentence as a claim this project can test.
_CLAIM_TERMS = (
    "were checked",
    "was checked",
    "were verified",
    "no outlier",
    "were edited",
    "error free",
    "error-free",
    "high-quality",
    "high quality",
    "excellent quality",
    "good quality",
    "acceptable",
    "within",
    "confirmed",
    "corroborated",
)


@dataclass(frozen=True)
class Statement:
    """One sentence from the record, and the term that surfaced it."""

    #: The FGDC element it came from, as the standard names it.
    field: str
    #: What that element is for, in words.
    about: str
    sentence: str
    #: The term matched.
    term: str


@dataclass(frozen=True)
class DeclaredUnit:
    """A column, and the unit the record states for it."""

    attribute: str
    unit: str
    definition: str

    @property
    def is_imperial(self) -> bool:
        """Whether the declared unit is one a reader is likely to assume away."""
        return bool(re.search(r"\b(feet|foot|ft|inch|mile|pound|gallon)\b", self.unit, re.I))


@dataclass(frozen=True)
class ReleaseNotes:
    """What one release says about itself."""

    title: str
    #: Sentences conceding a limit. Facts about the data.
    admissions: tuple[Statement, ...]
    #: Sentences claiming something was checked. Hypotheses to test.
    claims: tuple[Statement, ...]
    #: Every column that declares a unit.
    units: tuple[DeclaredUnit, ...]
    #: The narrative fields entire, for a reader who wants the context a sentence was
    #: pulled out of.
    narrative: dict[str, tuple[str, ...]]
    source_path: Path

    @property
    def imperial_units(self) -> tuple[DeclaredUnit, ...]:
        return tuple(unit for unit in self.units if unit.is_imperial)


def read_release_notes(path: Path) -> ReleaseNotes:
    """Parse one FGDC metadata record."""
    try:
        tree = ElementTree.parse(path)
    except ElementTree.ParseError as error:
        raise ValueError(f"{path.name} is not parsable XML: {error}") from error

    narrative: dict[str, tuple[str, ...]] = {}
    admissions: list[Statement] = []
    claims: list[Statement] = []
    for field, about in _NARRATIVE.items():
        texts = tuple(
            _flatten(element.text) for element in tree.iter(field) if (element.text or "").strip()
        )
        if not texts:
            continue
        narrative[field] = texts
        for text in texts:
            for sentence in _sentences(text):
                lowered = sentence.lower()
                for term in _ADMISSION_TERMS:
                    if term in lowered:
                        admissions.append(Statement(field, about, sentence, term))
                        break
                else:
                    for term in _CLAIM_TERMS:
                        if term in lowered:
                            claims.append(Statement(field, about, sentence, term))
                            break

    units = tuple(
        DeclaredUnit(
            attribute=_flatten(attribute.findtext("attrlabl", "")),
            unit=_flatten(unit),
            definition=_flatten(attribute.findtext("attrdef", "")),
        )
        for attribute in tree.iter("attr")
        for unit in [_first_unit(attribute)]
        if unit
    )
    return ReleaseNotes(
        title=_flatten(tree.findtext(".//title", path.stem)),
        admissions=tuple(admissions),
        claims=tuple(claims),
        units=units,
        narrative=narrative,
        source_path=Path(path),
    )


def _first_unit(attribute: ElementTree.Element) -> str:
    for declared in attribute.iter("attrunit"):
        if (declared.text or "").strip():
            return declared.text or ""
    return ""


def _flatten(text: str | None) -> str:
    return " ".join((text or "").split())


def _sentences(text: str) -> list[str]:
    """Split a narrative field into sentences, loosely."""
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(])", text)
    return [part.strip() for part in parts if len(part.strip()) > 20]
