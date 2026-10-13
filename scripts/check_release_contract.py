"""Check the files selected for the public source release."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "README.md",
    "LICENSE",
    "pyproject.toml",
    "docs/agent_validation_and_debugging.md",
    "docs/lessons/lessons.yaml",
    "docs/release_scope.md",
}
PRIVATE_ROOTS = {"paper", "data", "Result", "artifacts", "examples", "local_private"}
PRIVATE_FILES = {".env", "credentials.json", "agent_settings.json"}
PRIVATE_PATHS = {"src/ofag/agent/retrospect.py", "tests/test_edi.py"}
PRIVATE_SUFFIXES = {".ipynb", ".pptx", ".docx", ".pdf", ".pem", ".key", ".p12", ".pfx"}
PRIVATE_MARKER = re.compile(r"\bF\d{3}\b|\bFRG\d+\b")


def check() -> list[str]:
    problems = [
        f"missing public resource: {name}"
        for name in sorted(REQUIRED)
        if not (ROOT / name).is_file()
    ]
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="surrogateescape")
    for name in filter(None, listed.split("\0")):
        relative = Path(name)
        parts = relative.parts
        if (
            parts[0] in PRIVATE_ROOTS
            or relative.name in PRIVATE_FILES
            or relative.name.startswith(".env")
            or relative.as_posix() in PRIVATE_PATHS
        ):
            problems.append(f"private path in source release: {relative.as_posix()}")
        if relative.suffix.lower() in PRIVATE_SUFFIXES:
            problems.append(f"private file type in source release: {relative.as_posix()}")
        if parts[0] == "docs" and len(parts) > 1 and parts[1] in {"data_sources", "cases"}:
            problems.append(f"case documentation in source release: {relative.as_posix()}")
        case_prefixes = ("case1_", "case2_", "case3_", "case_audit")
        if parts[0] == "docs" and relative.name.startswith(case_prefixes):
            problems.append(f"case record in source release: {relative.as_posix()}")
        if parts[0] in {"src", "tests"} and relative.suffix == ".py":
            content = (ROOT / relative).read_text(encoding="utf-8")
            if PRIVATE_MARKER.search(content):
                problems.append(f"research identifier in public code: {relative.as_posix()}")
    corpus = (ROOT / "docs/lessons/lessons.yaml").read_text(encoding="utf-8")
    if "tier: synthetic" not in corpus or "tier: measured" in corpus:
        problems.append("the public lesson corpus is not synthetic-only")
    return problems


if __name__ == "__main__":
    failures = check()
    if failures:
        raise SystemExit("Public source check failed:\n- " + "\n- ".join(failures))
    print("Public source scope passed.")
