"""Calling the tools, with the tier honoured and the refusals kept."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ofag.agent.tools import Tier, Tool, tool_manifest

__all__ = ["ToolError", "Dispatcher", "GRANTED_BY_DEFAULT"]

#: The tiers a caller may use without asking for more.
GRANTED_BY_DEFAULT = (Tier.READ, Tier.COMPUTE, Tier.WRITE)


_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "object": (dict,),
    "array": (list, tuple),
    "boolean": (bool,),
    "integer": (int,),
    "number": (int, float),
}


def _shape_problem(declared: dict[str, Any], value: Any) -> str | None:
    """What is wrong with one argument against its declared schema, or None."""
    kind = declared.get("type")
    if isinstance(kind, str) and kind in _TYPES:
        allowed = _TYPES[kind]
        # bool is an int in Python and is never what an integer field means.
        if not isinstance(value, allowed) or (
            kind in {"integer", "number"} and isinstance(value, bool)
        ):
            article = "an" if kind[0] in "aeiou" else "a"
            return f"has to be {article} {kind}, not {type(value).__name__}"
    if "enum" in declared and value not in declared["enum"]:
        return f"has to be one of {declared['enum']}, not {value!r}"
    items = declared.get("items", {})
    if isinstance(value, (list, tuple)) and "enum" in items:
        stray = [v for v in value if v not in items["enum"]]
        if stray:
            return f"may hold only {items['enum']}, not {stray}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in declared and value < declared["minimum"]:
            return f"has to be at least {declared['minimum']}, not {value}"
        if "maximum" in declared and value > declared["maximum"]:
            return f"has to be at most {declared['maximum']}, not {value}"
    return None


class ToolError(RuntimeError):
    """A call that could not be made, and why."""


@dataclass(frozen=True)
class Dispatcher:
    """Routes a tool call to the thing that does it."""

    #: Where a project's runs and ledger live.
    artifact_root: Path
    granted: tuple[Tier, ...] = GRANTED_BY_DEFAULT
    registry: Any = None
    #: The tools this caller may name, or None for every tool its tiers allow.
    allowed: frozenset[str] | None = None
    #: The name every ledger entry this caller discharges is recorded under.
    actor: str = ""
    cancelled: Callable[[], bool] | None = None

    def manifest(self) -> tuple[Tool, ...]:
        """Only the tools this caller may use, so it cannot plan on the rest."""
        return tuple(
            tool
            for tool in tool_manifest(self.registry)
            if tool.tier in self.granted and (self.allowed is None or tool.name in self.allowed)
        )

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Make one call, or say why it cannot be made."""
        if arguments is not None and not isinstance(arguments, Mapping):
            raise ToolError(
                f"{name} takes its arguments as an object of named fields, not "
                f"{type(arguments).__name__}"
            )
        arguments = dict(arguments or {})
        tool = self._tool(name)
        self._check_arguments(tool, arguments)
        return self._handler(name)(arguments)

    # -- refusals -----------------------------------------------------------

    def _tool(self, name: str) -> Tool:
        declared = {tool.name: tool for tool in tool_manifest(self.registry)}
        if name not in declared:
            raise ToolError(
                f"no tool named {name!r}. The surface is exactly what "
                f"`tool_manifest` declares: {', '.join(sorted(declared))}"
            )
        tool = declared[name]
        if self.allowed is not None and name not in self.allowed:
            raise ToolError(
                f"{name} is not a tool of {self.actor or 'this caller'}, which holds "
                f"{', '.join(sorted(self.allowed))}. Hand the work to the role that holds it; "
                f"a role that could do everything could also check its own work."
            )
        if tool.tier not in self.granted:
            raise ToolError(
                f"{name} is {tool.tier.value} and this caller holds "
                f"{', '.join(tier.value for tier in self.granted)}. Ask for the tier rather "
                f"than working around it."
            )
        return tool

    @staticmethod
    def _check_arguments(tool: Tool, arguments: dict[str, Any]) -> None:
        declared = set(tool.input_schema.get("properties", {}))
        required = set(tool.input_schema.get("required", []))
        unknown = sorted(set(arguments) - declared)
        missing = sorted(required - set(arguments))
        if unknown or missing:
            raise ToolError(
                f"{tool.name} takes {sorted(declared) or 'no arguments'}"
                + (f"; missing {missing}" if missing else "")
                + (f"; unexpected {unknown}" if unknown else "")
            )
        # Validate nested tool arguments before dispatch.
        properties = tool.input_schema.get("properties", {})
        for key, value in arguments.items():
            problem = _shape_problem(properties.get(key, {}), value)
            if problem:
                raise ToolError(f"{tool.name}: {key!r} {problem}")

    # -- the handlers -------------------------------------------------------

    def _handler(self, name: str) -> Callable[[dict[str, Any]], Any]:
        from ofag.agent.workbench_tools import handle, manifest

        if name == "ofag.saved_run":
            return self._saved_run
        if name in {tool.name for tool in manifest()}:
            return lambda arguments: handle(self.artifact_root, name, arguments, self.actor)
        handlers: dict[str, Callable[[dict[str, Any]], Any]] = {
            "ofag.list_plugins": self._list_plugins,
            "ofag.describe_plugin": self._describe_plugin,
            "ofag.conventions": self._conventions,
            "ofag.lessons": self._lessons,
            "ofag.owed": self._owed,
            "ofag.validate": self._validate,
            "ofag.estimate": self._estimate,
            "ofag.sample": self._sample,
            "ofag.execute": self._execute,
            "ofag.result": self._result,
            "ofag.record_decision": self._record_decision,
            "ofag.classify_question": self._classify_question,
            "ofag.list_importers": self._list_importers,
            "ofag.describe_importer": self._describe_importer,
            "ofag.import_data": self._import_data,
            "ofag.delete_run": self._delete_run,
            "ofag.cell_grid": self._cell_grid,
            "ofag.build_model": self._build_model,
            "ofag.journal": self._journal,
            "ofag.note": self._note,
            "ofag.registries": self._registries,
            "ofag.resolve_identifier": self._resolve_identifier,
            "ofag.project": self._project,
            "ofag.retrieve": self._retrieve,
            "ofag.diagnose": self._diagnose,
            "ofag.audit": self._audit,
            "ofag.propose_lesson": self._propose_lesson,
        }
        if name not in handlers:
            raise ToolError(
                f"{name} is declared and has no handler yet. Declared and unimplemented is "
                f"better than implemented and undeclared, but it is still not callable."
            )
        return handlers[name]

    def _saved_run(self, arguments: dict[str, Any]) -> Any:
        from uuid import UUID

        from ofag.core.schemas import RunSpec

        identifier = UUID(arguments["run_id"])
        path = self.artifact_root / "drafts" / f"{identifier}.json"
        spec = RunSpec.model_validate_json(path.read_text("utf-8"))
        payload = {"spec": spec.model_dump(mode="json")}
        if arguments["action"] == "sample":
            if not arguments.get("smaller_run_id"):
                raise ToolError("Sampling needs smaller_run_id naming a saved smaller draft.")
            smaller_id = UUID(arguments["smaller_run_id"])
            smaller = RunSpec.model_validate_json(
                (self.artifact_root / "drafts" / f"{smaller_id}.json").read_text("utf-8")
            )
            payload["smaller"] = smaller.model_dump(mode="json")
        return self.call("ofag." + arguments["action"], payload)

    # -- the open project ------------------------------------------------------

    def _project(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """What the open project is and holds, read from its own records."""
        from ofag.agent.project_context import ProjectContext

        context = ProjectContext.find(self.artifact_root)
        if context is None:
            raise ToolError(
                f"{self.artifact_root} is not a project's runs folder (no project.json beside "
                "it), so there is no open project to describe."
            )
        return context.summary()

    # -- what the project has written down -----------------------------------

    def _retrieve(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Passages from the procedure, the lessons, the write-ups and received practice."""
        from ofag.agent.project_context import LESSONS_ARE_NOT_DATA
        from ofag.agent.retrieval import Kind, default_index

        stage = str(arguments.get("stage") or "").strip().upper()
        if stage and stage not in {"A", "B", "C"}:
            raise ToolError(
                f"no stage {stage!r}: A is before an inversion, B after a bad misfit, C "
                "before reading a result into a model"
            )
        try:
            kinds = tuple(Kind(k) for k in arguments.get("kinds") or ())
            hits = default_index().search(
                str(arguments.get("query") or ""),
                stages=(stage,) if stage else (),
                procedure=(
                    str(arguments["procedure"]).upper() if arguments.get("procedure") else None
                ),
                method=arguments.get("method") or None,
                kinds=kinds,
                k=6 if arguments.get("k") is None else int(arguments["k"]),
            )
        except ValueError as refused:
            raise ToolError(f"ofag.retrieve refused: {refused}") from refused
        return {
            "passages": [
                {
                    "id": hit.passage.id,
                    "kind": hit.passage.kind.value,
                    "cite_as": hit.passage.cited_as,
                    "stage": hit.passage.stage,
                    "lessons": list(hit.passage.lessons),
                    "matched": list(hit.matched),
                    "text": hit.passage.text,
                    **({"dois": list(hit.passage.dois)} if hit.passage.dois else {}),
                }
                for hit in hits
            ],
            "note": (
                "Quoted from the files named in cite_as. A claim made from a passage cites it; "
                "a passage that does not bear on the question is not evidence for it. "
                + LESSONS_ARE_NOT_DATA
                + " A passage of kind 'received' is published practice this project has not "
                "measured: it may suggest a check, and it is never a reason to pass or refuse "
                "a run."
            ),
        }

    def _propose_lesson(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Hold a proposed lesson for a person to admit, or say what it lacks."""
        from ofag.agent.candidates import Candidate, UnsupportedCandidate, candidates_for

        book = candidates_for(self.artifact_root)
        try:
            proposed = book.propose(
                Candidate(
                    title=str(arguments["title"]),
                    evidence=str(arguments["evidence"]),
                    seen_at=str(arguments["seen_at"]),
                    proposed_by=self.actor or "unnamed",
                    methods=tuple(str(m) for m in arguments.get("methods") or ()),
                    procedure=(
                        str(arguments["procedure"]).upper() if arguments.get("procedure") else None
                    ),
                )
            )
        except UnsupportedCandidate as refused:
            raise ToolError(str(refused)) from refused
        return {
            "proposed": proposed.title,
            "by": proposed.proposed_by,
            "awaiting_a_person": len(book.items),
            "note": "Held for a person to admit into docs/lessons/lessons.yaml; not a lesson yet.",
        }

    # -- diagnosing and auditing a run ----------------------------------------

    def _fingerprint_of(self, run_id: str) -> tuple[Any, str]:
        from uuid import UUID

        from ofag.core.schemas import spec_fingerprint
        from ofag.services.run_service import RunService

        try:
            record = RunService(artifact_root=self.artifact_root).get(UUID(run_id))
        except (KeyError, ValueError) as absent:
            raise ToolError(f"run {run_id} is not here") from absent
        return record, spec_fingerprint(record.spec)

    def _diagnose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Record that the misfit was read, and what was concluded from it."""
        from ofag.agent.obligations import ObligationError, Stage

        _, fingerprint = self._fingerprint_of(str(arguments["run_id"]))
        ledger = self._session().ledger
        try:
            entry = ledger.discharge(
                Stage.DIAGNOSED, fingerprint, str(arguments["evidence"]), by=self.actor
            )
        except ObligationError as owed:
            return {"diagnosed": False, "owed": [s.value for s in owed.missing], "why": str(owed)}
        except ValueError as refused:
            raise ToolError(str(refused)) from refused
        return {"diagnosed": True, "by": entry.by or None, "at": entry.at}

    def _audit(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Pass a run on to be read into a model, or veto it with the reason."""
        from ofag.agent.obligations import NotIndependent, ObligationError, Stage, Vetoed
        from ofag.agent.remembering import Kind as NoteKind
        from ofag.agent.remembering import UnsupportedNote, journal_for

        run_id = str(arguments["run_id"])
        verdict = str(arguments["verdict"])
        evidence = str(arguments["evidence"])
        if verdict not in {"pass", "veto"}:
            raise ToolError(f"a verdict is 'pass' or 'veto', not {verdict!r}")
        _, fingerprint = self._fingerprint_of(run_id)
        stage = Stage.AUDITED if verdict == "pass" else Stage.VETOED
        ledger = self._session().ledger
        try:
            entry = ledger.discharge(stage, fingerprint, evidence, by=self.actor)
        except ObligationError as owed:
            return {"audited": False, "owed": [s.value for s in owed.missing], "why": str(owed)}
        except (NotIndependent, Vetoed, ValueError) as refused:
            raise ToolError(str(refused)) from refused
        if verdict == "pass":
            return {"audited": True, "by": entry.by, "at": entry.at}
        # The ledger is what holds the veto; this note is how the lead hears of it.
        try:
            note = journal_for(self.artifact_root).note(
                NoteKind.ASKED,
                f"audit veto on run {run_id}",
                because=(
                    f"{self.actor}: {evidence}. The ledger holds this veto until the run is "
                    "executed or adopted again; satisfying this note does not lift it."
                ),
            )
        except UnsupportedNote as refused:
            raise ToolError(str(refused)) from refused
        return {"audited": False, "vetoed": True, "by": entry.by, "owed_in_journal": note.what}

    # -- following an identifier off this machine -----------------------------

    def _registries(self, arguments: dict[str, Any]) -> list[dict[str, str]]:
        """Where an identifier may be followed."""
        from ofag.agent.scholarship import REGISTRIES

        return [{"host": item.host, "answers_for": item.what} for item in REGISTRIES]

    def _resolve_identifier(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Follow one identifier, or find candidates for a reference in prose."""
        from ofag.agent.scholarship import NotFound, OffTheList, look_up, search

        identifier = str(arguments.get("identifier") or "").strip()
        bibliographic = str(arguments.get("bibliographic") or "").strip()
        if bool(identifier) == bool(bibliographic):
            raise ToolError(
                "give either an identifier to follow or a bibliographic string to search "
                "for, and not both: they are different questions and the second is a guess."
            )
        try:
            if identifier:
                found = look_up(identifier)
                return {
                    "identifier": found.identifier,
                    "resolved_to": found.as_resolved_to(),
                    "title": found.title,
                    "authors": list(found.authors),
                    "year": found.year,
                    "kind": found.kind,
                    "publisher": found.publisher,
                    "registry": found.registry,
                }
            candidates = search(bibliographic)
        except NotFound as absent:
            raise ToolError(str(absent)) from absent
        except OffTheList as refused:  # pragma: no cover - the URLs are built here
            raise ToolError(str(refused)) from refused
        except OSError as unreachable:
            raise ToolError(
                f"could not reach the registry: {unreachable}. Nothing is recorded as "
                "resolved on a failure to look, because that is not the same as a dead "
                "identifier."
            ) from unreachable
        return {
            "searched_for": bibliographic,
            "candidates": [
                {
                    "identifier": c.identifier,
                    "resolved_to": c.as_resolved_to(),
                    "year": c.year,
                    "kind": c.kind,
                }
                for c in candidates
            ],
        }

    # -- what cannot be derived -----------------------------------------------

    def _journal(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """What was asked, tried and ruled out, which no artifact records."""
        from ofag.agent.remembering import Kind, journal_for

        book = journal_for(self.artifact_root)
        about = str(arguments.get("about") or "").strip()
        if about:
            found = book.about(about)
            return {
                "about": about,
                "notes": [
                    {
                        "kind": note.kind.value,
                        "what": note.what,
                        "because": note.because,
                        "measured_where": note.measured_where,
                        "at": note.at,
                    }
                    for note in found
                ],
            }
        from ofag.agent.candidates import candidates_for

        proposed = candidates_for(self.artifact_root).items
        return {
            "still_owed": [note.what for note in book.still_owed()],
            "lessons_proposed": [item.title for item in proposed],
            "tried_and_dropped": [
                {"what": n.what, "because": n.because} for n in book.of(Kind.TRIED)
            ],
            "ruled_out": [
                {"what": n.what, "because": n.because, "measured_where": n.measured_where}
                for n in book.of(Kind.RULED_OUT)
            ],
            "notes": len(book.notes),
        }

    def _note(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Add one, and refuse one that does not carry what its kind needs."""
        from ofag.agent.remembering import Kind, UnsupportedNote, journal_for

        book = journal_for(self.artifact_root)
        try:
            kind = Kind(str(arguments["kind"]))
        except ValueError as unknown:
            raise ToolError(
                f"no note kind {arguments['kind']!r}; the kinds are "
                + ", ".join(k.value for k in Kind)
            ) from unknown
        what = str(arguments["what"])
        try:
            if kind is Kind.SATISFIED:
                note = book.satisfy(what, by=str(arguments.get("because") or ""))
            else:
                note = book.note(
                    kind,
                    what,
                    because=str(arguments.get("because") or ""),
                    measured_where=str(arguments.get("measured_where") or ""),
                )
        except UnsupportedNote as refused:
            raise ToolError(str(refused)) from refused
        return {
            "kind": note.kind.value,
            "what": note.what,
            "at": note.at,
            "still_owed": len(book.still_owed()),
        }

    # -- making a volume and labelling it -------------------------------------

    def _cell_grid(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Lay out the cells, hung on ground that had to be stated (F034)."""
        from ofag.agent.volumes import CellGridSpec, build_cell_grid, save_grid

        try:
            spec = CellGridSpec(**dict(arguments["spec"]))
        except Exception as refused:
            raise ToolError(f"ofag.cell_grid refused the specification: {refused}") from refused
        try:
            grid = build_cell_grid(spec)
        except ValueError as refused:
            raise ToolError(f"ofag.cell_grid refused: {refused}") from refused
        path = save_grid(grid, self.artifact_root)
        path.with_suffix(".spec.json").write_text(spec.model_dump_json(indent=2), encoding="utf-8")
        return {**grid.summary(), "path": path.as_posix()}

    def _build_model(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Label every cell of a grid, and say what decided each one."""
        from uuid import UUID

        import numpy as np

        from ofag.agent.volumes import load_grid
        from ofag.core.schemas import UnitRule
        from ofag.services.interpretation_service import InterpretationService

        try:
            grid = load_grid(UUID(str(arguments["grid_id"])), self.artifact_root)
        except (FileNotFoundError, ValueError) as absent:
            raise ToolError(str(absent)) from absent

        try:
            rules = tuple(UnitRule(**dict(rule)) for rule in arguments.get("rules") or ())
        except Exception as refused:
            raise ToolError(f"ofag.build_model refused a rule: {refused}") from refused
        if not rules:
            raise ToolError("ofag.build_model needs at least one rule; nothing labels itself")

        surfaces = self._surfaces_for(grid, dict(arguments.get("surfaces") or {}))
        given_sections = dict(arguments.get("sections") or {})
        sections = self._sections_for(given_sections)
        self._refuse_rules_without_their_evidence(rules, surfaces, sections)
        owed = self._owed_before_reading(given_sections)
        if owed:
            return {
                "built": False,
                "owed": owed,
                "why": (
                    "a run is read into a model only after it was diagnosed and then audited "
                    "by someone other than whoever ran it. Diagnose it, and ask the audit role."
                ),
            }

        try:
            model = InterpretationService().assign_units(
                rules,
                cell_centres_m=grid.cell_centres_m,
                cell_volume_m3=grid.cell_volume_m3,
                depth_below_ground_m=grid.depth_below_ground_m,
                surfaces=surfaces,
                sections=sections or None,
            )
        except (KeyError, ValueError) as refused:
            raise ToolError(f"ofag.build_model refused: {refused}") from refused

        report = model.report
        self._record_reading(given_sections, report)
        saved = self._save_labelled_model(grid, rules, model)
        import json

        saved.with_suffix(".recipe.json").write_text(
            json.dumps(arguments, indent=2), encoding="utf-8"
        )
        return {
            "built": True,
            "model_id": saved.stem,
            "saved_to": saved.as_posix(),
            "grid_id": str(grid.grid_id),
            "cells": grid.cells,
            "ground_source": grid.terrain.source,
            "undecided_cells": report.undecided_cells,
            "units": [
                {
                    "name": unit.name,
                    "source": unit.source,
                    "cell_count": unit.cell_count,
                    "volume_share": unit.volume_share,
                }
                for unit in report.units
            ],
            "furthest_column_from_a_ground_point_m": float(np.max(grid.ground_distance_m)),
        }

    def _save_labelled_model(self, grid: Any, rules: Any, model: Any) -> Any:
        """Write the labels, so the model can be looked at and not only summarised."""
        from uuid import uuid4

        import numpy as np

        from ofag.services.unit_models import MODELS_DIR, save_unit_model

        unit = np.asarray(model.unit, dtype=int).copy()
        names = [rule.name for rule in rules]
        sources = [rule.source for rule in rules]
        if (unit < 0).any():
            unit[unit < 0] = len(names)
            names.append("nothing claimed")
            sources.append("no rule reached these cells")
        lines = [f"{u.name}: {u.volume_share * 100:.1f}% ({u.source})" for u in model.report.units]
        import json

        grid_spec = self.artifact_root / "grids" / f"{grid.grid_id}.spec.json"
        widths = None
        if grid_spec.is_file():
            cell_m = json.loads(grid_spec.read_text("utf-8"))["cell_m"]
            widths = np.tile(cell_m, (grid.cells, 1))
        return save_unit_model(
            self.artifact_root / MODELS_DIR / f"{uuid4()}.npz",
            unit=unit,
            unit_names=names,
            unit_sources=sources,
            centres_m=grid.cell_centres_m,
            widths_m=widths,
            report="\n".join(lines),
            name=f"{grid.name}, {len(rules)} rules",
            support_distance_m=np.asarray(model.support_distance_m, dtype=float),
            ground_elevation_m=np.asarray(grid.ground_elevation_m, dtype=float),
        )

    def _owed_before_reading(self, given: dict[str, Any]) -> dict[str, list[str]]:
        """For each run a section comes from, what it owes before it may be read."""
        from ofag.agent.obligations import Stage

        ledger = self._session().ledger
        owed: dict[str, list[str]] = {}
        for source in given.values():
            run_id = str(dict(source)["run_id"])
            _, fingerprint = self._fingerprint_of(run_id)
            missing = ledger.missing_for(Stage.READ_INTO_MODEL, fingerprint)
            if missing:
                owed[run_id] = [stage.value for stage in missing]
        return owed

    def _record_reading(self, given: dict[str, Any], report: Any) -> None:
        """Discharge read-into-model for every run a section came from."""
        from ofag.agent.obligations import Stage

        if not given:
            return
        ledger = self._session().ledger
        shares = ", ".join(f"{u.name} {u.volume_share:.0%}" for u in report.units)
        for name, source in given.items():
            run_id = str(dict(source)["run_id"])
            _, fingerprint = self._fingerprint_of(run_id)
            ledger.discharge(
                Stage.READ_INTO_MODEL,
                fingerprint,
                f"read as section {name!r}; {report.undecided_cells} cells undecided; {shares}",
                by=self.actor,
            )

    @staticmethod
    def _surfaces_for(grid: Any, given: dict[str, Any]) -> dict[str, Any]:
        """One array per cell for each named surface, from a number or a list."""
        import numpy as np

        surfaces: dict[str, Any] = {}
        for name, value in given.items():
            if isinstance(value, int | float):
                surfaces[name] = np.full(grid.cells, float(value))
                continue
            array = np.asarray(value, dtype=float)
            if array.shape != (grid.cells,):
                raise ToolError(
                    f"surface {name!r} has {array.shape} values for a grid of {grid.cells} "
                    "cells. Give one number to mean a flat surface, or one value per cell."
                )
            surfaces[name] = array
        return surfaces

    def _sections_for(self, given: dict[str, Any]) -> dict[str, Any]:
        """A layered section per name, read from a stored run."""
        import numpy as np

        from ofag.services.interpretation_service import LayeredSection

        sections: dict[str, Any] = {}
        from uuid import UUID

        from ofag.services.run_service import RunService

        runs = RunService(artifact_root=self.artifact_root)
        for name, source in given.items():
            if not isinstance(source, dict) or "run_id" not in source:
                raise ToolError(
                    f"section {name!r} has to be an object naming a run: "
                    '{"run_id": "...", "chi_squared_at_most": 2.0}'
                )
            request = dict(source)
            run_id = str(request["run_id"])
            # Asked of RunService rather than built here: the layout is its own, and a
            # copy of it written here as root/runs/<id> was wrong -- every run this
            # dispatcher starts lives at root/<id>.
            try:
                runs.get(UUID(run_id))
            except (KeyError, ValueError) as absent:
                raise ToolError(
                    f"section {name!r} names run {run_id}, which is not here"
                ) from absent
            path = runs.run_dir(UUID(run_id)) / "stitched_conductivity_section.npz"
            if not path.exists():
                from ofag.services.model_sections import read_section

                try:
                    sections[name] = read_section(runs, UUID(run_id), request)
                except ValueError as error:
                    raise ToolError(f"section {name!r}: {error}") from error
                continue
            with np.load(path, allow_pickle=False) as archive:
                data = {key: archive[key].copy() for key in archive.files}
            keep = np.ones(data["conductivity_s_m"].shape[0], dtype=bool)
            bar = request.get("chi_squared_at_most")
            if bar is not None:
                if "chi_squared" not in data:
                    raise ToolError(
                        f"section {name!r} has no per-site chi-squared; "
                        "cannot apply the requested filter"
                    )
                keep = np.isfinite(data["chi_squared"]) & (data["chi_squared"] <= float(bar))
            if not keep.any():
                best = float(np.min(data["chi_squared"]))
                raise ToolError(
                    f"section {name!r} keeps no soundings at chi-squared <= {bar}; "
                    f"the best in that run is {best:.3f}"
                )
            values = data["conductivity_s_m"][keep]
            as_resistivity = bool(request.get("as_resistivity", True))
            positions = data.get("receiver_locations_m")
            if positions is None:
                positions = np.column_stack(
                    [data["easting_m"], data["northing_m"], data["elevation_m"]]
                )
            sections[name] = LayeredSection(
                easting_m=positions[keep, 0],
                northing_m=positions[keep, 1],
                values=1.0 / values if as_resistivity else values,
                layer_top_depth_m=data["layer_top_depth_m"],
            )
        return sections

    @staticmethod
    def _refuse_rules_without_their_evidence(
        rules: Any, surfaces: dict[str, Any], sections: dict[str, Any]
    ) -> None:
        """A rule naming a surface or a section nobody supplied is refused here."""
        from ofag.core.schemas import UnitRuleKind

        for rule in rules:
            if rule.kind is UnitRuleKind.REMAINDER:
                continue
            if rule.kind is UnitRuleKind.PROPERTY_THRESHOLD:
                if rule.section not in sections:
                    raise ToolError(
                        f"rule {rule.name!r} reads section {rule.section!r} and none was "
                        "given. Supply it under `sections` with the run that wrote it and "
                        "the chi-squared it has to have met."
                    )
                continue
            if rule.surface not in surfaces:
                raise ToolError(
                    f"rule {rule.name!r} needs surface {rule.surface!r} and none was given. "
                    "Supply a number for a flat one or a value per cell."
                )

    # -- getting data in ----------------------------------------------------

    def _list_importers(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        from ofag.agent.importers import IMPORTERS

        return [
            {
                "importer_id": item.importer_id,
                "what": item.what,
                "tier": "read" if item.reads_only else "write",
                "refuses": item.refuses,
                "needs_extra": item.needs_extra,
                "available": self._extra_present(item),
            }
            for item in IMPORTERS
        ]

    def _describe_importer(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ofag.agent.importers import importer, request_schema

        try:
            item = importer(arguments["importer_id"])
        except KeyError as absent:
            raise ToolError(str(absent).strip('"')) from absent
        return {
            "importer_id": item.importer_id,
            "what": item.what,
            "refuses": item.refuses,
            "needs_extra": item.needs_extra,
            "available": self._extra_present(item),
            "request_schema": request_schema(item),
        }

    def _import_data(self, arguments: dict[str, Any]) -> Any:
        """Read one delivery, and say what was read and what was dropped."""
        from dataclasses import asdict, is_dataclass

        from ofag.agent.importers import importer

        try:
            item = importer(arguments["importer_id"])
        except KeyError as absent:
            raise ToolError(str(absent).strip('"')) from absent
        if not self._extra_present(item):
            raise ToolError(
                f"{item.importer_id} needs the {item.needs_extra!r} extra, which is not "
                f"installed: uv sync --extra {item.needs_extra}"
            )
        try:
            request = item.request_model(**dict(arguments.get("request") or {}))
        except Exception as refused:
            # A refusal from the request model is the reader's own rule and is the most
            # useful thing an agent can be told, so it travels whole.
            raise ToolError(f"{item.importer_id} refused the request: {refused}") from refused

        service = self._import_service(item)
        try:
            outcome = self._call_importer(item, service, request)
        except (OSError, ValueError) as refused:
            raise ToolError(f"{item.importer_id} refused: {refused}") from refused
        dump = getattr(outcome, "model_dump", None)
        if callable(dump):
            answer = dump(mode="json")
        elif is_dataclass(outcome) and not isinstance(outcome, type):
            answer = asdict(outcome)
        else:
            answer = outcome
        registered = self._register_in_project(item, request, answer)
        if registered is not None and isinstance(answer, dict):
            answer = {**answer, "registered_in_project": registered}
        return answer

    def _register_in_project(self, item: Any, request: Any, answer: Any) -> str | None:
        """Put what was imported on the open project's register, as the Data stage does."""
        from pathlib import Path

        from ofag.agent.importers import REGISTERS_AS, SOURCE_FIELDS
        from ofag.agent.project_context import ProjectContext
        from ofag.core.schemas import DatasetKind
        from ofag.services.project_service import ProjectService

        kind = REGISTERS_AS.get(item.importer_id)
        context = ProjectContext.find(self.artifact_root)
        if kind is None or context is None or not isinstance(answer, dict):
            return None
        if not answer.get("dataset_id"):
            return None
        source = next(
            (str(getattr(request, f)) for f in SOURCE_FIELDS if getattr(request, f, None)), ""
        )
        name = str(getattr(request, "name", "") or Path(source).name or item.importer_id)
        dataset = ProjectService(root=context.folder.parent).register_dataset(
            context.project_id,
            kind=DatasetKind(kind),
            name=name,
            source_filename=Path(source).name or name,
            imported=answer,
        )
        return dataset.name

    def _call_importer(self, item: Any, service: Any, request: Any) -> Any:
        """Two shapes: a reader that writes a dataset, and one that writes a run."""
        method = getattr(service, item.method)
        if not item.adopts_a_run:
            return method(request)
        from uuid import uuid4

        from ofag.agent.obligations import Stage
        from ofag.core.schemas import spec_fingerprint
        from ofag.services.run_service import RunService

        runs = RunService(artifact_root=self.artifact_root)
        run_id = uuid4()
        spec, result, imported = method(request, run_id, runs.run_dir(run_id))
        runs.adopt_external_result(spec, result)
        # Recorded so the run can be diagnosed and audited like one inverted here;
        # without it a published model could never be read into a model.
        self._session().ledger.discharge(
            Stage.ADOPTED,
            spec_fingerprint(spec),
            f"adopted by {item.importer_id}, not inverted here; run {run_id}",
            by=self.actor,
        )
        return imported

    def _import_service(self, item: Any) -> Any:
        from ofag.services.aeromagnetic_import import AeromagneticImportService
        from ofag.services.borehole_import import BoreholeImportService
        from ofag.services.data_import import DataImportService
        from ofag.services.ert_import import ERTFieldImportService
        from ofag.services.line_data_import import LayeredLineImportService
        from ofag.services.model_import import ExternalModelImportService
        from ofag.services.mt_import import MtImportService
        from ofag.services.segy_import import SegyImportService
        from ofag.services.tem_import import TemImportService

        root = self.artifact_root
        services: dict[str, Callable[[], Any]] = {
            "data": lambda: DataImportService(import_root=root),
            "ert": lambda: ERTFieldImportService(import_root=root),
            "tem": lambda: TemImportService(import_root=root),
            "mt": lambda: MtImportService(import_root=root),
            "borehole": lambda: BoreholeImportService(import_root=root),
            "aeromagnetic": lambda: AeromagneticImportService(import_root=root),
            "segy": lambda: SegyImportService(import_root=root),
            "line": LayeredLineImportService,
            "model": ExternalModelImportService,
        }
        return services[item.service]()

    @staticmethod
    def _extra_present(item: Any) -> bool:
        """Whether the optional dependency this reader needs is installed."""
        if not item.needs_extra:
            return True
        from importlib.util import find_spec

        packages = {
            "ert-formats": "PyHydroGeophysX",
            "seismic": "segyio",
            "simpeg": "simpeg",
        }
        package = packages.get(item.needs_extra)
        return package is None or find_spec(package) is not None

    def _delete_run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Remove a run through the service that owns it, and say what went."""
        from uuid import UUID

        from ofag.services.run_service import RunService

        runs = RunService(artifact_root=self.artifact_root)
        run_id = UUID(str(arguments["run_id"]))
        try:
            record = runs.get(run_id)
        except KeyError as absent:
            raise ToolError(f"no run {run_id} under {self.artifact_root}") from absent
        state = record.state.value
        try:
            runs.delete(run_id)
        except ValueError as refused:
            raise ToolError(str(refused)) from refused
        return {"run_id": str(run_id), "was": state, "deleted": True}

    def _registry(self) -> Any:
        if self.registry is not None:
            return self.registry
        from ofag.plugins.registry import default_registry

        return default_registry()

    def _session(self) -> Any:
        from ofag.agent.session import GuardedRuns
        from ofag.services.run_service import RunService

        return GuardedRuns(
            RunService(artifact_root=self.artifact_root),
            registry=self._registry(),
            actor=self.actor,
            cancelled=self.cancelled,
        )

    def _spec(self, arguments: dict[str, Any], key: str = "spec") -> Any:
        from pydantic import ValidationError

        from ofag.core.schemas import RunSpec

        try:
            return RunSpec.model_validate(arguments[key])
        except ValidationError as refused:
            raise ToolError(f"{key!r} is not a RunSpec: {refused}") from refused

    # -- read ---------------------------------------------------------------

    def _list_plugins(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "plugin_id": plugin.manifest().plugin_id,
                "plugin_version": plugin.manifest().plugin_version,
                "limitations": list(plugin.manifest().limitations),
            }
            for plugin in self._registry().all()
        ]

    def _describe_plugin(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from ofag.agent.tools import describe_plugin

        return describe_plugin(arguments["plugin_id"], self._registry())

    def _conventions(self, arguments: dict[str, Any]) -> Any:
        from ofag.core.conventions import _Unverified

        plugin = self._registry().get(arguments["plugin_id"])
        declared = getattr(plugin, "conventions", None)
        if declared is None:
            return []
        checks = declared()
        if isinstance(checks, _Unverified):
            # Said plainly rather than as an empty list, which reads as "no conventions
            # to check" when it means "none checked".
            return {
                "unverified": True,
                "why": (
                    "this plugin's conventions have not been checked against anything "
                    "independent; its results carry that on every validation"
                ),
            }
        return [
            {"name": check.name, "catches": check.catches, "against": check.against}
            for check in checks
        ]

    def _lessons(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        from ofag.agent.lessons import find, load_lessons, search

        corpus = load_lessons()
        if arguments.get("id"):
            try:
                found: tuple[Any, ...] = (find(corpus, str(arguments["id"])),)
            except KeyError as absent:
                raise ToolError(str(absent)) from absent
        else:
            try:
                found = search(
                    corpus,
                    procedure=(
                        str(arguments["procedure"]).upper() if arguments.get("procedure") else None
                    ),
                    decision=arguments.get("decision"),
                    uncovered_only=bool(arguments.get("uncovered_only", False)),
                    method=arguments.get("method"),
                )
            except ValueError as refused:
                raise ToolError(str(refused)) from refused
        return [
            {
                "id": lesson.id,
                "former_id": lesson.former_id,
                "title": lesson.title,
                "source": lesson.source,
                "methods": list(lesson.methods),
                "found_by": lesson.found_by.value,
                "silent": lesson.silent,
                "decision": lesson.decision.value,
                "procedure": lesson.procedure,
                "covered_by": lesson.covered_by,
                "evidence": lesson.evidence,
            }
            for lesson in found
        ]

    def _owed(self, arguments: dict[str, Any]) -> list[str]:
        return [stage.value for stage in self._session().owed(self._spec(arguments))]

    # -- compute ------------------------------------------------------------

    def _validate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        report = self._session().validate(self._spec(arguments))
        return {
            "valid": report.valid,
            "issues": [
                {"field": issue.field, "message": issue.message, "remediation": issue.remediation}
                for issue in report.issues
            ],
        }

    def _estimate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        estimate = self._session().estimate(self._spec(arguments))
        return {
            "estimated_seconds": estimate.resources.estimated_seconds,
            "memory_mb": estimate.resources.memory_mb,
            "estimate_basis": estimate.resources.estimate_basis,
            "note": "Uncalibrated admission heuristic, not a wall-time or peak-memory prediction. "
            "Measure a smaller run before scheduling resources.",
            "walk_owed": estimate.walk_owed,
            "why": estimate.why,
        }

    def _sample(self, arguments: dict[str, Any]) -> dict[str, Any]:
        walk = self._session().sample(self._spec(arguments), self._spec(arguments, "smaller"))
        return {
            "run_id": str(walk.run_id),
            "seconds": round(walk.seconds, 1),
            "reached_the_consumer": walk.reached_the_consumer,
            "readable": list(walk.readable),
            "unreadable": list(walk.unreadable),
        }

    def _execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run it, or return the refusal as an answer rather than an exception."""
        from ofag.agent.obligations import ObligationError

        spec = self._spec(arguments)
        try:
            record = self._session().execute(spec)
        except ObligationError as refusal:
            return {
                "ran": False,
                "owed": [stage.value for stage in refusal.missing],
                "why": str(refusal),
            }
        state = getattr(record.state, "value", str(record.state))
        if state != "SUCCEEDED":
            return {
                "ran": False,
                "run_id": str(spec.run_id),
                "state": state,
                "why": (
                    f"the run ended {state}, so it is not recorded as executed and cannot be "
                    "diagnosed or audited. Read its result for the error."
                ),
            }
        return {"ran": True, "run_id": str(spec.run_id), "state": state}

    def _result(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from uuid import UUID

        from ofag.services.run_service import RunService

        runs = RunService(artifact_root=self.artifact_root)
        run_id = UUID(arguments["run_id"])
        record = runs.get(run_id)
        result = runs.result(run_id)
        if result is None:
            return {
                "finished": record.state.value in {"FAILED", "CANCELLED", "INTERRUPTED"},
                "run_id": str(run_id),
                "state": record.state.value,
                "error": record.error,
            }
        return {
            "finished": True,
            "run_id": str(run_id),
            "state": record.state.value,
            "error": record.error,
            "summary": dict(result.summary),
            "artifacts": [artifact.relative_path for artifact in result.artifacts],
        }

    def _classify_question(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Whether this is a question yet, or something to go and run."""
        from ofag.agent.asking import ProbeCost, classify

        verdict = classify(
            tuple(ProbeCost(**probe).described() for probe in arguments.get("probes", ()))
        )
        return {
            "next": verdict.next.value,
            "because": verdict.because,
            "probe": verdict.probe.what if verdict.probe else None,
        }

    def _record_decision(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Validate a choice and hand back the comment it becomes."""
        from ofag.agent.decisions import DecisionRecord

        record = DecisionRecord.model_validate(arguments["decision"])
        return {
            "recorded_at": record.recorded_at,
            "settlement": record.settlement.value,
            "comment": record.as_comment(),
        }
