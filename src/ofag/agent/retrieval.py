"""Retrieval over what this project has written down, for an agent's brief."""

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from ofag.agent.lessons import DEFAULT_CORPUS, METHOD_NAMES, load_lessons
from ofag.agent.resources import DOCS_ROOT

__all__ = [
    "Kind",
    "Passage",
    "Hit",
    "Retriever",
    "Index",
    "METHODS",
    "PROCEDURE",
    "WRITE_UPS",
    "KNOWLEDGE",
    "passages_from_markdown",
    "passages_from_lessons",
    "passages_from_knowledge",
    "default_index",
]

#: The procedure every stage filter refers to.
PROCEDURE = DOCS_ROOT / "agent_validation_and_debugging.md"

#: Current case summaries and the detailed accounts behind procedure steps.
WRITE_UPS: tuple[Path, ...] = tuple(
    DOCS_ROOT / name
    for name in (
        "case1_forge.md",
        "case2_cedar_rapids.md",
        "case3_llano.md",
        "development/case1_forge_history.md",
        "development/case2_cedar_rapids_history.md",
        "development/case3_llano_history.md",
        "development/stillwater.md",
        "interpretation.md",
        "unit_policy.md",
        "tdem1d_configuration.md",
        "development/seismic_engine_selection.md",
        "development/seismic_field_data.md",
        "development/plugin_contract_evolution.md",
        "architecture.md",
    )
)

#: Published practice, one file per method, at the received tier.
KNOWLEDGE = DOCS_ROOT / "knowledge"

#: The words that say a passage is about a method.
METHODS: dict[str, tuple[str, ...]] = {
    "tdem": ("tdem", "tem", "transient", "ramp", "sounding", "soundings", "skytem"),
    # Airborne here means frequency-domain: this project's one airborne EM survey is
    # Cedar Rapids' EM1DFM. "apparent" is not an ERT cue -- the seismic refraction
    # write-ups use it for velocity.
    "fdem": ("fdem", "aem", "airborne", "coplanar", "coaxial"),
    "ert": ("ert", "electrode", "electrodes", "pygimli", "resistivity"),
    "mt": ("magnetotelluric", "magnetotellurics", "edi", "impedance", "tipper"),
    "gravity": ("gravity", "bouguer", "density", "densities"),
    "magnetic": ("magnetic", "aeromagnetic", "susceptibility", "rtp"),
    "seismic": ("seismic", "segy", "traveltime", "reflection", "refraction"),
    "boreholes": ("borehole", "boreholes", "drill", "cuttings", "lithology", "lithological"),
}

if set(METHODS) != set(METHOD_NAMES):  # pragma: no cover - a module-load invariant
    raise RuntimeError("retrieval.METHODS and lessons.METHOD_NAMES name different methods")

_PROCEDURE_STEP = re.compile(r"^([ABC]\d{1,2})\.\s")
_LESSON_ID = re.compile(r"\b(F\d{3})\b")
_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
_KNOWLEDGE_META = re.compile(
    r"^Stage:\s*(?P<stage>[ABC])\s*\|\s*Step:\s*(?P<step>[ABC]\d{1,2}|none)\s*\|"
    r"\s*Methods:\s*(?P<methods>[a-z, ]*?)\s*$"
)
_DOI = re.compile(r"\bdoi:\s*(10\.\d{4,9}/\S+)", re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+(?:[.'][a-z0-9]+)*")
_STOP = frozenset(
    "a an and are as at be but by for from has have if in into is it its not of on or "
    "that the their them then there these this those to was were what when where which "
    "who will with would can does do so than no".split()
)
#: A passage shorter than this under its heading is a signpost, not content.
_SHORTEST = 60


class Kind(StrEnum):
    """What a passage is, which decides what it may be used for."""

    #: A step of the procedure: what to do.
    PROCEDURE = "procedure"
    #: One recorded failure: what went wrong when it was not done.
    LESSON = "lesson"
    #: A section of a write-up: how it went in a real case.
    WRITE_UP = "write_up"
    #: A practice the literature states and this project has not measured: it may
    #: propose a check, never gate a run.
    RECEIVED = "received"


@dataclass(frozen=True)
class Passage:
    """One piece of a document, quoted, with what it is about."""

    id: str
    kind: Kind
    #: Relative to the repository, so a citation works on any checkout.
    source: str
    heading: str
    text: str
    #: A, B or C, or None for a passage that belongs to no single stage.
    stage: str | None = None
    #: The procedure step this is, or is covered by.
    procedure: str | None = None
    lessons: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()
    #: Where a received passage's claim is published, so it can be followed.
    dois: tuple[str, ...] = ()

    @property
    def cited_as(self) -> str:
        """Where a reader goes to check a claim made from this."""
        return f"{self.source} -- {self.heading}"


@dataclass(frozen=True)
class Hit:
    passage: Passage
    score: float
    #: The query terms this passage contained, so a reader can see why it was chosen
    #: rather than trusting a number.
    matched: tuple[str, ...] = ()


class Retriever(Protocol):
    """What the roles and the tools need from an index, and nothing more."""

    def search(
        self,
        query: str = "",
        *,
        stages: Sequence[str] = (),
        procedure: str | None = None,
        method: str | None = None,
        kinds: Sequence[Kind] = (),
        k: int = 6,
    ) -> tuple[Hit, ...]: ...


def tokens(text: str) -> list[str]:
    """Lower-cased words, stop words dropped, a plural reduced to its singular."""
    out: list[str] = []
    for word in _TOKEN.findall(text.lower()):
        if word.endswith("'s"):
            word = word[:-2]
        if word in _STOP:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _methods_in(words: Iterable[str]) -> tuple[str, ...]:
    present = set(words)
    return tuple(
        method for method, cues in METHODS.items() if present.intersection(tokens(" ".join(cues)))
    )


def _relative(path: Path) -> str:
    try:
        return "docs/" + path.resolve().relative_to(DOCS_ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def passages_from_markdown(path: Path, *, procedure_document: bool = False) -> list[Passage]:
    """Cut a document at its headings, one passage per section."""
    source = _relative(path)
    stem = path.stem
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: list[tuple[str, str | None, list[str]]] = []
    stage: str | None = None
    heading = stem
    body: list[str] = []
    for line in lines:
        match = _HEADING.match(line)
        if match is None:
            body.append(line)
            continue
        sections.append((heading, stage, body))
        level, heading = len(match.group(1)), match.group(2)
        body = []
        if procedure_document and level == 2:
            letter = heading[:1]
            stage = letter if heading[1:2] == "." and letter in "ABC" else None
    sections.append((heading, stage, body))

    passages: list[Passage] = []
    used: Counter[str] = Counter()
    for heading, section_stage, section_body in sections:
        text = "\n".join(section_body).strip()
        if len(text) < _SHORTEST:
            continue
        step = _PROCEDURE_STEP.match(heading) if procedure_document else None
        words = tokens(f"{heading} {text}")
        slug = "-".join(tokens(heading)[:6]) or "section"
        used[slug] += 1
        if used[slug] > 1:
            slug = f"{slug}-{used[slug]}"
        passages.append(
            Passage(
                id=f"procedure:{step.group(1)}" if step else f"{stem}#{slug}",
                kind=Kind.PROCEDURE if step else Kind.WRITE_UP,
                source=source,
                heading=heading,
                text=text,
                stage=step.group(1)[0] if step else section_stage,
                procedure=step.group(1) if step else None,
                # A step's heading names the step; only its text cites lessons.
                lessons=tuple(
                    dict.fromkeys(_LESSON_ID.findall(text if step else f"{heading} {text}"))
                ),
                methods=_methods_in(words),
            )
        )
    return passages


def passages_from_lessons(path: Path | None = None) -> list[Passage]:
    """One passage per recorded failure: its rule and the sentence it came from."""
    source = _relative(path or DEFAULT_CORPUS)
    passages = []
    for lesson in load_lessons(path):
        text = f"{lesson.title}\n\n{lesson.evidence}"
        # The old identifier is in the text so a query that cites it -- from a paper or
        # a note written before the renumbering -- still finds it.
        formerly = f" (formerly {lesson.former_id})" if lesson.former_id else ""
        passages.append(
            Passage(
                id=f"lesson:{lesson.id}",
                kind=Kind.LESSON,
                source=source,
                heading=f"{lesson.id}. {lesson.title}{formerly}",
                text=text
                + (
                    "\n\n(ran clean: nothing raised and the answer was wrong)"
                    if lesson.silent
                    else ""
                ),
                stage=lesson.procedure[0] if lesson.procedure else None,
                procedure=lesson.procedure,
                lessons=(lesson.id,),
                # Stated in the corpus, so not guessed from the words here.
                methods=lesson.methods,
            )
        )
    return passages


def _doi_as_written(match: str) -> str:
    """A DOI without the punctuation of the sentence it sits in."""
    doi = match.rstrip(".,;:*_]>")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1].rstrip(".,;:*_]>")
    return doi


def passages_from_knowledge(path: Path) -> list[Passage]:
    """One passage per `##` section of a received-practice file."""
    from ofag.agent.lessons import METHOD_NAMES

    source = _relative(path)
    sections: list[tuple[str, list[str]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _HEADING.match(line)
        if match is not None and len(match.group(1)) == 2:
            sections.append((match.group(2), []))
        elif match is not None and len(match.group(1)) == 3:
            raise ValueError(f"{source}: use only ## sections, not '{line.strip()}'")
        elif sections:
            sections[-1][1].append(line)

    passages: list[Passage] = []
    used: Counter[str] = Counter()
    for heading, body in sections:
        lines = [line for line in body if line.strip()]
        meta = _KNOWLEDGE_META.match(lines[0].strip()) if lines else None
        if meta is None:
            raise ValueError(
                f"{source} -- {heading}: the line under the heading has to be "
                "'Stage: A | Step: A7 | Methods: mt'"
            )
        stage, step = meta["stage"], meta["step"]
        if step != "none" and step[0] != stage:
            raise ValueError(f"{source} -- {heading}: step {step} is not in stage {stage}")
        methods = tuple(m.strip() for m in meta["methods"].split(",") if m.strip())
        unknown = sorted(set(methods) - set(METHOD_NAMES))
        if unknown:
            raise ValueError(f"{source} -- {heading}: no method {', '.join(unknown)}")
        text = "\n".join(body).strip()
        text = text[text.index("\n") + 1 :].strip() if "\n" in text else ""
        dois = tuple(dict.fromkeys(_doi_as_written(d) for d in _DOI.findall(text)))
        if not dois:
            raise ValueError(f"{source} -- {heading}: a received section cites a DOI")
        slug = "-".join(tokens(heading)[:6]) or "section"
        used[slug] += 1
        if used[slug] > 1:
            slug = f"{slug}-{used[slug]}"
        passages.append(
            Passage(
                id=f"received:{path.stem}#{slug}",
                kind=Kind.RECEIVED,
                source=source,
                heading=heading,
                text=text,
                stage=stage,
                procedure=None if step == "none" else step,
                methods=methods,
                dois=dois,
            )
        )
    return passages


@dataclass(frozen=True)
class Index:
    """BM25 over passages, behind the structured filters."""

    passages: tuple[Passage, ...]
    k1: float = 1.5
    b: float = 0.75
    _terms: tuple[Counter[str], ...] = field(init=False, repr=False)
    _document_frequency: Counter[str] = field(init=False, repr=False)
    _mean_length: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        ids = [p.id for p in self.passages]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ValueError(f"passage ids must be unique; repeated: {repeated}")
        terms = tuple(Counter(tokens(f"{p.heading} {p.text}")) for p in self.passages)
        frequency: Counter[str] = Counter()
        for counted in terms:
            frequency.update(counted.keys())
        object.__setattr__(self, "_terms", terms)
        object.__setattr__(self, "_document_frequency", frequency)
        lengths = [sum(c.values()) for c in terms]
        object.__setattr__(self, "_mean_length", sum(lengths) / max(len(lengths), 1))

    def get(self, passage_id: str) -> Passage:
        for passage in self.passages:
            if passage.id == passage_id:
                return passage
        raise KeyError(f"no passage {passage_id!r}")

    def search(
        self,
        query: str = "",
        *,
        stages: Sequence[str] = (),
        procedure: str | None = None,
        method: str | None = None,
        kinds: Sequence[Kind] = (),
        k: int = 6,
    ) -> tuple[Hit, ...]:
        """The passages that bear on this, best first."""
        if method is not None and method not in METHODS:
            raise ValueError(f"no method {method!r}; the methods are {', '.join(METHODS)}")
        if k < 1:
            raise ValueError("k has to be at least one")
        covered = self._covered_by(procedure)
        candidates = [
            (position, passage)
            for position, passage in enumerate(self.passages)
            if (not kinds or passage.kind in kinds)
            and (not stages or passage.stage is None or passage.stage in stages)
            and (
                procedure is None
                or passage.procedure == procedure
                or (
                    passage.kind is not Kind.PROCEDURE
                    and bool(covered.intersection(passage.lessons))
                )
            )
        ]
        wanted = [t for t in dict.fromkeys(tokens(query))]
        if not wanted:
            if method is not None:
                candidates = [(i, p) for i, p in candidates if method in p.methods]
            ordered = sorted(candidates, key=lambda item: _structured_order(item[1], procedure))
            return tuple(Hit(passage=p, score=0.0) for _, p in ordered[:k])

        scored = []
        for position, passage in candidates:
            score, matched = self._score(position, wanted)
            if score <= 0.0:
                continue
            if method is not None and method in passage.methods:
                score *= 1.5
            scored.append(Hit(passage=passage, score=score, matched=matched))
        scored.sort(key=lambda hit: (-hit.score, hit.passage.id))
        return tuple(scored[:k])

    def _covered_by(self, procedure: str | None) -> set[str]:
        """The lessons a step answers for: those placed at it, and those it cites."""
        if procedure is None:
            return set()
        placed = {
            p.lessons[0]
            for p in self.passages
            if p.kind is Kind.LESSON and p.procedure == procedure and p.lessons
        }
        cited = {
            lesson
            for p in self.passages
            if p.kind is Kind.PROCEDURE and p.procedure == procedure
            for lesson in p.lessons
        }
        return placed | cited

    def _score(self, position: int, wanted: list[str]) -> tuple[float, tuple[str, ...]]:
        counted = self._terms[position]
        length = sum(counted.values())
        total = len(self.passages)
        score = 0.0
        matched = []
        for term in wanted:
            frequency = counted.get(term, 0)
            if not frequency:
                continue
            matched.append(term)
            df = self._document_frequency[term]
            idf = math.log((total - df + 0.5) / (df + 0.5) + 1.0)
            norm = frequency + self.k1 * (1 - self.b + self.b * length / self._mean_length)
            score += idf * frequency * (self.k1 + 1) / norm
        return score, tuple(matched)


def _structured_order(passage: Passage, procedure: str | None) -> tuple[int, int, str]:
    kind_rank = {Kind.PROCEDURE: 0, Kind.LESSON: 1, Kind.WRITE_UP: 2, Kind.RECEIVED: 3}[
        passage.kind
    ]
    if procedure is not None and passage.procedure == procedure and passage.kind is Kind.PROCEDURE:
        kind_rank = -1
    number = 0
    if passage.kind is Kind.LESSON and passage.lessons:
        digits = passage.lessons[0][1:]
        number = int(digits) if digits.isdigit() else 0
    return (kind_rank, number, passage.id)


@lru_cache(maxsize=1)
def default_index() -> Index:
    """The project's own corpus -- the procedure, the lessons and the write-ups -- and the
    received practice beside it."""
    passages = passages_from_markdown(PROCEDURE, procedure_document=True)
    passages += passages_from_lessons()
    for path in WRITE_UPS:
        if path.is_file():
            passages += passages_from_markdown(path)
    for path in sorted(KNOWLEDGE.glob("*.md")) if KNOWLEDGE.is_dir() else ():
        if path.name != "README.md":
            passages += passages_from_knowledge(path)
    return Index(tuple(passages))
