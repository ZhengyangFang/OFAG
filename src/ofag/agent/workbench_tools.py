"""Project workflow tools used by conversations and desktop actions."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ofag.agent.tools import _STRING, Tier, Tool, _object
from ofag.core.schemas import RunSpec, RunState, spec_fingerprint
from ofag.services.result_quality import quality_summary
from ofag.services.result_review import ResultReview
from ofag.services.run_configuration import reuse_spec
from ofag.services.run_service import RunService


def manifest() -> tuple[Tool, ...]:
    return (
        Tool(
            "ofag.survey_coverage",
            Tier.READ,
            "Read mapped station counts, extents and missing map coordinates.",
            _object(),
        ),
        Tool(
            "ofag.describe_model",
            Tier.READ,
            "Read grid and rule schemas, source formats and coordinate requirements.",
            _object(),
        ),
        Tool(
            "ofag.prepare_run",
            Tier.WRITE,
            "Save a full draft from a source run with nested changes. Returns its id. "
            "Use saved_run to validate, estimate and execute it.",
            _object(source_run_id=_STRING, changes={"type": "object"}),
        ),
        Tool(
            "ofag.saved_run",
            Tier.COMPUTE,
            "Validate, estimate, sample, inspect obligations or execute a saved draft. "
            "Sampling requires smaller_run_id naming another saved draft. Gates still apply.",
            {
                "type": "object",
                "properties": {
                    "run_id": _STRING,
                    "smaller_run_id": _STRING,
                    "action": {
                        "type": "string",
                        "enum": [
                            "validate",
                            "estimate",
                            "sample",
                            "owed",
                            "execute",
                        ],
                    },
                },
                "required": ["run_id", "action"],
                "additionalProperties": False,
            },
        ),
        Tool(
            "ofag.inspect_run",
            Tier.READ,
            "Read a run or saved draft's complete configuration and state. "
            "Executed runs also include error, quality and artifacts.",
            _object(run_id=_STRING),
        ),
        Tool(
            "ofag.reuse_run",
            Tier.READ,
            "Read-only preview of an unsaved specification. Nothing is saved or validated. "
            "For a reusable draft use prepare_run, then saved_run with action validate.",
            _object(run_id=_STRING),
        ),
        Tool(
            "ofag.select_result",
            Tier.WRITE,
            "Select a completed result for its datasets and method. Does not grant audit.",
            _object(run_id=_STRING),
        ),
        Tool(
            "ofag.adopt_run",
            Tier.WRITE,
            "Register historical results for diagnosis and independent audit. "
            "Cannot clear a veto or grant audit. Give source evidence.",
            _object(run_id=_STRING, evidence=_STRING),
        ),
        Tool(
            "ofag.list_models",
            Tier.READ,
            "List model ids, sources, recipes and unclaimed shares.",
            _object(),
        ),
        Tool(
            "ofag.model_recipe",
            Tier.READ,
            "Read saved build_model arguments. Legacy models may have no recipe.",
            _object(model_id=_STRING),
        ),
        Tool(
            "ofag.export_report",
            Tier.WRITE,
            "Save a Markdown report of runs, fit, selected results, audits and model sources.",
            _object(),
        ),
        Tool(
            "ofag.cancel_run",
            Tier.WRITE,
            "Cancel a running project job by id.",
            _object(run_id=_STRING),
        ),
    )


def handle(root: Path, name: str, args: dict[str, Any], actor: str) -> Any:
    runs = RunService(artifact_root=root)
    review = ResultReview(runs)
    action = name.removeprefix("ofag.")
    if action == "survey_coverage":
        from ofag.services.survey_coverage import project_coverage

        coverage = project_coverage(root.parent)
        return {
            "crs": coverage.crs,
            "datasets": {
                name: {
                    "stations": len(points),
                    "min_xy_m": points.min(axis=0).tolist(),
                    "max_xy_m": points.max(axis=0).tolist(),
                }
                for name, points in coverage.stations.items()
            },
            "unavailable": coverage.unavailable,
            "note": "Station coverage does not establish geological resolution.",
        }
    if action == "describe_model":
        from ofag.agent.volumes import CellGridSpec
        from ofag.core.schemas import UnitRule

        return {
            "grid": CellGridSpec.model_json_schema(),
            "rule": UnitRule.model_json_schema(),
            "sections": {
                "batch": {"run_id": "UUID", "chi_squared_at_most": 2.0, "as_resistivity": True},
                "single_sounding": {"run_id": "UUID", "location_m": [0.0, 0.0]},
                "mesh_2d": {
                    "run_id": "UUID",
                    "profile": {
                        "origin_easting_m": 0.0,
                        "origin_northing_m": 0.0,
                        "azimuth_degrees": 0.0,
                        "elevation_offset_m": 0.0,
                    },
                },
                "mesh_3d": {"run_id": "UUID"},
            },
            "requirements": [
                "Examples show field names only: use measured project coordinates.",
                "2D profile azimuth is clockwise from north; local x is distance along it.",
                "Mesh threshold rules require an explicit reach_m support radius.",
                "Layered values default to resistivity; mesh values keep artifact units.",
                "Historical sources require adoption, diagnosis and independent audit.",
                "Use depth_band_m from resolution evidence; fit alone is not resolution.",
            ],
        }
    if action == "prepare_run":
        original = runs.get(UUID(args["source_run_id"])).spec
        changes = args["changes"]
        if any(key in changes for key in ("run_id", "project_id", "plugin_id", "engine")):
            raise ValueError(
                "A reused draft retains its project and method; identity changes are not allowed."
            )

        def merge(base: Any, update: Any) -> Any:
            if isinstance(base, dict) and isinstance(update, dict):
                return {
                    key: merge(base.get(key), update[key]) if key in update else value
                    for key, value in (base | update).items()
                }
            return update

        payload = merge(original.model_dump(mode="json"), changes)
        draft = reuse_spec(original, **{k: v for k, v in payload.items() if k != "run_id"})
        path = root / "drafts" / f"{draft.run_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
        return {
            "run_id": str(draft.run_id),
            "source_run_id": str(original.run_id),
            "changed_fields": sorted(changes),
            "saved_to": str(path.resolve()),
        }
    if action in {"inspect_run", "reuse_run", "select_result", "adopt_run", "cancel_run"}:
        run_id = UUID(args["run_id"])
        try:
            record = runs.get(run_id)
        except KeyError:
            path = root / "drafts" / f"{run_id}.json"
            if action not in {"inspect_run", "reuse_run"} or not path.is_file():
                raise
            spec = RunSpec.model_validate_json(path.read_text("utf-8"))
            if action == "reuse_run":
                return {
                    "source_run_id": str(run_id),
                    "spec": reuse_spec(spec).model_dump(mode="json"),
                }
            return {
                "run_id": str(run_id),
                "state": "draft",
                "error": None,
                "quality": "No result",
                "audit": "Not audited",
                "artifacts": [],
                "summary": {},
                "spec": spec.model_dump(mode="json"),
                "note": "Saved configuration only; this draft has not been executed.",
            }
        if action == "reuse_run":
            return {
                "source_run_id": str(run_id),
                "spec": reuse_spec(record.spec).model_dump(mode="json"),
            }
        if action == "select_result":
            review.choose(run_id)
            return {"run_id": str(run_id), "selected": True, "audit": review.audit_status(run_id)}
        if action == "cancel_run":
            return {"run_id": str(run_id), "state": runs.cancel(run_id).state.value}
        result = runs.result(run_id)
        if action == "adopt_run":
            from ofag.agent.obligations import Ledger, Stage

            evidence = str(args["evidence"]).strip()
            if not evidence or record.state is not RunState.SUCCEEDED or result is None:
                raise ValueError("A completed result and source evidence are required.")
            for artifact in result.artifacts:
                artifact_path = (root / artifact.relative_path).resolve()
                if not artifact_path.is_relative_to(root.resolve()) or not artifact_path.is_file():
                    raise ValueError(f"Artifact is unavailable: {artifact.relative_path}")
            ledger = Ledger(root / "obligations.jsonl")
            fingerprint = spec_fingerprint(record.spec)
            if ledger.has(Stage.VETOED, fingerprint):
                raise ValueError("Veto stands. Historical adoption cannot clear it.")
            execution = ledger.current(Stage.EXECUTED, fingerprint)
            adoption = ledger.current(Stage.ADOPTED, fingerprint)
            if (execution is None or not execution.by) and adoption is None:
                ledger.discharge(Stage.ADOPTED, fingerprint, evidence, by=actor)
            return {"run_id": str(run_id), "adopted": True, "audit": review.audit_status(run_id)}
        return {
            "run_id": str(run_id),
            "state": record.state.value,
            "error": record.error,
            "quality": quality_summary(dict(result.summary)) if result else "No result",
            "audit": review.audit_status(run_id),
            "artifacts": [a.model_dump(mode="json") for a in result.artifacts] if result else [],
            "summary": dict(result.summary) if result else {},
            # Large station arrays may exceed the model's tool-output limit.
            "spec": record.spec.model_dump(mode="json"),
        }
    if action in {"list_models", "model_recipe"}:
        from ofag.services.unit_models import find_unit_models, load_unit_model

        paths = find_unit_models(root.parent)
        if action == "model_recipe":
            model_path = next((p for p in paths if p.stem == args["model_id"]), None)
            recipe = model_path.with_suffix(".recipe.json") if model_path else None
            return {
                "model_id": args["model_id"],
                "recipe": json.loads(recipe.read_text("utf-8"))
                if recipe and recipe.exists()
                else None,
                "note": "Legacy models without recipes must be rebuilt from their source workflow.",
            }
        models = []
        for path in paths:
            model = load_unit_model(path, root.parent)
            models.append(
                {
                    "model_id": path.stem,
                    "name": model.name,
                    "cells": model.cells,
                    "shares": model.shares(),
                    "geometry_from": model.geometry_from,
                    "recipe_available": path.with_suffix(".recipe.json").is_file(),
                }
            )
        return models
    if action == "export_report":
        lines = [f"# {root.parent.name}", "", "## Runs", ""]
        for record in runs.list_runs():
            result = runs.result(record.spec.run_id)
            lines.extend(
                [
                    f"### {record.spec.label or record.spec.run_id}",
                    "",
                    f"- Run: {record.spec.run_id}",
                    f"- Dataset: {record.spec.dataset.name}",
                    f"- State: {record.state.value}",
                    "- Quality: "
                    + (quality_summary(dict(result.summary)) if result else "No result"),
                    f"- Audit: {review.audit_status(record.spec.run_id)}",
                    f"- Selected: {review.preferred(record.spec.run_id)}",
                    "",
                ]
            )
        lines += [
            "## Models",
            "",
            "```json",
            json.dumps(handle(root, "ofag.list_models", {}, actor), ensure_ascii=False, indent=2),
            "```",
            "",
        ]
        destination = root / "reports" / f"review-{uuid4()}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(lines), encoding="utf-8")
        return {"saved_to": str(destination.resolve()), "report_id": destination.stem}
    raise KeyError(name)
