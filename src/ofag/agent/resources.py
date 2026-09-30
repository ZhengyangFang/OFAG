"""Locate knowledge in a checkout or an installed distribution."""

from importlib.resources import files
from pathlib import Path


def docs_root() -> Path:
    checkout = Path(__file__).resolve().parents[3]
    if (checkout / "src" / "ofag" / "agent" / "resources.py").resolve() == Path(__file__).resolve():
        return checkout / "docs"
    # Wheels are installed as directories by pip/uv.
    return Path(str(files("ofag").joinpath("_resources", "docs")))


DOCS_ROOT = docs_root()
