"""The situation F024 was decided in, regenerated from the release."""

import pathlib
import re

CASE = pathlib.Path("data/case1_Utah FORGE/gravity")

#: Files this project renamed on the way in are noted, because a replay that silently
#: used a clearer name than the release shipped would be replaying an easier situation
#: than the one that was met.
_RENAMED = {"granite_surface_TEST.csv"}


def main() -> None:
    readme = (CASE / "README.txt").read_text(encoding="utf-8", errors="replace")

    print("What the delivery's own README says about its models:")
    print()
    for line in readme.splitlines():
        text = line.strip()
        if re.search(r"model|granite|test|final", text, re.I) and len(text) > 20:
            print("   " + text[:150])
    print()
    print("What the folder actually holds:")
    print()
    for path in sorted(CASE.iterdir()):
        if path.name == "SOURCES.tsv":
            continue
        note = "  (renamed by this project on the way in)" if path.name in _RENAMED else ""
        print(f"   {path.stat().st_size:>10,d}  {path.name}{note}")
    print()
    for name in ("published_model.csv", "granite_surface_TEST.csv"):
        path = CASE / name
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", errors="replace") as handle:
            header = handle.readline().strip()
            rows = sum(1 for _ in handle)
        print(f"   {name}: {rows:,} rows, columns {header}")
    print()
    print("An independent check needs a reference surface. One is shipped.")


if __name__ == "__main__":
    main()
