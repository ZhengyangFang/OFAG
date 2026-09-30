"""OFAG as a set of tools, with what each one refuses written into it."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ofag.agent.importers import importer_ids
from ofag.agent.lessons import METHOD_NAMES
from ofag.agent.retrieval import METHODS
from ofag.agent.volumes import CellGridSpec

__all__ = ["Tier", "Tool", "tool_manifest", "REFUSALS"]


class Tier(StrEnum):
    """What a tool is allowed to do, and therefore what it needs."""

    #: Reads. Listing, describing, fetching a result that already exists.
    READ = "read"
    #: Computes and may write artifacts, subject to the obligations.
    COMPUTE = "compute"
    #: Writes project state: creates a project, saves a model.
    WRITE = "write"
    #: Removes or overwrites. Confirmed by a person, every time.
    DESTRUCTIVE = "destructive"
    #: Leaves this machine.
    OUTWARD = "outward"


#: What each tool refuses, in the words its description carries.
REFUSALS: dict[str, str] = {
    "ofag.validate": (
        "Refuses nothing. Returns a report; an invalid specification is an answer, not an error."
    ),
    "ofag.estimate": "Refuses nothing, and is the only way to learn whether a walk is owed.",
    "ofag.sample": (
        "Refuses a walk down a different plugin's path, and a walk that is the run itself. "
        "A walk whose artifacts cannot be read back at their declared paths does not count "
        "as taken."
    ),
    "ofag.execute": (
        "Refuses a specification that has not been validated, whose conventions have not "
        "been checked, or that has not been estimated -- and, where the estimate is above "
        "the walk threshold, one that has not been walked on a smaller version first. The "
        "refusal names which of those is owed."
    ),
    "ofag.import_data": (
        "Each reader refuses what its own format lets through: a turn-off ramp no "
        "transmitter could produce, a hole with no elevation source, a site too "
        "three-dimensional for a layered inversion, electrodes read in the wrong order. "
        "`describe_importer` names them per reader, because the point of a refusal written "
        "down is that it can be planned around rather than discovered."
    ),
    "ofag.resolve_identifier": (
        "Reaches only the named registries, over https, with a GET that carries no body: the "
        "scope is published work and it is enforced as a host list rather than as a judgement "
        "about content, because an index has to be measured against what it filters for "
        "before it gates anything (A6). A redirect off the list is refused, since the list "
        "means nothing if the first hop can leave it. Nothing is ever sent out but the "
        "identifier being looked up."
    ),
    "ofag.note": (
        "An abandoned approach or a refuted hypothesis is refused unless it says why, and a "
        "refutation is refused unless it says where the measurement was taken: F052 is a "
        "hypothesis ruled out on a figure from twenty metres below the band it was about. "
        "Satisfying an ask nobody made is refused rather than filed."
    ),
    "ofag.cell_grid": (
        "Refuses a grid whose ground is unstated. A volume on a plane renders, reports unit "
        "shares and is read as geology exactly like one that is not, and the box this was "
        "found in had 36 m between the fifth and ninety-fifth percentiles of its own "
        "elevation (F034). Flat is an answer; silence is not."
    ),
    "ofag.build_model": (
        "Refuses to read a run that missed its target misfit into geology unless a reason "
        "for using it anyway is recorded. A misfit that nothing acknowledges is a claim "
        "about the ground that nothing stands behind. Reads a section from a run only once "
        "that run was diagnosed and then audited by someone else; until then it returns "
        "what is owed instead of a model."
    ),
    "ofag.propose_lesson": (
        "Refuses a proposal without a rule-shaped title, evidence quoted from where it was "
        "seen, and where that was; a method outside the vocabulary; a step that is not one; "
        "and a title already proposed. It never writes the corpus: a person admits a lesson."
    ),
    "ofag.diagnose": (
        "Refuses a run that has not executed, and evidence that says it was done rather "
        "than what was read: the misfit, where the residual sits, which rung of the B "
        "ladder explained it."
    ),
    "ofag.audit": (
        "Refuses an audit from whoever executed or diagnosed the run, and one from a caller "
        "with no name, because a reader that wrote what it is reading finds what it "
        "expected (F056). A veto stands in the ledger until the run is executed or adopted "
        "again, and no audit passes while it does; the lead hears of it through the journal."
    ),
}


@dataclass(frozen=True)
class Tool:
    """One tool: what it is for, what it takes, and what it will not do."""

    name: str
    tier: Tier
    summary: str
    #: JSON Schema for the arguments, in the shape a tool protocol wants.
    input_schema: dict[str, Any]
    #: What this refuses, or None where it refuses nothing.
    refuses: str | None = None

    @property
    def description(self) -> str:
        """Summary and refusal together, which is what a caller reads."""
        return self.summary if self.refuses is None else f"{self.summary}\n\n{self.refuses}"


def _schema(model: Any) -> dict[str, Any]:
    return dict(model.model_json_schema())


def _object(**properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STRING = {"type": "string"}


def tool_manifest(registry: Any = None) -> tuple[Tool, ...]:
    """Every tool this surface offers, with its schema and its refusals."""
    from ofag.core.schemas import RunSpec

    if registry is None:
        from ofag.plugins.registry import default_registry

        registry = default_registry()
    plugin_ids = sorted(plugin.plugin_id for plugin in registry.all())
    run_spec = _schema(RunSpec)
    from ofag.agent.workbench_tools import manifest as workbench_manifest

    return (
        *workbench_manifest(),
        Tool(
            name="ofag.list_plugins",
            tier=Tier.READ,
            summary=(
                "Every inversion method this installation offers, with what each supports "
                "and the limitations it declares about itself."
            ),
            input_schema=_object(),
        ),
        Tool(
            name="ofag.describe_plugin",
            tier=Tier.READ,
            summary=(
                "The exact shape of a valid specification for one method, as JSON Schema, "
                "from the plugin's own physics model. Read this before writing a "
                "specification rather than after one is refused."
            ),
            input_schema=_object(
                plugin_id={"type": "string", "enum": plugin_ids},
            ),
        ),
        Tool(
            name="ofag.conventions",
            tier=Tier.READ,
            summary=(
                "What a method checks about its engine before it will run: what each check "
                "catches, and what outside the engine it is measured against. A method that "
                "declares none has to say why."
            ),
            input_schema=_object(plugin_id={"type": "string", "enum": plugin_ids}),
        ),
        Tool(
            name="ofag.validate",
            tier=Tier.COMPUTE,
            summary=(
                "Check a specification against its plugin, and run every convention check "
                "that plugin declares. Discharges two of the obligations execute requires."
            ),
            input_schema=_object(spec=run_spec),
            refuses=REFUSALS["ofag.validate"],
        ),
        Tool(
            name="ofag.estimate",
            tier=Tier.COMPUTE,
            summary=(
                "What a run is expected to cost, and whether that is enough to owe a walk "
                "on a smaller version first."
            ),
            input_schema=_object(spec=run_spec),
            refuses=REFUSALS["ofag.estimate"],
        ),
        Tool(
            name="ofag.sample",
            tier=Tier.COMPUTE,
            summary=(
                "Walk the whole path on a smaller version of a run and read every artifact "
                "it declares back at the path it declares. The reading back is the point: a "
                "sample that finished and was never read has checked that it ran."
            ),
            input_schema=_object(spec=run_spec, smaller=run_spec),
            refuses=REFUSALS["ofag.sample"],
        ),
        Tool(
            name="ofag.owed",
            tier=Tier.READ,
            summary="List outstanding execution gates. Does not validate or save a specification; "
            "call validate (or saved_run action validate) for an actual configuration check.",
            input_schema=_object(spec=run_spec),
        ),
        Tool(
            name="ofag.execute",
            tier=Tier.COMPUTE,
            summary="Run an inversion and wait for it.",
            input_schema=_object(spec=run_spec),
            refuses=REFUSALS["ofag.execute"],
        ),
        Tool(
            name="ofag.result",
            tier=Tier.READ,
            summary="A finished run's summary and the artifacts it declared.",
            input_schema=_object(run_id=_STRING),
        ),
        Tool(
            name="ofag.lessons",
            tier=Tier.READ,
            summary=(
                "Search what has gone wrong here before: recorded failures, most of which "
                "ran clean and were wrong. Filter by the procedure step they belong to, the "
                "method whose data they happened on, whether they were a decision, or whether "
                "any check covers them yet. `id` fetches one, by its F-number or by the "
                "identifier it had before renumbering (P19, C4, L16)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": _STRING,
                    "procedure": _STRING,
                    "method": {"type": "string", "enum": list(METHOD_NAMES)},
                    "decision": {"type": "string", "enum": ["none", "measurable", "judgement"]},
                    "uncovered_only": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="ofag.classify_question",
            tier=Tier.READ,
            summary=(
                "Before asking anyone anything: say whether something runnable would separate "
                "the options, and whether it is cheap enough to just run. Returns measure, "
                "time it first, or ask, with the reason. Six of this project's sixty-eight "
                "lessons are decisions the data would have settled for the price of one extra "
                "inversion."
            ),
            input_schema=_object(
                probes={
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "what": {"type": "string"},
                            "seconds": {"type": "number"},
                            "timing": {"enum": ["measured", "estimated"]},
                        },
                        "required": ["what", "seconds", "timing"],
                        "additionalProperties": False,
                    },
                }
            ),
        ),
        Tool(
            name="ofag.record_decision",
            tier=Tier.WRITE,
            summary=(
                "Write down a choice the data could not settle: the options and what each "
                "costs, what was chosen and on what criterion, and what would make it wrong "
                "later. Ninety-nine documented constants in this project record fifty-four "
                "choices and three say what would reverse them."
            ),
            input_schema=_object(decision={"type": "object"}),
        ),
        Tool(
            name="ofag.list_importers",
            tier=Tier.READ,
            summary=(
                "Every way data gets into a project: what each reader is for, what it "
                "refuses, and the extra it needs. The pipeline starts here -- nothing else "
                "on this surface puts data in."
            ),
            input_schema=_object(),
        ),
        Tool(
            name="ofag.describe_importer",
            tier=Tier.READ,
            summary=(
                "The exact shape of a valid request for one reader, as JSON Schema, from the "
                "service's own request model. Read this before writing a request rather than "
                "after one is refused."
            ),
            input_schema=_object(
                importer_id={"type": "string", "enum": list(importer_ids())},
            ),
        ),
        Tool(
            name="ofag.import_data",
            tier=Tier.WRITE,
            summary=(
                "Read one delivery into the project. Returns what was read and what was "
                "dropped, because a reader that silently keeps less than it was given is "
                "how a survey becomes a different survey."
            ),
            input_schema=_object(
                importer_id={"type": "string", "enum": list(importer_ids())},
                request={"type": "object"},
            ),
            refuses=REFUSALS["ofag.import_data"],
        ),
        Tool(
            name="ofag.registries",
            tier=Tier.READ,
            summary=(
                "Where an identifier may be followed, and what each place answers for. "
                "Reaches nothing itself; read it to see the scope before asking for the "
                "outward tier."
            ),
            input_schema=_object(),
        ),
        Tool(
            name="ofag.resolve_identifier",
            tier=Tier.OUTWARD,
            summary=(
                "Follow a DOI or a ScienceBase item to the published thing it names, and "
                "report the title, authors and year that came back. This is how the "
                "dereference A13 requires actually happens: four of five identifiers in one "
                "source table here were well-formed, resolvable, and pointed at something "
                "else."
            ),
            input_schema={
                "type": "object",
                "properties": {"identifier": _STRING, "bibliographic": _STRING},
                "required": [],
                "additionalProperties": False,
            },
            refuses=REFUSALS["ofag.resolve_identifier"],
        ),
        Tool(
            name="ofag.journal",
            tier=Tier.READ,
            summary=(
                "What this project was asked for and has not delivered, what was tried and "
                "abandoned, and what was ruled out. Read it before planning: everything else "
                "on this surface is derivable from the artifacts and this is not."
            ),
            input_schema={
                "type": "object",
                "properties": {"about": _STRING},
                "required": [],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="ofag.note",
            tier=Tier.WRITE,
            summary=(
                "Record an ask, a satisfaction, an approach abandoned, or a hypothesis ruled "
                "out. Append-only: satisfying an ask adds a note naming it rather than "
                "editing the ask away."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["asked", "satisfied", "tried", "ruled_out"],
                    },
                    "what": _STRING,
                    "because": _STRING,
                    "measured_where": _STRING,
                },
                "required": ["kind", "what"],
                "additionalProperties": False,
            },
            refuses=REFUSALS["ofag.note"],
        ),
        Tool(
            name="ofag.cell_grid",
            tier=Tier.WRITE,
            summary=(
                "Lay out the cells a geological model is written on, hung on measured "
                "ground. Returns a grid id and what the ground was measured to be; the "
                "arrays are written where build_model can read them."
            ),
            input_schema=_object(spec=_schema(CellGridSpec)),
            refuses=REFUSALS["ofag.cell_grid"],
        ),
        Tool(
            name="ofag.build_model",
            tier=Tier.WRITE,
            summary=(
                "Label every cell of a grid, first matching rule wins, recording for each "
                "one which method decided it and how far the nearest measurement was. "
                "Build the grid with cell_grid first."
            ),
            # Not `_object`, which makes every property required: a model built only
            # from `remainder` and depth rules needs neither, and a surface demanded
            # where none is wanted is a surface somebody invents.
            input_schema={
                "type": "object",
                "properties": {
                    "grid_id": _STRING,
                    "rules": {"type": "array"},
                    "surfaces": {"type": "object"},
                    "sections": {"type": "object"},
                },
                "required": ["grid_id", "rules"],
                "additionalProperties": False,
            },
            refuses=REFUSALS["ofag.build_model"],
        ),
        Tool(
            name="ofag.project",
            tier=Tier.READ,
            summary=(
                "The open project: its name, coordinate system, methods, the datasets imported "
                "into it and the runs it holds. Start here for any question about this project; "
                "the lesson corpus describes other field cases, not this one."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="ofag.retrieve",
            tier=Tier.READ,
            summary=(
                "Passages from the procedure (A before an inversion, B after a bad misfit, C "
                "before reading into a model), the lesson corpus and the case write-ups of the "
                "field cases OFAG was built on, quoted with where they came from. Lessons, not "
                "the open project's data. Also published practice per method (kind "
                "'received', with its DOIs): it may suggest a check and never passes or "
                "refuses a run. Filter by stage, procedure step or method; "
                "rank by a query. Read what bears on the step before taking it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": _STRING,
                    "stage": {"type": "string", "enum": ["A", "B", "C"]},
                    "procedure": _STRING,
                    "method": {"type": "string", "enum": sorted(METHODS)},
                    "kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["procedure", "lesson", "write_up", "received"],
                        },
                    },
                    "k": {"type": "integer", "minimum": 1, "maximum": 20},
                },
                "required": [],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="ofag.propose_lesson",
            tier=Tier.WRITE,
            summary=(
                "Propose a failure the lesson corpus does not name, in the shape a lesson has, "
                "for a person to admit. Check ofag.lessons and ofag.retrieve first: a failure "
                "that is already recorded is cited, not proposed."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": _STRING,
                    "evidence": _STRING,
                    "seen_at": _STRING,
                    "methods": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(METHOD_NAMES)},
                    },
                    "procedure": _STRING,
                },
                "required": ["title", "evidence", "seen_at"],
                "additionalProperties": False,
            },
            refuses=REFUSALS["ofag.propose_lesson"],
        ),
        Tool(
            name="ofag.diagnose",
            tier=Tier.WRITE,
            summary=(
                "Record that a finished run's misfit was read and what it was concluded to "
                "mean. Discharges the diagnosed stage, which an audit needs before it can pass "
                "the run."
            ),
            input_schema=_object(run_id=_STRING, evidence=_STRING),
            refuses=REFUSALS["ofag.diagnose"],
        ),
        Tool(
            name="ofag.audit",
            tier=Tier.WRITE,
            summary=(
                "Pass a diagnosed run on to be read into a model, or veto it with the reason. "
                "Read the run's result, its ledger and the passages that bear on it first; "
                "the evidence says what was checked against what."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "run_id": _STRING,
                    "verdict": {"type": "string", "enum": ["pass", "veto"]},
                    "evidence": _STRING,
                },
                "required": ["run_id", "verdict", "evidence"],
                "additionalProperties": False,
            },
            refuses=REFUSALS["ofag.audit"],
        ),
        Tool(
            name="ofag.delete_run",
            tier=Tier.DESTRUCTIVE,
            summary=(
                "Remove a run and its artifacts. Confirmed by a person every time: this "
                "project's own state has been left inconsistent by tidying more than once."
            ),
            input_schema=_object(run_id=_STRING),
        ),
    )


def tools_by_tier(registry: Any = None) -> dict[Tier, tuple[str, ...]]:
    """The surface grouped by what each tool is allowed to do."""
    manifest = tool_manifest(registry)
    return {tier: tuple(tool.name for tool in manifest if tool.tier is tier) for tier in Tier}


def describe_plugin(plugin_id: str, registry: Any = None) -> dict[str, Any]:
    """The JSON Schema of one method's specification, plus what it declares."""
    if registry is None:
        from ofag.plugins.registry import default_registry

        registry = default_registry()
    plugin = registry.get(plugin_id)
    manifest = plugin.manifest()
    model: Callable[[], Any] | None = getattr(plugin, "physics_model", None)
    physics = model() if model is not None else None
    return {
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.plugin_version,
        "supported_quantities": [q.value for q in manifest.supported_quantities],
        "limitations": list(manifest.limitations),
        "physics_schema": None if physics is None else _schema(physics),
    }
