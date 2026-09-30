"""The open project, as the agents see it."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

__all__ = ["ProjectContext", "LESSONS_ARE_NOT_DATA"]

#: Said wherever passages from the corpus reach an agent, because those passages quote
#: other cases' files and numbers and read like findings.
LESSONS_ARE_NOT_DATA = (
    "Passages from ofag.retrieve and ofag.lessons are lessons learned on the field cases "
    "OFAG was built on (Utah FORGE, Cedar Rapids, Llano, Stillwater). They are not data in "
    "the open project, and are never described as its data; ofag.project says what it holds."
)


@dataclass(frozen=True)
class ProjectContext:
    """One project: its record, its workspace and its runs, read from disk."""

    folder: Path
    project_id: UUID

    @classmethod
    def find(cls, runs_root: Path) -> "ProjectContext | None":
        """The project a runs folder belongs to, or None if it belongs to none."""
        record = Path(runs_root).parent / "project.json"
        if not record.is_file():
            return None
        try:
            identifier = UUID(str(json.loads(record.read_text("utf-8"))["project_id"]))
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return cls(folder=record.parent, project_id=identifier)

    def summary(self) -> dict[str, Any]:
        """What the project is and holds, for the `ofag.project` tool."""
        from ofag.core.schemas import ProjectRecord
        from ofag.services.project_service import ProjectService
        from ofag.services.result_review import ResultReview
        from ofag.services.run_service import RunService

        record = ProjectRecord.model_validate_json(
            (self.folder / "project.json").read_text("utf-8")
        )
        workspace = ProjectService(root=self.folder.parent).workspace(self.project_id)
        run_service = RunService(artifact_root=self.folder / "runs")
        runs = run_service.list_runs()
        return {
            "name": record.name,
            "project_id": str(self.project_id),
            "folder": self.folder.resolve().as_posix(),
            "crs": record.coordinate_convention.crs,
            "elevation_reference": record.elevation_reference,
            "methods": [str(m) for m in record.enabled_methods],
            "datasets": [
                {
                    "dataset_id": str(d.dataset_id),
                    "name": d.name,
                    "kind": str(d.kind),
                    "source_file": d.source_filename,
                    "imported_at": d.imported_at.isoformat(timespec="seconds"),
                }
                for d in workspace.datasets
            ],
            "runs": [
                {
                    "run_id": str(r.spec.run_id),
                    "label": r.spec.label,
                    "dataset": r.spec.dataset.name,
                    "source_dataset_ids": [str(value) for value in r.spec.source_dataset_ids],
                    "plugin": r.spec.plugin_id,
                    "state": getattr(r.state, "value", str(r.state)),
                }
                for r in runs
            ],
            "meshes": len(workspace.meshes),
            "geological_models": len(workspace.geology),
            "preferred_results": ResultReview(run_service).selections(),
            "note": LESSONS_ARE_NOT_DATA,
        }

    def as_brief(self) -> str:
        """The same, as a few lines an agent starts with."""
        facts = self.summary()
        datasets = facts["datasets"]
        runs = facts["runs"]
        lines = [
            "## The open project",
            "",
            f"**{facts['name']}** -- {facts['crs']}, elevations {facts['elevation_reference']}, "
            f"methods: {', '.join(facts['methods'])}.",
            f"{len(datasets)} imported datasets and {len(runs)} runs. "
            "Call ofag.project for the list; answer questions about this project from it.",
        ]
        for dataset in datasets[:8]:
            lines.append(
                f"- dataset `{dataset['name']}` ({dataset['kind']}, from {dataset['source_file']})"
            )
        if len(datasets) > 8:
            lines.append(f"- ... and {len(datasets) - 8} more")
        lines += ["", LESSONS_ARE_NOT_DATA]
        return "\n".join(lines) + "\n"
