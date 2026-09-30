"""The project catalogue, as directories a person can find."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ofag.core.schemas import (
    DatasetKind,
    ProjectCreateRequest,
    ProjectDataset,
    ProjectMethodsUpdate,
    ProjectRecord,
    ProjectWorkspace,
    ProjectWorkspaceUpdate,
)
from ofag.services.project_export import export_portable_project
from ofag.services.project_folder import (
    DEFAULT_RESULT_ROOT,
    ProjectFolder,
    folders_in,
    unique_folder,
)
from ofag.services.project_paths import repair_project_paths


class ProjectService:
    """Store independent project records without coupling them to a solver backend."""

    def __init__(self, root: Path = DEFAULT_RESULT_ROOT) -> None:
        self._root = root

    @property
    def result_root(self) -> Path:
        return self._root

    def list(self) -> tuple[ProjectRecord, ...]:
        records: list[ProjectRecord] = []
        for folder in folders_in(self._root):
            try:
                records.append(
                    ProjectRecord.model_validate_json(
                        folder.record_path.read_text(encoding="utf-8")
                    )
                )
            except (OSError, ValueError):
                continue
        return tuple(sorted(records, key=lambda record: record.updated_at, reverse=True))

    def folder(self, project_id: UUID) -> ProjectFolder:
        """Where this project keeps everything, which is what the rest needs."""
        for folder in folders_in(self._root):
            try:
                record = ProjectRecord.model_validate_json(
                    folder.record_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                continue
            if record.project_id == project_id:
                repair_project_paths(folder)
                return folder
        raise KeyError(f"project {project_id} does not exist")

    def get(self, project_id: UUID) -> ProjectRecord:
        folder = self.folder(project_id)
        return ProjectRecord.model_validate_json(folder.record_path.read_text(encoding="utf-8"))

    def export_portable(self, project_id: UUID, destination_root: Path) -> Path:
        """Make an independent copy including referenced external inputs."""
        return export_portable_project(self.folder(project_id), destination_root)

    def create(self, request: ProjectCreateRequest) -> ProjectRecord:
        record = ProjectRecord(**request.model_dump())
        folder = unique_folder(self._root, record.name).create()
        self._write(folder, record)
        repair_project_paths(folder)
        return record

    def update_methods(self, project_id: UUID, update: ProjectMethodsUpdate) -> ProjectRecord:
        previous = self.get(project_id)
        record = ProjectRecord(
            project_id=previous.project_id,
            name=previous.name,
            coordinate_convention=previous.coordinate_convention,
            elevation_reference=previous.elevation_reference,
            enabled_methods=update.enabled_methods,
            created_at=previous.created_at,
            updated_at=datetime.now(UTC),
        )
        self._persist(record)
        return record

    def workspace(self, project_id: UUID) -> ProjectWorkspace:
        """Load the project's durable data and mesh assets, creating an empty view if needed."""
        path = self.folder(project_id).workspace_path
        if not path.is_file():
            return ProjectWorkspace(project_id=project_id)
        stored = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(stored, dict) and "datasets" not in stored:
            stored = _migrate_single_slot_workspace(project_id, stored)
        return ProjectWorkspace.model_validate(stored)

    def update_workspace(
        self, project_id: UUID, update: ProjectWorkspaceUpdate
    ) -> ProjectWorkspace:
        folder = self.folder(project_id)
        workspace = ProjectWorkspace(project_id=project_id, **update.model_dump())
        _write_atomically(folder.workspace_path, workspace.model_dump_json(indent=2))
        return workspace

    def register_dataset(
        self,
        project_id: UUID,
        *,
        kind: DatasetKind,
        name: str,
        source_filename: str,
        imported: Any,
    ) -> ProjectDataset:
        """Put an import on the project's register, so every stage and agent sees it."""
        from dataclasses import asdict, is_dataclass

        if isinstance(imported, dict):
            raw = imported
        elif hasattr(imported, "model_dump"):
            raw = imported.model_dump(mode="json")
        elif is_dataclass(imported) and not isinstance(imported, type):
            raw = asdict(imported)
        else:
            raise TypeError(f"cannot register {type(imported).__name__} as a dataset payload")
        payload = json.loads(json.dumps(raw, default=str))
        dataset_id = UUID(str(payload.get("dataset_id") or uuid4()))
        payload["dataset_id"] = str(dataset_id)
        workspace = self.workspace(project_id)
        for existing in workspace.datasets:
            if existing.dataset_id == dataset_id:
                return existing
        dataset = ProjectDataset(
            dataset_id=dataset_id,
            name=name[:120] or source_filename[:120] or kind.value,
            kind=kind,
            source_filename=source_filename or name or kind.value,
            payload=payload,
        )
        stored = workspace.model_copy(update={"datasets": (*workspace.datasets, dataset)})
        values = stored.model_dump()
        self.update_workspace(
            project_id,
            ProjectWorkspaceUpdate.model_validate(
                {field: values[field] for field in ProjectWorkspaceUpdate.model_fields}
            ),
        )
        return dataset

    def _persist(self, record: ProjectRecord) -> None:
        self._write(self.folder(record.project_id), record)

    @staticmethod
    def _write(folder: ProjectFolder, record: ProjectRecord) -> None:
        folder.create()
        _write_atomically(folder.record_path, record.model_dump_json(indent=2))


def _write_atomically(path: Path, text: str) -> None:
    """Written beside and renamed over, so a crash leaves the old one intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


#: The single-slot fields a workspace used before a project could hold more than one
#: dataset per method.
_LEGACY_DATASET_SLOTS: tuple[tuple[str, DatasetKind], ...] = (
    ("gravity_dataset", DatasetKind.GRAVITY),
    ("magnetic_dataset", DatasetKind.MAGNETICS),
    ("aem_dataset", DatasetKind.AEM),
    ("topography_dataset", DatasetKind.TOPOGRAPHY),
)

_LEGACY_MESH_SLOTS: tuple[tuple[str, str], ...] = (
    ("gravity_mesh", "gravity"),
    ("magnetic_mesh", "magnetics"),
)


def _migrate_single_slot_workspace(project_id: UUID, stored: dict[str, Any]) -> dict[str, Any]:
    """Read a workspace written when each method had exactly one dataset slot."""
    datasets: list[dict[str, Any]] = []
    active: dict[str, str] = {}
    for field, kind in _LEGACY_DATASET_SLOTS:
        payload = stored.get(field)
        if not isinstance(payload, dict):
            continue
        dataset_id = str(payload.get("dataset_id") or uuid4())
        filename = str(payload.get("source_filename") or f"{kind.value}.csv")
        datasets.append(
            {
                "dataset_id": dataset_id,
                "name": filename,
                "kind": kind.value,
                "source_filename": filename,
                "payload": payload,
            }
        )
        active[kind.value] = dataset_id

    meshes: list[dict[str, Any]] = []
    for field, source_method in _LEGACY_MESH_SLOTS:
        mesh = stored.get(field)
        if isinstance(mesh, dict):
            meshes.append({**mesh, "source_method": mesh.get("source_method", source_method)})

    migrated = {
        "project_id": str(project_id),
        "datasets": datasets,
        "active_dataset_ids": active,
        "meshes": meshes,
    }
    if "updated_at" in stored:
        migrated["updated_at"] = stored["updated_at"]
    return migrated
