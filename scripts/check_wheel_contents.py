"""Check wheel and source archives for public-release scope."""

import sys
import tarfile
import zipfile
from pathlib import Path

REQUIRED = {
    "ofag/_resources/docs/agent_validation_and_debugging.md",
    "ofag/_resources/docs/lessons/lessons.yaml",
    "ofag/_resources/docs/development/benchmark/judgement.yaml",
    "ofag/_resources/docs/development/benchmark/silent.yaml",
}
PRIVATE_ROOTS = {"paper", "data", "Result", "artifacts", "examples", "local_private"}
PRIVATE_SUFFIXES = {".ipynb", ".pptx", ".docx", ".pdf", ".pem", ".key", ".p12", ".pfx"}


def _private(name: str) -> bool:
    parts = Path(name).parts
    return bool(
        set(parts) & PRIVATE_ROOTS
        or Path(name).suffix.lower() in PRIVATE_SUFFIXES
        or Path(name).name.startswith(".env")
        or Path(name).name in {"credentials.json", "agent_settings.json"}
        or any(part.startswith(("case1_", "case2_", "case3_", "case_audit")) for part in parts)
    )


def check(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            names = set(wheel.namelist())
        problems = [f"missing wheel resource: {name}" for name in sorted(REQUIRED - names)]
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as source:
            names = {member.name for member in source.getmembers() if member.isfile()}
        problems = []
    else:
        return [f"unsupported archive: {path.name}"]
    problems.extend(f"private archive member: {name}" for name in sorted(names) if _private(name))
    return problems


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: check_wheel_contents.py WHEEL [SOURCE_ARCHIVE]")
    failures = [problem for argument in sys.argv[1:] for problem in check(Path(argument))]
    if failures:
        raise SystemExit("Archive check failed:\n- " + "\n- ".join(failures))
    print("Public archives passed.")
