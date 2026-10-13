"""Make a self-contained copy of one project for another computer."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from ofag.execution.state import IN_FLIGHT_STATES
from ofag.services.project_folder import ProjectFolder
from ofag.services.project_paths import (
    LOCATION_MARKER,
    project_document_paths,
    repair_project_paths,
    rewrite_project_documents,
)
from ofag.services.run_service import RunService


def export_portable_project(source: ProjectFolder, destination_root: Path) -> Path:
    """Copy internal assets and every referenced external file into one folder."""
    original = source.root.resolve()
    if any(
        record.state in IN_FLIGHT_STATES
        for record in RunService(artifact_root=source.runs_root).list_runs()
    ):
        raise ValueError("finish or cancel active runs before exporting the project")
    parent = destination_root.resolve()
    if parent.is_relative_to(original):
        raise ValueError("export destination cannot be inside the project being copied")
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / source.name_on_disk
    if destination.exists():
        raise FileExistsError(f"export destination already exists: {destination}")
    staging = parent / f".{source.name_on_disk}.export-{uuid4().hex}"
    if not staging.resolve().is_relative_to(parent):
        raise ValueError("export staging path escaped the destination directory")
    published_here = False
    try:
        shutil.copytree(source.root, staging)
        copied = ProjectFolder(staging)
        repair_project_paths(copied)
        marker = json.loads((staging / LOCATION_MARKER).read_text(encoding="utf-8"))
        if marker.get("root") != str(staging.resolve()):
            raise ValueError("project has missing internal files; export cannot be completed")
        external = _external_references(copied)
        replacements: dict[str, str] = {}
        for path in external:
            digest = hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()[:16]
            target = copied.imports_root / "external" / digest / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if path.is_dir():
                shutil.copytree(path, target)
            else:
                shutil.copy2(path, target)
            replacements[path.as_posix()] = target.resolve().as_posix()
        rewrite_project_documents(copied, lambda data: _replace(data, replacements))
        staging.replace(destination)
        published_here = True
        published = ProjectFolder(destination)
        repair_project_paths(published)
        return destination
    except Exception:
        if staging.is_dir():
            shutil.rmtree(staging)
        # Only remove the directory this invocation published, never a pre-existing
        # recipient project.
        if published_here and destination.resolve().parent == parent and destination.is_dir():
            shutil.rmtree(destination)
        raise


def _external_references(folder: ProjectFolder) -> tuple[Path, ...]:
    found: set[Path] = set()
    root = folder.root.resolve()
    for document in project_document_paths(folder):
        raw = document.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) if document.suffix == ".yaml" else json.loads(raw)
        for value in _strings(data):
            path = Path(value)
            if not path.is_absolute():
                continue
            resolved = path.resolve()
            if resolved.is_relative_to(root):
                continue
            if not resolved.exists():
                raise FileNotFoundError(f"referenced external path is missing: {resolved}")
            if resolved == Path(resolved.anchor):
                raise ValueError(f"refusing to copy a drive root: {resolved}")
            if resolved.is_dir() and root.is_relative_to(resolved):
                raise ValueError(
                    f"external directory contains the export staging folder: {resolved}"
                )
            found.add(resolved)
    return tuple(sorted(found))


def _strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(item for nested in value.values() for item in _strings(nested))
    if isinstance(value, list):
        return tuple(item for nested in value for item in _strings(nested))
    return (value,) if isinstance(value, str) else ()


def _replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, str):
        path = Path(value)
        if path.is_absolute():
            return replacements.get(path.resolve().as_posix(), value)
    return value
