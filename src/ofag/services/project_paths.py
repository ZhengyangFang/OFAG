"""Repair references to files inside a project after its directory moves."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ofag.core.schemas import RunSpec, spec_fingerprint
from ofag.services.project_folder import ProjectFolder

LOCATION_MARKER = ".ofag_location.json"


def repair_project_paths(folder: ProjectFolder) -> None:
    """Rebase existing import/run paths once per location, leaving external paths alone."""
    marker = folder.root / LOCATION_MARKER
    current = str(folder.root.resolve())
    previous: str | None = None
    if marker.is_file():
        try:
            stored = json.loads(marker.read_text(encoding="utf-8"))
            previous = stored.get("root") if isinstance(stored, dict) else None
            if not isinstance(previous, str):
                previous = None
            if previous == current:
                return
        except (OSError, ValueError, AttributeError):
            pass

    unresolved: list[str] = []
    rewrite_project_documents(
        folder, lambda data: _rebase(data, folder, previous, unresolved), unresolved
    )
    if not unresolved:
        _write_atomically(marker, json.dumps({"root": current}) + "\n")


def rewrite_project_documents(
    folder: ProjectFolder,
    transform: Callable[[Any], Any],
    unresolved: list[str] | None = None,
) -> None:
    """Rewrite project references and matching checkpoints as one migration."""
    paths = project_document_paths(folder)
    pending: list[tuple[Path, Any, Any]] = []
    fingerprints: dict[Path, tuple[str, str]] = {}
    for path in paths:
        try:
            original = path.read_text(encoding="utf-8")
            data = yaml.safe_load(original) if path.suffix == ".yaml" else json.loads(original)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        repaired = transform(data)
        pending.append((path, data, repaired))
        if path.name == "run_record.json" and repaired != data:
            try:
                old_spec = RunSpec.model_validate(data["spec"])
                new_spec = RunSpec.model_validate(repaired["spec"])
                fingerprints[path.parent] = (spec_fingerprint(old_spec), spec_fingerprint(new_spec))
            except (KeyError, TypeError, ValueError):
                pass
    # Keep every file on the original configuration until all copied assets are present.
    if unresolved:
        return
    # Checkpoints go first and records last.
    order = {
        "checkpoint.json": 0,
        "run_spec.yaml": 1,
        "workspace.json": 2,
        "run_record.json": 3,
    }
    pending.sort(key=lambda item: order.get(item[0].name, 2))
    for path, data, repaired in pending:
        if path.name == "checkpoint.json" and path.parent in fingerprints:
            old, new = fingerprints[path.parent]
            if isinstance(repaired, dict) and repaired.get("spec_fingerprint") == old:
                repaired["spec_fingerprint"] = new
        if repaired == data:
            continue
        serialized = (
            yaml.safe_dump(repaired, sort_keys=True)
            if path.suffix == ".yaml"
            else json.dumps(repaired, indent=2, ensure_ascii=False)
        )
        _write_atomically(path, serialized)


def project_document_paths(folder: ProjectFolder) -> tuple[Path, ...]:
    """Structured files that can contain paths into or outside a project."""
    paths = [folder.workspace_path, folder.root / "case_state.json"]
    paths.extend(folder.runs_root.glob("*/run_record.json"))
    paths.extend(folder.runs_root.glob("*/run_spec.yaml"))
    paths.extend(folder.runs_root.glob("*/checkpoint.json"))
    paths.extend(folder.runs_root.glob("*/result.json"))
    return tuple(path for path in paths if path.is_file())


def _rebase(value: Any, folder: ProjectFolder, previous: str | None, unresolved: list[str]) -> Any:
    if isinstance(value, dict):
        return {key: _rebase(item, folder, previous, unresolved) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase(item, folder, previous, unresolved) for item in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace("\\", "/")
    old_root = previous.replace("\\", "/").rstrip("/") if previous else None
    if old_root is not None and normalized.startswith(old_root + "/"):
        suffix = normalized[len(old_root) + 1 :]
        if suffix and ".." not in Path(suffix).parts:
            candidate = folder.root / suffix
            if candidate.exists():
                return candidate.resolve().as_posix()
            unresolved.append(value)
        return value
    for part in ("imports", "runs"):
        marker = f"/{part}/"
        if marker not in normalized:
            continue
        # Only paths inside this project qualify.
        prefix = normalized.rsplit(marker, 1)[0]
        if old_root is not None:
            if prefix != old_root:
                continue
        elif not Path(value).is_absolute() or Path(prefix).name != folder.root.name:
            continue
        suffix = normalized.rsplit(marker, 1)[1]
        if not suffix or ".." in Path(suffix).parts:
            continue
        candidate = folder.root / part / suffix
        if candidate.exists():
            return candidate.resolve().as_posix()
        unresolved.append(value)
    return value


def _write_atomically(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.relocating")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
