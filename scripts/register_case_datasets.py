"""Put each project's inverted data on its register, from the runs that used it."""

import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from ofag.core.schemas import DatasetKind, ProjectDataset, ProjectWorkspaceUpdate, RunRecord
from ofag.services.project_service import ProjectService

#: The mark on every dataset this script registers, so a second run can rebuild its own
#: and leave everyone else's alone.
MARK = "registered_from"
FROM_RUNS = "runs"
FROM_CASE_STATE = "case_state.json"

#: A channel's physical quantity decides its kind; the plugin is the fallback.
KIND_BY_QUANTITY = {
    "transfer_resistance": DatasetKind.ERT,
    "apparent_resistivity": DatasetKind.ERT,
    "traveltime": DatasetKind.SEISMIC,
    "gravity_acceleration": DatasetKind.GRAVITY,
    "magnetic_anomaly": DatasetKind.MAGNETICS,
    "magnetic_flux_density": DatasetKind.MAGNETICS,
    "magnetic_flux_density_time_derivative": DatasetKind.AEM,
    "impedance": DatasetKind.MT,
    "magnetotelluric_impedance": DatasetKind.MT,
    "apparent_resistivity_phase": DatasetKind.MT,
}
KIND_BY_PLUGIN = (
    ("ert", DatasetKind.ERT),
    ("srt", DatasetKind.SEISMIC),
    ("refraction", DatasetKind.SEISMIC),
    ("seismic", DatasetKind.SEISMIC),
    ("fwi", DatasetKind.SEISMIC),
    ("nsem", DatasetKind.MT),
    ("mt", DatasetKind.MT),
    ("aem", DatasetKind.AEM),
    ("tdem", DatasetKind.AEM),
    ("fdem", DatasetKind.AEM),
    ("gravity", DatasetKind.GRAVITY),
    ("mag", DatasetKind.MAGNETICS),
)
#: Files an importer writes beside its observations, and the payload key each is read
#: under.
COMPANION_FILES = {
    "electrodes_m.npy": "electrodes_path",
    "quadrupoles.npy": "quadrupoles_path",
    "reciprocal_error.npy": "reciprocal_error_path",
    "reciprocal_difference_ohm.npy": "reciprocal_difference_path",
    "sensors_m.npy": "sensors_path",
    "shot_receiver.npy": "pairs_path",
}
_IMPORT_DIR = re.compile(r"imports/([0-9A-Za-z_.-]+)/")


def _kind(quantity: str, plugin_id: str) -> DatasetKind | None:
    if quantity in KIND_BY_QUANTITY:
        return KIND_BY_QUANTITY[quantity]
    for fragment, kind in KIND_BY_PLUGIN:
        if fragment in plugin_id.lower():
            return kind
    return None


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def from_runs(folder: Path) -> list[ProjectDataset]:
    """One dataset per channel name the runs read, the latest copy of each."""
    records = []
    for path in (folder / "runs").glob("*/run_record.json"):
        try:
            records.append(RunRecord.model_validate_json(path.read_text("utf-8")))
        except (OSError, ValueError):
            continue
    records.sort(key=lambda r: r.created_at)
    chosen: dict[str, dict[str, Any]] = {}
    for record in records:
        spec = record.spec
        channels = [channel.model_dump(mode="json") for channel in spec.datasets]
        if (
            not any(_IMPORT_DIR.search(json.dumps(c)) for c in channels)
            and spec.dataset is not None
        ):
            # A batch plugin -- MT, TEM, airborne EM -- names its soundings in its
            # physics, not in a channel; the run's own dataset stands for them, and its
            # import directory is wherever the spec names one.
            channels = [
                {
                    "channel_id": "batch",
                    "dataset": spec.dataset.model_dump(mode="json"),
                    "imports_named": [
                        f"imports/{d}/"
                        for d in sorted(set(_IMPORT_DIR.findall(spec.model_dump_json())))
                    ],
                }
            ]
        for raw in channels:
            directories = sorted(set(_IMPORT_DIR.findall(json.dumps(raw))))
            if not directories:
                continue
            kind = _kind(str(raw["dataset"].get("physical_quantity", "")), spec.plugin_id)
            if kind is None:
                continue
            name = str(raw["dataset"]["name"])
            entry = chosen.setdefault(name, {"copies": [], "runs": []})
            entry["copies"] = sorted(set(entry["copies"]) | set(directories))
            entry["runs"].append(str(spec.run_id))
            # Later runs overwrite: the copy the most recent run read is the one kept.
            entry.update(
                kind=kind,
                directory=directories[0],
                dataset_id=raw["dataset"]["dataset_id"],
                channel=raw,
                label=spec.label or spec.plugin_id,
            )
    datasets = []
    for name, entry in chosen.items():
        channel = entry["channel"]
        payload = {
            **{k: v for k, v in channel.items() if k != "dataset"},
            "dataset_id": entry["dataset_id"],
            "import_directory": (folder / "imports" / entry["directory"]).as_posix(),
            "used_by_runs": entry["runs"],
            "other_copies": [c for c in entry["copies"] if c != entry["directory"]],
            MARK: FROM_RUNS,
        }
        if isinstance(channel.get("observations_path"), str):
            payload.setdefault("canonical_observations_path", channel["observations_path"])
        # The files beside the observations, under the names the importers give them, so
        # the Setup stage can draw the survey and an ERT run can be set up from it again
        # -- a run's channel records only its data.
        directory = folder / "imports" / entry["directory"]
        for filename, key in COMPANION_FILES.items():
            if (directory / filename).is_file():
                payload.setdefault(key, (directory / filename).as_posix())
        datasets.append(
            ProjectDataset(
                dataset_id=uuid.UUID(entry["dataset_id"]),
                name=name[:120],
                kind=entry["kind"],
                source_filename=entry["label"][:120],
                payload=json.loads(json.dumps(payload, default=str)),
            )
        )
    return datasets


def _survey_key(kind: DatasetKind, name: str, payload: dict[str, Any]) -> str:
    """What identifies a survey across its names: a profile number or a site and array."""
    if kind is DatasetKind.SEISMIC and payload.get("profile") is not None:
        return f"srt{payload['profile']}"
    if kind is DatasetKind.ERT and payload.get("profile") is not None and not payload.get("site"):
        return f"ert{payload['profile']}"
    return _normal(name)


def from_case_state(folder: Path, taken: set[str]) -> list[ProjectDataset]:
    """What the case state names that no run read, and no run's dataset is called."""
    state_path = folder / FROM_CASE_STATE
    if not state_path.is_file():
        return []
    state = json.loads(state_path.read_text("utf-8"))
    candidates: list[tuple[DatasetKind, str, str, dict[str, Any]]] = []
    for entry in state.get("ert_imports") or ():
        label = entry.get("site") or f"ERT{entry.get('profile', '')}"
        array = f" {entry['array']}" if entry.get("array") else ""
        candidates.append(
            (DatasetKind.ERT, f"{label}{array}", str(entry.get("source", "")), dict(entry))
        )
    for entry in state.get("srt_imports") or ():
        candidates.append(
            (
                DatasetKind.SEISMIC,
                f"SRT{entry.get('profile', '')} first arrivals",
                str(entry.get("source", "")),
                dict(entry),
            )
        )
    if state.get("topography_path"):
        path = Path(state["topography_path"])
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, path.as_posix()))
        candidates.append(
            (
                DatasetKind.TOPOGRAPHY,
                "Topography",
                path.name,
                {"dataset_id": identifier, "canonical_observations_path": path.as_posix()},
            )
        )
    datasets = []
    for kind, name, source, payload in candidates:
        if not payload.get("dataset_id"):
            continue
        # The survey's own token -- "srt2", "ert1", "elliscw1dipoledipole" -- inside a
        # run's dataset name means a run already read this survey, imported again; a
        # second row would be two names for one thing.
        key = _survey_key(kind, name, payload)
        if any(key in t for t in taken):
            continue
        datasets.append(
            ProjectDataset(
                dataset_id=uuid.UUID(str(payload["dataset_id"])),
                name=name[:120],
                kind=kind,
                source_filename=Path(source).name or source or kind.value,
                payload=json.loads(json.dumps({**payload, MARK: FROM_CASE_STATE}, default=str)),
            )
        )
        taken.add(_normal(name))
    return datasets


def register(folder: Path) -> tuple[int, int, int]:
    """Rebuild this script's registrations for one project: (from runs, from state, kept)."""
    record = json.loads((folder / "project.json").read_text("utf-8"))
    project_id = uuid.UUID(record["project_id"])
    projects = ProjectService(root=folder.parent)
    workspace = projects.workspace(project_id)
    kept = [
        d for d in workspace.datasets if d.payload.get(MARK) not in {FROM_RUNS, FROM_CASE_STATE}
    ]
    runs = from_runs(folder)
    retired_path = folder / "retired_datasets.json"
    retired = set(json.loads(retired_path.read_text("utf-8"))) if retired_path.exists() else set()
    runs = [d for d in runs if d.name not in retired]
    taken = {_normal(d.name) for d in [*kept, *runs]}
    state = from_case_state(folder, taken)
    state = [d for d in state if d.name not in retired]
    ids = {d.dataset_id for d in kept}
    added = [d for d in [*runs, *state] if d.dataset_id not in ids]
    values = workspace.model_copy(update={"datasets": (*kept, *added)}).model_dump()
    projects.update_workspace(
        project_id,
        ProjectWorkspaceUpdate.model_validate(
            {f: values[f] for f in ProjectWorkspaceUpdate.model_fields}
        ),
    )
    return len(runs), len(state), len(kept)


def main(root: Path) -> None:
    for folder in sorted(p.parent for p in root.glob("*/project.json")):
        if not (folder / "runs").is_dir():
            continue
        runs, state, kept = register(folder)
        print(
            f"{folder.name}: {runs} from runs, {state} from the case state, "
            f"{kept} imported by hand kept"
        )


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Result"))
