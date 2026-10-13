"""Where one project keeps everything it produces."""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

#: Where projects live unless a caller says otherwise.
DEFAULT_RESULT_ROOT = Path("Result")

#: Long enough to stay recognisable, short enough that the paths inside it do not
#: approach the Windows limit once a run id and an artifact name are added.
MAX_FOLDER_NAME = 60

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
#: Reserved on Windows whatever the extension, and silently unusable.
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{digit}" for digit in range(1, 10)}
    | {f"LPT{digit}" for digit in range(1, 10)}
)


def folder_name_for(name: str) -> str:
    """A directory name that keeps a project recognisable and can be created."""
    folded = unicodedata.normalize("NFKD", name)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    cleaned = _UNSAFE.sub("-", ascii_only).strip("-. ")
    cleaned = re.sub(r"-{2,}", "-", cleaned)[:MAX_FOLDER_NAME].strip("-. ")
    if not cleaned or cleaned.upper() in _RESERVED:
        return "project"
    return cleaned


@dataclass(frozen=True)
class ProjectFolder:
    """One project's directory, and the paths inside it."""

    root: Path

    @property
    def name_on_disk(self) -> str:
        return self.root.name

    @property
    def record_path(self) -> Path:
        return self.root / "project.json"

    @property
    def workspace_path(self) -> Path:
        return self.root / "workspace.json"

    @property
    def imports_root(self) -> Path:
        """Canonical SI copies of imported surveys, one directory per dataset."""
        return self.root / "imports"

    @property
    def runs_root(self) -> Path:
        """One directory per run, which is what a plugin context is given."""
        return self.root / "runs"

    def create(self) -> "ProjectFolder":
        for directory in (self.root, self.imports_root, self.runs_root):
            directory.mkdir(parents=True, exist_ok=True)
        return self

    def exists(self) -> bool:
        return self.record_path.is_file()


def unique_folder(result_root: Path, name: str) -> ProjectFolder:
    """A folder for a new project, not colliding with one already there."""
    base = folder_name_for(name)
    candidate = result_root / base
    suffix = 2
    while candidate.exists():
        candidate = result_root / f"{base}-{suffix}"
        suffix += 1
    return ProjectFolder(candidate)


def folders_in(result_root: Path) -> tuple[ProjectFolder, ...]:
    """Every project directory under a result root, in name order."""
    if not result_root.is_dir():
        return ()
    found = [
        ProjectFolder(path)
        for path in sorted(result_root.iterdir())
        if path.is_dir() and (path / "project.json").is_file()
    ]
    return tuple(found)
