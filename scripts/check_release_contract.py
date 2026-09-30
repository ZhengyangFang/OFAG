"""Check the source-to-case-to-figure map without requiring field datasets."""

import ast
import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "Utah FORGE": "case1_forge.py",
    "Cedar Rapids": "case2_cedar_rapids.py",
    "Llano": "case3_llano.py",
}
NOTEBOOKS = tuple(f"Fig{number}.ipynb" for number in range(2, 9))
LOCAL_ONLY_ROOTS = {
    "paper",
    "data",
    "Result",
    "artifacts",
    "dist",
    ".claude",
    ".venv",
    ".release-smoke",
    "local_private",
}
LOCAL_ONLY_SUFFIXES = (".docx", ".pptx", ".pdf", ".pem", ".key", ".p12", ".pfx")


def _check_public_paths() -> list[str]:
    """Inspect files Git would publish, including not-yet-staged new files."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8", errors="surrogateescape")
    problems = []
    for name in filter(None, listed.split("\0")):
        path = Path(name)
        if (
            path.parts[0] in LOCAL_ONLY_ROOTS
            or path.parts[:2] == ("examples", "Figure")
            or path.suffix.lower() in LOCAL_ONLY_SUFFIXES
            or path.name.startswith(".env")
            or path.name in {"agent_settings.json", "credentials.json"}
        ):
            problems.append(f"local-only material would enter Git: {name}")
    return problems


def _stages(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "STAGES" for target in node.targets
        ):
            if not isinstance(node.value, ast.Dict):
                break
            return {key.value for key in node.value.keys if isinstance(key, ast.Constant)}
    raise ValueError(f"{path} has no static STAGES map")


def check() -> list[str]:
    problems: list[str] = _check_public_paths()
    guide = (ROOT / "docs/reproducibility.md").read_text(encoding="utf-8")
    for case, script in CASES.items():
        row = next(
            (
                line
                for line in guide.splitlines()
                if line.startswith(f"| {case} |") and f"scripts/{script}" in line
            ),
            "",
        )
        if not row or script not in row:
            problems.append(f"reproduction guide has no stage row for {case}")
            continue
        listed = re.findall(r"`([a-z][a-z0-9_]*)`", row.split(" in `scripts/")[0])
        available = _stages(ROOT / "scripts" / script)
        if missing := sorted(set(listed) - available):
            problems.append(f"{case}: documented stages missing from {script}: {missing}")

    figure_rows = {
        int(match.group(1))
        for match in re.finditer(r"^\| ([1-8]) \|", guide, flags=re.MULTILINE)
    }
    if figure_rows != set(range(1, 9)):
        problems.append(f"figure map has {sorted(figure_rows)}, expected 1-8")
    if (ROOT / "examples/Fig1.ipynb").exists():
        problems.append("legacy Fig1.ipynb still conflicts with manuscript Figure 2 naming")
    for name in NOTEBOOKS:
        path = ROOT / "examples" / name
        if f"examples/{name}" not in guide or not path.is_file():
            problems.append(f"figure notebook {name} missing from guide or repository")
            continue
        notebook = json.loads(path.read_text(encoding="utf-8"))
        code = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
        if not code:
            problems.append(f"{name} has no executable cells")
        source = "\n".join("".join(cell["source"]) for cell in code)
        expected_figure = int(name[3])
        panel_numbers = {
            int(number) for number in re.findall(r"Fig([2-8])[A-Za-z0-9_]*\.png", source)
        }
        if panel_numbers != {expected_figure}:
            problems.append(f"{name} exports panels numbered {sorted(panel_numbers)}")
        if f"'fig{expected_figure}'" not in source and f'"fig{expected_figure}"' not in source:
            problems.append(f"{name} does not name its own figure output directory")
        for index, cell in enumerate(code):
            try:
                ast.parse("".join(cell["source"]), filename=f"{name}:{index}")
            except SyntaxError as error:
                problems.append(f"{name} code cell {index} does not parse: {error}")
            if cell.get("outputs") or cell.get("execution_count") is not None:
                problems.append(f"{name} code cell {index} contains cached execution output")
            if "execution" in cell.get("metadata", {}):
                problems.append(f"{name} code cell {index} contains execution timestamps")

    manifest_root = ROOT / "docs/data_sources"
    manifests = [manifest_root / "cedar_rapids.tsv", manifest_root / "llano.tsv"]
    manifests += sorted((manifest_root / "forge").glob("*.tsv"))
    if len(manifests) < 8:
        problems.append("one or more source manifests are absent")
    for path in manifests:
        with path.open(encoding="utf-8", newline="") as handle:
            records = csv.DictReader(
                (line for line in handle if line.strip() and not line.startswith("#")),
                delimiter="\t",
            )
            names: set[str] = set()
            rows = 0
            for row in records:
                rows += 1
                name = row.get("path") or row.get("name") or ""
                candidate = Path(name)
                if not name or candidate.is_absolute() or ".." in candidate.parts:
                    problems.append(f"{path.name}: invalid local input name {name!r}")
                if name in names:
                    problems.append(f"{path.name}: duplicate local input name {name!r}")
                names.add(name)
            if rows == 0:
                problems.append(f"{path.name}: no source rows")

    register = (ROOT / "docs/case_audit.md").read_text(encoding="utf-8")
    for case in ("Utah-FORGE", "Cedar-Rapids", "Llano-Uplift"):
        if not re.search(rf"^\| {case} \|.*\| (?:Pass|Veto) \|", register, re.MULTILINE):
            problems.append(f"audit register has no verdict for {case}")
    verdicts = dict(re.findall(r"\| `([0-9a-f-]{36})` \| (Pass|Veto) \|", register))
    ledger_rows = [
        json.loads(line)
        for line in (ROOT / "docs/case_audit_ledger.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if len(verdicts) != 19 or len(ledger_rows) != 3 * len(verdicts):
        problems.append("audit table and exported ledger do not cover the same 19 runs")
    for run_id, verdict in verdicts.items():
        entries = [row for row in ledger_rows if row["run_id"] == run_id]
        expected = {"adopted", "diagnosed", "audited" if verdict == "Pass" else "vetoed"}
        if {row["stage"] for row in entries} != expected:
            problems.append(f"{run_id}: exported audit stages do not match {verdict}")
        if any(not row.get("by") or not row.get("evidence") for row in entries):
            problems.append(f"{run_id}: an exported entry has no actor or evidence")
    return problems


if __name__ == "__main__":
    failures = check()
    if failures:
        raise SystemExit("Release contract failed:\n- " + "\n- ".join(failures))
    print("Release source, stage, figure and audit metadata checks passed.")
