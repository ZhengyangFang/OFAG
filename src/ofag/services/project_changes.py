"""Small, factual change summaries for project operations."""

import json
import re
from pathlib import Path
from typing import Any
from uuid import UUID


def related_records(value: Any) -> list[dict[str, str]]:
    found: dict[tuple[str, str], dict[str, str]] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                if key == "model_id" and isinstance(nested, str):
                    # Saved model identifiers include legacy filename stems, not just UUIDs.
                    if re.fullmatch(r"[\w-][\w.-]*", nested) and ".." not in nested:
                        found[key, nested] = {"kind": key, "id": nested}
                elif key in ("run_id", "dataset_id"):
                    try:
                        identifier = str(UUID(str(nested)))
                        found[key, identifier] = {"kind": key, "id": identifier}
                    except ValueError:
                        pass
                elif isinstance(nested, (dict, list)):
                    visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(value)
    return list(found.values())[:20]


def configuration_snapshot(runs_root: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    paths = [
        runs_root.parent / "workspace.json",
        runs_root / "preferred_results.json",
        *runs_root.glob("*/run_record.json"),
        *runs_root.glob("models/*.recipe.json"),
        *runs_root.glob("drafts/*.json"),
    ]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Progress is not a configuration change.
            if path.name == "run_record.json":
                data = data["spec"]
            elif isinstance(data, dict):
                data.pop("updated_at", None)
            snapshot[path.relative_to(runs_root.parent).as_posix()] = data
        except (OSError, ValueError, KeyError):
            continue
    return snapshot


def configuration_changes(before: Any, after: Any, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            changes.extend(
                configuration_changes(before.get(key), after.get(key), f"{prefix}/{key}")
            )
        return changes

    def shown(value: Any) -> str:
        text = json.dumps(value, ensure_ascii=False, default=str)
        return text if len(text) <= 240 else text[:240] + "... (see saved record)"

    return [f"{prefix}: {shown(before)} -> {shown(after)}"]
