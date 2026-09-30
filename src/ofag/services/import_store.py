"""Where an imported dataset's canonical copy goes."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

#: Where imports go when no project supplies a root.
DEFAULT_IMPORT_ROOT = Path("data/imports")


@dataclass(frozen=True)
class ImportStore:
    """The root an importer writes under, and the directories it makes there."""

    root: Path = DEFAULT_IMPORT_ROOT

    def new_dataset(self) -> tuple[UUID, Path]:
        """An identifier and the empty directory that belongs to it."""
        dataset_id = uuid4()
        return dataset_id, self.directory_for(dataset_id)

    def directory_for(self, dataset_id: UUID) -> Path:
        """The directory for a dataset, created if it is not there yet."""
        directory = self.root / str(dataset_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory
