"""Fail a release if private inputs or non-runtime reports enter the wheel."""

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


def _local_only(name: str) -> bool:
    parts = set(Path(name).parts)
    return bool(
        parts
        & {"paper", "data", "Result", "artifacts", ".claude", "dist", ".venv", "local_private"}
        or "/examples/Figure/" in f"/{name}"
        or "/benchmark/results/" in f"/{name}"
        or name.endswith(".ipynb")
        or name.endswith((".docx", ".pptx", ".pdf", ".pem", ".key", ".p12", ".pfx"))
        or Path(name).name.startswith(".env")
        or Path(name).name in {"agent_settings.json", "credentials.json"}
    )


def check(path: Path) -> list[str]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            names = set(wheel.namelist())
        problems = [f"missing runtime resource: {name}" for name in sorted(REQUIRED - names)]
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as source:
            names = {member.name for member in source.getmembers() if member.isfile()}
        problems = []
    else:
        return [f"unsupported release archive: {path.name}"]
    for name in sorted(names):
        if _local_only(name):
            problems.append(f"unexpected release file: {name}")
    return problems


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: check_wheel_contents.py WHEEL [SOURCE_ARCHIVE]")
    failures = [problem for argument in sys.argv[1:] for problem in check(Path(argument))]
    if failures:
        raise SystemExit("Release archive contents failed:\n- " + "\n- ".join(failures))
    print("Release archives contain required runtime resources and no local-only material.")
