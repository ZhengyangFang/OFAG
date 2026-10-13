"""Isolated source changes for the Developer Agent."""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from ofag.agent.dispatch import ToolError

_WORKSPACE_ID = re.compile(r"[0-9a-f]{32}\Z")
_ALLOWED_ROOTS = (Path("src/ofag"), Path("tests"))
_MAX_FILE_BYTES = 128_000


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise ToolError(result.stderr.strip() or result.stdout.strip() or "Git failed")
    return result.stdout.rstrip()


def _repo_root() -> Path:
    root = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    if not (root / "src" / "ofag").is_dir():
        raise ToolError("Start OFAG from its source checkout to use the Developer Agent.")
    if _git(root, "ls-files", "paper"):
        raise ToolError("The source checkout tracks paper files; Developer worktrees are disabled.")
    return root


def _enabled() -> None:
    if os.environ.get("OFAG_DEVELOPER_WRITE_ENABLED") != "1":
        raise ToolError(
            "Developer source changes are disabled. Set OFAG_DEVELOPER_WRITE_ENABLED=1 "
            "before starting OFAG to enable isolated worktrees."
        )


def _record_path(repo: Path, workspace_id: str) -> Path:
    if not _WORKSPACE_ID.fullmatch(workspace_id):
        raise ToolError("Invalid developer workspace ID.")
    return repo / "local_private" / "developer_worktrees" / f"{workspace_id}.json"


def _workspace(repo: Path, workspace_id: str) -> tuple[Path, dict[str, Any]]:
    record_path = _record_path(repo, workspace_id)
    if not record_path.is_file():
        raise ToolError("No developer workspace has this ID.")
    record: dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
    path = repo / "local_private" / "developer_worktrees" / workspace_id
    if not path.is_dir() or Path(record["path"]).resolve() != path.resolve():
        raise ToolError("The developer worktree is missing or has moved.")
    if Path(_git(path, "rev-parse", "--show-toplevel")).resolve() != path.resolve():
        raise ToolError("The developer workspace is not its recorded Git worktree.")
    return path, record


def _source_path(worktree: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ToolError("Use a relative source or test path without '..'.")
    if not any(relative == root or root in relative.parents for root in _ALLOWED_ROOTS):
        raise ToolError("Developer edits are limited to src/ofag/ and tests/.")
    if relative.suffix != ".py":
        raise ToolError("Developer edits are limited to Python source and tests.")
    path = worktree / relative
    if not path.resolve().is_relative_to(worktree.resolve()):
        raise ToolError("The source path leaves the developer worktree.")
    ancestors = (part for part in (path, *path.parents) if part.is_relative_to(worktree))
    if any(part.is_symlink() for part in ancestors):
        raise ToolError("Developer edits cannot follow symbolic links.")
    return path


def _changed(worktree: Path) -> list[str]:
    listed = _git(worktree, "status", "--porcelain", "--untracked-files=all")
    names: list[str] = []
    for line in listed.splitlines():
        name = line[3:]
        if " -> " in name or name.startswith('"'):
            raise ToolError("Rename or quoted paths need manual review.")
        _source_path(worktree, name)
        names.append(name)
    return names


def _fingerprint(worktree: Path) -> str:
    digest = hashlib.sha256()
    for name in sorted(_changed(worktree)):
        path = _source_path(worktree, name)
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.is_file() else b"<deleted>")
    return digest.hexdigest()


def _save(repo: Path, workspace_id: str, record: dict[str, Any]) -> None:
    path = _record_path(repo, workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def handle(artifact_root: Path, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one developer operation in a private Git worktree."""
    del artifact_root
    _enabled()
    repo = _repo_root()
    if action == "prepare":
        workspace_id = uuid4().hex
        branch = f"codex/ofag-developer-{workspace_id[:12]}"
        path = repo / "local_private" / "developer_worktrees" / workspace_id
        path.parent.mkdir(parents=True, exist_ok=True)
        base = _git(repo, "rev-parse", "HEAD")
        dirty = bool(_git(repo, "status", "--porcelain"))
        _git(repo, "worktree", "add", "-b", branch, str(path), base)
        record: dict[str, Any] = {
            "path": str(path.resolve()),
            "branch": branch,
            "base": base,
            "checks": {},
        }
        _save(repo, workspace_id, record)
        return {
            "workspace_id": workspace_id,
            "branch": branch,
            "path": str(path),
            "base": base,
            "uncommitted_checkout_changes_excluded": dirty,
        }

    workspace_id = arguments["workspace_id"]
    worktree, record = _workspace(repo, workspace_id)
    if action == "read":
        path = _source_path(worktree, arguments["path"])
        if not path.is_file():
            raise ToolError("No source file exists at that path.")
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ToolError("This source file is too large for the Developer Agent.")
        return {"path": arguments["path"], "content": path.read_text(encoding="utf-8")}
    if action == "patch":
        path = _source_path(worktree, arguments["path"])
        old, new = arguments["old"], arguments["new"]
        if path.exists():
            current = path.read_text(encoding="utf-8")
            if not old or current.count(old) != 1:
                raise ToolError("The old text must occur exactly once in an existing file.")
            updated = current.replace(old, new, 1)
        else:
            if old:
                raise ToolError("A new file requires empty old text.")
            updated = new
        if len(updated.encode("utf-8")) > _MAX_FILE_BYTES:
            raise ToolError("The updated file exceeds the source size limit.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
        record["checks"] = {}
        _save(repo, workspace_id, record)
        return {"path": arguments["path"], "changed": True}
    if action == "check":
        changed = _changed(worktree)
        if not changed:
            raise ToolError("The developer workspace has no source changes to check.")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(worktree / "src")
        commands = (
            ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests"]),
            ("mypy", [sys.executable, "-m", "mypy"]),
            (
                "pytest",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp=local_private/.test-tmp",
                ],
            ),
        )
        results: dict[str, Any] = {}
        for name, command in commands:
            try:
                result = subprocess.run(
                    command,
                    cwd=worktree,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=1200,
                    check=False,
                )
                results[name] = {
                    "passed": result.returncode == 0,
                    "output": (result.stdout + result.stderr)[-4000:],
                }
            except subprocess.TimeoutExpired:
                results[name] = {"passed": False, "output": "Check timed out."}
            if not results[name]["passed"]:
                break
        record["checks"] = {"fingerprint": _fingerprint(worktree), "results": results}
        _save(repo, workspace_id, record)
        return {"workspace_id": workspace_id, "checks": results}
    if action == "finish":
        summary = arguments["summary"].strip()
        if not summary or len(summary) > 120 or "\n" in summary:
            raise ToolError("Give a one-line commit summary of at most 120 characters.")
        checks = record.get("checks", {})
        results = checks.get("results", {})
        if checks.get("fingerprint") != _fingerprint(worktree) or set(results) != {
            "ruff",
            "mypy",
            "pytest",
        } or not all(item.get("passed") for item in results.values()):
            raise ToolError("Ruff, mypy and pytest must pass on the current source changes.")
        if _git(worktree, "branch", "--show-current") != record["branch"]:
            raise ToolError("The developer worktree is on a different branch.")
        _git(worktree, "add", "--", "src/ofag", "tests")
        _git(
            worktree,
            "-c",
            "user.name=OFAG Developer Agent",
            "-c",
            "user.email=developer@users.noreply.github.com",
            "commit",
            "-m",
            summary,
        )
        commit = _git(worktree, "rev-parse", "HEAD")
        return {"branch": record["branch"], "commit": commit, "worktree": str(worktree)}
    raise ToolError(f"Unknown developer action: {action}")
