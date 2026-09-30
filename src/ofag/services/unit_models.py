"""Labelled volumes: every cell given a unit, and what decided it, read back for viewing."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import numpy as np

__all__ = ["UnitModel", "find_unit_models", "load_unit_model", "UNCLAIMED_WORDS", "MODELS_DIR"]

#: Where the agents' models are written, under a project's runs folder.
MODELS_DIR = "models"

#: Words that mark a unit as the part of the volume nothing claimed: drawn grey, because
#: a model's honest content includes what it cannot say.
UNCLAIMED_WORDS = (
    "nothing",
    "below the investigation",
    "out of reach",
    "not claimed",
    "unclaimed",
    "remainder",
)


@dataclass(frozen=True)
class UnitModel:
    name: str
    path: Path
    unit: np.ndarray
    unit_names: tuple[str, ...]
    unit_sources: tuple[str, ...]
    centres_m: np.ndarray
    widths_m: np.ndarray
    report: str = ""
    #: Where the cell geometry came from, when the file did not carry it.
    geometry_from: str = ""
    #: Per-cell arrays the file also carries (support distance, depths ...).
    fields: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def cells(self) -> int:
        """Cells inside the model volume."""
        return int((self.unit >= 0).sum())

    def shares(self) -> list[tuple[str, str, float]]:
        """(name, source, share of the volume) per unit, in unit order."""
        # Over the labelled cells only: a negative unit is a cell outside the model
        # volume -- the inversion mesh's padding -- which is no part of the ground the
        # model describes.
        volumes = np.prod(self.widths_m, axis=1)
        total = float(volumes[self.unit >= 0].sum()) or 1.0
        return [
            (name, source, float(volumes[self.unit == index].sum()) / total)
            for index, (name, source) in enumerate(
                zip(self.unit_names, self.unit_sources, strict=False)
            )
        ]

    def unclaimed(self, index: int) -> bool:
        name = self.unit_names[index].lower() if index < len(self.unit_names) else ""
        return any(word in name for word in UNCLAIMED_WORDS)


def find_unit_models(project_folder: Path) -> list[Path]:
    """Every labelled volume in a project: the case's, then the agents', newest first."""
    folder = Path(project_folder)
    found = [p for p in [folder / "imports" / "geological_model.npz"] if p.is_file()]
    agents = sorted(
        (folder / "runs" / MODELS_DIR).glob("*.npz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return found + agents


def _grid_widths(centres: np.ndarray) -> np.ndarray:
    """Cell sizes of a column grid hung from the ground: x and y from the grid, z per column."""
    widths = np.empty_like(centres)
    for axis in (0, 1):
        distinct = np.unique(np.round(centres[:, axis], 6))
        steps = np.diff(distinct)
        widths[:, axis] = float(np.median(steps)) if steps.size else 1.0
    keys = np.round(centres[:, :2], 6)
    _, column = np.unique(keys, axis=0, return_inverse=True)
    column = column.reshape(-1)
    for index in np.unique(column):
        rows = column == index
        z = np.sort(centres[rows, 2])
        steps = np.diff(z)
        widths[rows, 2] = float(np.median(steps)) if steps.size else 1.0
    return widths


def _labels(
    unit: Any, names: Any, sources: Any
) -> tuple[np.ndarray, tuple[str, ...], tuple[str, ...]]:
    labels = np.asarray(unit)
    names_array, sources_array = np.asarray(names), np.asarray(sources)
    if names_array.ndim != 1 or sources_array.shape != names_array.shape:
        raise ValueError("unit_names and unit_sources must be matching one-dimensional arrays")
    if labels.ndim != 1 or labels.dtype.kind not in "iuf":
        raise ValueError("unit must be a one-dimensional array of integer labels")
    if (
        not np.all(np.isfinite(labels))
        or np.any(labels != np.floor(labels))
        or np.any(labels < -1)
        or np.any(labels >= len(names_array))
    ):
        raise ValueError("unit labels must be -1 (padding) or an integer index into unit_names")
    return labels.astype(np.int64), tuple(map(str, names_array)), tuple(map(str, sources_array))


def _geometry(centres: Any, widths: Any, cells: int) -> tuple[np.ndarray, np.ndarray]:
    centres = np.asarray(centres, dtype=float)
    if centres.shape != (cells, 3) or not np.all(np.isfinite(centres)):
        raise ValueError("cell centres must contain three finite coordinates for every label")
    widths = _grid_widths(centres) if widths is None else np.asarray(widths, dtype=float)
    if widths.shape != (cells, 3) or not np.all(np.isfinite(widths)) or np.any(widths <= 0):
        raise ValueError("cell widths must contain three positive finite sizes for every label")
    return centres, widths


def _geometry_from_runs(project_folder: Path, cells: int) -> tuple[np.ndarray, np.ndarray, str]:
    matches = []
    for mesh in (Path(project_folder) / "runs").glob("*/mesh_geometry.npz"):
        try:
            with np.load(mesh, allow_pickle=False) as stored:
                key = "cell_centers_m" if "cell_centers_m" in stored.files else None
                if (
                    key is None
                    or stored[key].shape[0] != cells
                    or "cell_widths_m" not in stored.files
                ):
                    continue
                matches.append(
                    (np.asarray(stored[key]), np.asarray(stored["cell_widths_m"]), mesh.parent.name)
                )
        except (OSError, ValueError):
            continue
    if not matches:
        raise ValueError(
            f"the model carries no cell geometry and no run's mesh has its {cells} cells, so "
            "there is nothing honest to draw it on"
        )
    first = matches[0]
    # A relative tolerance scales with the UTM origin and can hide metre-scale offsets.
    if any(
        m[0].shape != first[0].shape
        or m[1].shape != first[1].shape
        or not np.allclose(m[0], first[0], rtol=0, atol=1e-6)
        or not np.allclose(m[1], first[1], rtol=0, atol=1e-6)
        for m in matches[1:]
    ):
        raise ValueError(
            f"{len(matches)} runs have meshes of {cells} cells that differ; which one is ambiguous"
        )
    return first[0], first[1], first[2]


def load_unit_model(path: Path, project_folder: Path | None = None) -> UnitModel:
    """One labelled volume, with its cell geometry, whatever file shape it was saved in."""
    path = Path(path)
    folder = Path(project_folder) if project_folder is not None else path.parent.parent
    with np.load(path, allow_pickle=False) as stored:
        data = {key: np.asarray(stored[key]) for key in stored.files}
    if "unit" not in data or "unit_names" not in data:
        raise ValueError("model must contain unit and unit_names arrays")
    raw_names = data.pop("unit_names")
    unit, names, sources = _labels(
        data.pop("unit"),
        raw_names,
        data.pop("unit_sources", np.full(raw_names.shape, "", dtype=str)),
    )
    report = str(data.pop("report", ""))
    geometry_from = ""
    if "cell_centres_m" in data:
        centres = data.pop("cell_centres_m")
        widths = data.pop("cell_widths_m", None)
    else:
        centres, widths, run = _geometry_from_runs(folder, unit.shape[0])
        geometry_from = f"the mesh of run {run}"
    centres, widths = _geometry(centres, widths, len(unit))
    per_cell = {k: v for k, v in data.items() if v.ndim == 1 and v.shape[0] == unit.shape[0]}
    label = (
        "the case's model"
        if path.name == "geological_model.npz"
        else f"agent model {path.stem[:8]}"
    )
    meta = path.with_suffix(".json")
    if meta.is_file():
        try:
            metadata = json.loads(meta.read_text("utf-8"))
            if isinstance(metadata, dict):
                label = str(metadata.get("name") or label)
        except (OSError, ValueError):
            pass
    return UnitModel(
        name=label,
        path=path,
        unit=unit,
        unit_names=names,
        unit_sources=sources,
        centres_m=np.asarray(centres, dtype=float),
        widths_m=np.asarray(widths, dtype=float),
        report=report,
        geometry_from=geometry_from,
        fields=per_cell,
    )


def save_unit_model(
    path: Path,
    *,
    unit: Any,
    unit_names: Any,
    unit_sources: Any,
    centres_m: Any,
    widths_m: Any = None,
    report: str = "",
    name: str = "",
    **fields: Any,
) -> Path:
    """Write a labelled volume in the shape `load_unit_model` reads."""
    path = Path(path)
    if path.suffix != ".npz":
        path = Path(str(path) + ".npz")
    unit, unit_names, unit_sources = _labels(unit, unit_names, unit_sources)
    centres_m, widths_m = _geometry(centres_m, widths_m, len(unit))
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, Any] = {
        **{k: np.asarray(v) for k, v in fields.items()},
        "unit": unit,
        "unit_names": np.asarray(unit_names, dtype=str),
        "unit_sources": np.asarray(unit_sources, dtype=str),
        "cell_centres_m": np.asarray(centres_m, dtype=float),
        "report": np.asarray(report),
    }
    if widths_m is not None:
        arrays["cell_widths_m"] = np.asarray(widths_m, dtype=float)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".npz", delete=False) as handle:
            temporary = Path(handle.name)
            np.savez_compressed(handle, **arrays)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if name:
        path.with_suffix(".json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return path
