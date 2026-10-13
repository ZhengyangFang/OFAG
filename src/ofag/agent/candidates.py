"""A lesson an agent proposes, held until a person accepts it into the corpus."""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ofag.agent.lessons import METHOD_NAMES

__all__ = ["Candidate", "Candidates", "UnsupportedCandidate", "candidates_for", "FILENAME"]

FILENAME = "candidate_lessons.jsonl"

#: Below these a field is a gesture. The same bars the ledger and the journal use.
_SHORTEST_TITLE = 12
_SHORTEST_EVIDENCE = 20


class UnsupportedCandidate(ValueError):
    """A proposal that does not carry what a lesson needs."""


@dataclass(frozen=True)
class Candidate:
    #: Written as the rule, not the incident: "A cell is not a unit of ground".
    title: str
    #: Quoted from where it was seen, not summarised.
    evidence: str
    #: Where: an artifact path, a run id, a file and line. A reader goes here.
    seen_at: str
    #: The role or agent that proposed it.
    proposed_by: str
    methods: tuple[str, ...] = ()
    #: The procedure step it belongs to, or None where no step covers it -- which is
    #: worth knowing, since a lesson no step covers is one nothing can enforce.
    procedure: str | None = None
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class Candidates:
    """The proposals for one project, oldest first."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.items: list[Candidate] = []
        if path.is_file():
            for raw in path.read_text("utf-8").splitlines():
                if raw.strip():
                    record = json.loads(raw)
                    record["methods"] = tuple(record.get("methods") or ())
                    self.items.append(Candidate(**record))

    def propose(self, candidate: Candidate) -> Candidate:
        self._refuse_unsupported(candidate)
        self.items.append(candidate)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(candidate)) + "\n")
        return candidate

    def _refuse_unsupported(self, candidate: Candidate) -> None:
        from ofag.agent.roles import STEP_OWNER

        if len(candidate.title.strip()) < _SHORTEST_TITLE:
            raise UnsupportedCandidate(
                f"a lesson's title is the rule it teaches, and {candidate.title!r} is too short "
                "to be one"
            )
        if len(candidate.evidence.strip()) < _SHORTEST_EVIDENCE:
            raise UnsupportedCandidate(
                "the evidence is quoted from where the failure was seen, and this is too short "
                "to be a quotation"
            )
        if not candidate.seen_at.strip():
            raise UnsupportedCandidate(
                "say where it was seen -- an artifact, a run, a file and line -- so a person "
                "can check it before admitting it"
            )
        unknown = sorted(set(candidate.methods) - set(METHOD_NAMES))
        if unknown:
            raise UnsupportedCandidate(
                f"no method {unknown}; the methods are {', '.join(METHOD_NAMES)}"
            )
        if candidate.procedure is not None and candidate.procedure not in STEP_OWNER:
            raise UnsupportedCandidate(
                f"{candidate.procedure!r} is not a step of the procedure; leave it empty where "
                "no step covers this"
            )
        wanted = candidate.title.strip().lower()
        if any(item.title.strip().lower() == wanted for item in self.items):
            raise UnsupportedCandidate(f"{candidate.title!r} has already been proposed")


def candidates_for(artifact_root: Path) -> Candidates:
    return Candidates(Path(artifact_root) / FILENAME)
