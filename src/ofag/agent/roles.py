"""The agents, as roles: who holds which tools, reads which stage, answers to whom."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from ofag.agent.dispatch import Dispatcher
from ofag.agent.retrieval import Hit, Kind, Retriever, default_index
from ofag.agent.tools import Tier, tool_manifest

__all__ = [
    "Role",
    "RoleSpec",
    "ROLES",
    "SHARED",
    "RECEIVED_MARK",
    "STEP_OWNER",
    "owner_of",
    "spec_for",
    "dispatcher_for",
    "brief",
    "check_the_split",
]


class Role(StrEnum):
    LEAD = "lead"
    DATA = "data"
    INVERSION = "inversion"
    MODELLING = "modelling"
    AUDIT = "audit"
    LITERATURE = "literature"
    DEVELOPER = "developer"


#: How a brief marks a passage of published practice, so that it is not read as
#: something one of the cases measured.
RECEIVED_MARK = "[received]"

#: What every role holds: the project's written memory, read and added to.
SHARED: tuple[str, ...] = (
    "ofag.inspect_run",
    "ofag.reuse_run",
    "ofag.list_models",
    "ofag.model_recipe",
    "ofag.describe_model",
    "ofag.survey_coverage",
    "ofag.project",
    "ofag.retrieve",
    "ofag.lessons",
    "ofag.journal",
    "ofag.note",
    "ofag.propose_lesson",
)


@dataclass(frozen=True)
class RoleSpec:
    role: Role
    #: One sentence a role's brief opens with.
    purpose: str
    #: The tools beyond `SHARED`.
    tools: tuple[str, ...]
    #: The parts of the procedure its retrieval is scoped to: A before an inversion, B
    #: after a bad misfit, C before reading into a model.
    stages: tuple[str, ...]
    #: What this role must hand back, stated so a lead can check it arrived.
    delivers: str
    #: What it fans out into, or None where it works alone.
    subagents: str | None = None
    #: None: the lead's model.
    model: str | None = None

    @property
    def holds(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(SHARED + self.tools))


ROLES: dict[Role, RoleSpec] = {
    spec.role: spec
    for spec in (
        RoleSpec(
            role=Role.LEAD,
            purpose=(
                "Turn the user's question into tasks for the other roles, and assemble what "
                "they deliver into an answer, from the ledger and the journal rather than "
                "from their conversations."
            ),
            tools=(
                "ofag.list_plugins",
                "ofag.list_importers",
                "ofag.owed",
                "ofag.result",
                "ofag.classify_question",
                "ofag.record_decision",
                "ofag.registries",
                "ofag.delete_run",
                "ofag.select_result",
                "ofag.export_report",
                "ofag.cancel_run",
            ),
            stages=(),
            delivers=(
                "the answer, with each claim traced to a run, a ledger entry or a cited "
                "passage, and the journal's still-owed list empty or explained"
            ),
            subagents="one worker per role task, each started with that role's brief",
        ),
        RoleSpec(
            role=Role.DATA,
            purpose=(
                "Bring each dataset in through an importer that states its conventions, and "
                "account for every parameter the file declares before anything is inverted."
            ),
            tools=(
                "ofag.list_importers",
                "ofag.describe_importer",
                "ofag.import_data",
                "ofag.list_plugins",
                "ofag.describe_plugin",
                "ofag.conventions",
            ),
            stages=("A",),
            delivers="imported datasets, each with its declared conventions and what was dropped",
        ),
        RoleSpec(
            role=Role.INVERSION,
            purpose=(
                "Take a specification through validation, estimate, sample and execution, "
                "then read the misfit and diagnose it before anyone else sees the result."
            ),
            tools=(
                "ofag.list_plugins",
                "ofag.describe_plugin",
                "ofag.conventions",
                "ofag.validate",
                "ofag.estimate",
                "ofag.sample",
                "ofag.owed",
                "ofag.execute",
                "ofag.prepare_run",
                "ofag.saved_run",
                "ofag.adopt_run",
                "ofag.result",
                "ofag.diagnose",
                "ofag.classify_question",
                "ofag.record_decision",
            ),
            stages=("A", "B"),
            delivers="runs that executed and were diagnosed, with the diagnosis as evidence",
        ),
        RoleSpec(
            role=Role.MODELLING,
            purpose=(
                "Lay the cells on measured ground and label them from audited runs only, "
                "saying for each unit which method decided it and what nothing claims."
            ),
            tools=("ofag.cell_grid", "ofag.build_model", "ofag.result", "ofag.record_decision"),
            stages=("C",),
            delivers="a labelled model with its unclaimed share, read only from audited runs",
        ),
        RoleSpec(
            role=Role.AUDIT,
            purpose=(
                "Read a diagnosed run's evidence cold -- the result, the ledger, the passages "
                "that bear on it -- and pass it or veto it. You did not produce it and you "
                "cannot change it."
            ),
            tools=(
                "ofag.describe_plugin",
                "ofag.conventions",
                "ofag.describe_importer",
                "ofag.owed",
                "ofag.result",
                "ofag.audit",
            ),
            stages=(),
            delivers="a pass or a veto per run, each with what was checked against what",
            subagents="one fresh reader per run or claim, so one verdict cannot colour the next",
        ),
        RoleSpec(
            role=Role.LITERATURE,
            purpose=(
                "Follow every identifier the others write down to the published thing it "
                "names, on the scholarly registries only, and report what it resolved to."
            ),
            tools=("ofag.registries", "ofag.resolve_identifier"),
            stages=("A",),
            delivers="each identifier confirmed, mismatched or dead, with what it resolved to",
        ),
        RoleSpec(
            role=Role.DEVELOPER,
            purpose=(
                "Add a capability the surface lacks, in its own git worktree, and hand back a "
                "branch that passed ruff, mypy and pytest -- never an edit to the shared tree."
            ),
            tools=(
                "ofag.list_plugins",
                "ofag.describe_plugin",
                "ofag.list_importers",
                "ofag.describe_importer",
            ),
            stages=(),
            delivers="a branch per capability, with its gates' output and the test that pins it",
            subagents="one per missing capability, each in its own worktree",
        ),
    )
}


#: Which role answers for each step of `docs/agent_validation_and_debugging.md`.
STEP_OWNER: dict[str, Role] = {
    **{step: Role.DATA for step in ("A1", "A3", "A6", "A8", "A9", "A10", "A14")},
    **{step: Role.INVERSION for step in ("A2", "A4", "A5", "A7", "A11", "A15")},
    "A12": Role.MODELLING,
    "A13": Role.LITERATURE,
    **{f"B{n}": Role.INVERSION for n in range(1, 8)},
    **{step: Role.MODELLING for step in ("C1", "C2", "C3")},
    **{step: Role.INVERSION for step in ("C4", "C5")},
}


def owner_of(procedure: str | None) -> Role | None:
    """The role that answers for a procedure step, or None for no step."""
    return None if procedure is None else STEP_OWNER.get(procedure)


def spec_for(role: Role | str) -> RoleSpec:
    try:
        return ROLES[Role(role)]
    except ValueError as unknown:
        raise ValueError(
            f"no role {role!r}; the roles are {', '.join(r.value for r in Role)}"
        ) from unknown


def dispatcher_for(role: Role | str, artifact_root: Path, *, registry: Any = None) -> Dispatcher:
    """The surface one role sees: its tools and no others, acting under its name."""
    spec = spec_for(role)
    declared = {tool.name: tool for tool in tool_manifest(registry)}
    tiers = tuple(dict.fromkeys(declared[name].tier for name in spec.holds))
    return Dispatcher(
        artifact_root=Path(artifact_root),
        granted=tiers,
        registry=registry,
        allowed=frozenset(spec.holds),
        actor=spec.role.value,
    )


def check_the_split(registry: Any = None) -> list[str]:
    """What is wrong with how the tools are divided, or nothing."""
    declared = {tool.name: tool for tool in tool_manifest(registry)}
    problems: list[str] = []
    for spec in ROLES.values():
        unknown = sorted(set(spec.holds) - set(declared))
        if unknown:
            problems.append(f"{spec.role.value} holds tools that do not exist: {unknown}")
    held = {name for spec in ROLES.values() for name in spec.holds}
    orphans = sorted(set(declared) - held)
    if orphans:
        problems.append(f"no role holds {orphans}, so no agent can call them")

    def holders(name: str) -> set[Role]:
        return {spec.role for spec in ROLES.values() if name in spec.holds}

    for name, tool in declared.items():
        if tool.tier is Tier.OUTWARD and holders(name) - {Role.LITERATURE}:
            problems.append(f"{name} reaches off the machine and only literature may hold it")
        if tool.tier is Tier.DESTRUCTIVE and holders(name) - {Role.LEAD}:
            problems.append(f"{name} removes things and only the lead may hold it")
    producing = {"ofag.import_data", "ofag.execute", "ofag.diagnose", "ofag.build_model"}
    if producing & set(ROLES[Role.AUDIT].holds):
        problems.append("the auditor holds a tool that produces what it audits")
    if holders("ofag.audit") != {Role.AUDIT}:
        problems.append("ofag.audit is held by a role other than the auditor")
    if holders("ofag.execute") != holders("ofag.diagnose"):
        problems.append("whoever executes a run has to be whoever diagnoses it first")
    return problems


def brief(
    role: Role | str,
    *,
    question: str = "",
    method: str | None = None,
    index: Retriever | None = None,
    k: int = 6,
) -> str:
    """What a role is started with: its job, its tools, and what bears on the task."""
    spec = spec_for(role)
    hits = _retrieve_for(spec, question, method, index or default_index(), k)
    lines = [
        f"# You are the {spec.role.value} role of the OFAG agents",
        "",
        spec.purpose,
        "",
        f"You deliver: {spec.delivers}.",
        "",
        "## Your tools",
        "",
        ", ".join(spec.holds) + ".",
        "Anything else is refused. Work another role holds is handed to it through the "
        "journal (ofag.note, kind 'asked'), not done here.",
        "",
        "## How the roles coordinate",
        "",
        "- Call ofag.project first: it says what the open project holds. Answer questions "
        "about the project from it, never from the lessons below.",
        "- Read ofag.journal before planning: what is owed, tried and ruled out.",
        "- Results travel as ledger entries, journal notes and decision records. Nobody "
        "reads your conversation, so anything that matters is written to one of those.",
        "- A refusal is an answer. Read what it says is owed and discharge that; do not "
        "retry the call.",
    ]
    if spec.subagents:
        lines += ["", "## Subagents", "", f"You may fan out: {spec.subagents}."]
    lines += [
        "",
        "## What earlier field cases taught, that bears on this",
        "",
        "Lessons from the cases OFAG was built on -- not data in the open project.",
        f"A passage marked {RECEIVED_MARK} is published practice this project has not "
        "measured: it may suggest a check, and it is never a reason to pass or refuse a run.",
        "",
    ]
    if not hits:
        lines.append("Nothing retrieved. Ask ofag.retrieve with a narrower query before acting.")
    for hit in hits:
        received = hit.passage.kind is Kind.RECEIVED
        lines += [
            f"### {RECEIVED_MARK + ' ' if received else ''}{hit.passage.cited_as}",
            "",
            hit.passage.text.strip(),
            "",
        ]
    lines += [
        "Cite a passage by its heading when a claim rests on it. A passage that does not "
        "bear on the question is not evidence for it.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _retrieve_for(
    spec: RoleSpec, question: str, method: str | None, index: Retriever, k: int
) -> Sequence[Hit]:
    """The role's slice: its stages, its method, ranked by the question."""
    if question.strip():
        return index.search(question, stages=spec.stages, method=method, k=k)
    return index.search("", stages=spec.stages, method=method, kinds=(Kind.PROCEDURE,), k=k)
