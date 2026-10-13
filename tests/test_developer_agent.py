"""The Developer Agent changes source only in a checked Git worktree."""

import subprocess
from pathlib import Path

import pytest

from ofag.agent.developer import handle
from ofag.agent.dispatch import ToolError
from ofag.agent.orchestrator import DELEGABLE
from ofag.agent.roles import Role, dispatcher_for


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture
def source_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "source"
    (repo / "src/ofag").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "src/ofag/__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("local_private/\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        '[tool.mypy]\nfiles = ["src/ofag"]\n', encoding="utf-8"
    )
    _git(repo, "init", "-b", "main")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "Base",
    )
    monkeypatch.chdir(repo)
    return repo


def test_developer_source_writes_require_local_opt_in(
    source_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OFAG_DEVELOPER_WRITE_ENABLED", raising=False)
    with pytest.raises(ToolError, match="disabled"):
        handle(source_repo, "prepare", {})
    assert not (source_repo / "local_private" / "developer_worktrees").exists()


def test_developer_role_can_be_delegated_without_audit_tools(tmp_path: Path) -> None:
    assert Role.DEVELOPER in DELEGABLE
    names = {tool.name for tool in dispatcher_for(Role.DEVELOPER, tmp_path).manifest()}
    assert {"ofag.developer_prepare", "ofag.developer_check", "ofag.developer_finish"} <= names
    assert "ofag.audit" not in names


def test_developer_branch_isolated_and_checked(
    source_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OFAG_DEVELOPER_WRITE_ENABLED", "1")
    prepared = handle(source_repo, "prepare", {})
    identifier = prepared["workspace_id"]
    worktree = Path(prepared["path"])
    assert prepared["branch"].startswith("codex/")

    with pytest.raises(ToolError, match="limited"):
        handle(
            source_repo,
            "patch",
            {"workspace_id": identifier, "path": "paper/main.tex", "old": "", "new": "x"},
        )
    handle(
        source_repo,
        "patch",
        {
            "workspace_id": identifier,
            "path": "src/ofag/__init__.py",
            "old": "VALUE = 1",
            "new": "VALUE = 2",
        },
    )
    handle(
        source_repo,
        "patch",
        {
            "workspace_id": identifier,
            "path": "tests/test_value.py",
            "old": "",
            "new": "from ofag import VALUE\n\n\ndef test_value():\n    assert VALUE == 2\n",
        },
    )
    assert (source_repo / "src/ofag/__init__.py").read_text("utf-8") == "VALUE = 1\n"
    assert "VALUE = 2" in handle(
        source_repo,
        "read",
        {"workspace_id": identifier, "path": "src/ofag/__init__.py"},
    )["content"]
    with pytest.raises(ToolError, match="must pass"):
        handle(source_repo, "finish", {"workspace_id": identifier, "summary": "Change value"})

    checked = handle(source_repo, "check", {"workspace_id": identifier})
    assert {name: result["passed"] for name, result in checked["checks"].items()} == {
        "ruff": True,
        "mypy": True,
        "pytest": True,
    }
    finished = handle(
        source_repo, "finish", {"workspace_id": identifier, "summary": "Change value"}
    )
    assert finished["branch"] == prepared["branch"]
    assert _git(worktree, "rev-list", "--count", "HEAD") == "2"
    assert (source_repo / "src/ofag/__init__.py").read_text("utf-8") == "VALUE = 1\n"
