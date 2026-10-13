"""Reciprocal quality control for an imported ERT dataset."""

import csv
import json
from pathlib import Path
from uuid import UUID

import numpy as np


def process_reciprocals(
    import_root: Path,
    dataset_id: UUID,
    *,
    max_reciprocal_error_percent: float = 5.0,
    max_contact_resistance_ohm: float = 2000.0,
    contact_resistance_csv: str | None = None,
) -> dict[str, object]:
    """Pair observations, filter them, and save a new dataset with an error model."""
    if not 0 < max_reciprocal_error_percent <= 100:
        raise ValueError("max_reciprocal_error_percent must be within (0, 100]")
    if max_contact_resistance_ohm <= 0:
        raise ValueError("max_contact_resistance_ohm must be positive")
    source = import_root / str(dataset_id)
    electrodes_path = source / "electrodes_m.npy"
    quadrupoles_path = source / "quadrupoles.npy"
    observations_path = source / "observations_ohm.csv"
    if not all(p.is_file() for p in (electrodes_path, quadrupoles_path, observations_path)):
        raise ValueError(f"dataset {dataset_id} has no complete ERT import")
    electrodes = np.load(electrodes_path, allow_pickle=False)
    quadrupoles = np.load(quadrupoles_path, allow_pickle=False)
    with observations_path.open(newline="", encoding="utf-8") as stream:
        observations = np.asarray(
            [float(row["resistance_ohm"]) for row in csv.DictReader(stream)], dtype=float
        )
    if (
        quadrupoles.ndim != 2
        or quadrupoles.shape[1] != 4
        or len(quadrupoles) != len(observations)
        or len(observations) == 0
        or not np.all(np.isfinite(observations))
    ):
        raise ValueError("ERT observations and quadrupoles have incompatible shapes or values")
    contact = None
    if contact_resistance_csv is not None:
        with Path(contact_resistance_csv).open(newline="", encoding="utf-8") as stream:
            contact = np.asarray(
                [float(row["contact_resistance_ohm"]) for row in csv.DictReader(stream)],
                dtype=float,
            )
        if (
            len(contact) != len(observations)
            or not np.all(np.isfinite(contact))
            or np.any(contact < 0)
        ):
            raise ValueError(
                "contact resistance must give one finite nonnegative value per reading"
            )
    lookup: dict[tuple[int, int, int, int], int] = {}
    for index, row in enumerate(quadrupoles):
        key = (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
        if key in lookup:
            raise ValueError("duplicate quadrupoles need explicit pairing before quality control")
        lookup[key] = index
    pairs: list[tuple[int, int]] = []
    for index, row in enumerate(quadrupoles):
        other = lookup.get((int(row[2]), int(row[3]), int(row[0]), int(row[1])))
        if other is not None and other > index:
            pairs.append((index, other))
    if not pairs:
        raise ValueError("no reciprocal pairs; an error model cannot be estimated")
    indices = np.asarray(pairs, dtype=int)
    first, second = indices[:, 0], indices[:, 1]
    magnitude = (np.abs(observations[first]) + np.abs(observations[second])) / 2
    difference = np.abs(np.abs(observations[first]) - np.abs(observations[second]))
    relative = np.divide(
        difference, magnitude, out=np.full_like(difference, np.inf), where=magnitude > 0
    )
    reciprocal_ok = relative < max_reciprocal_error_percent / 100
    contact_ok = np.ones(len(indices), dtype=bool)
    if contact is not None:
        contact_ok = np.maximum(contact[first], contact[second]) <= max_contact_resistance_ohm
    keep = reciprocal_ok & contact_ok
    if keep.sum() < 2:
        raise ValueError("fewer than two reciprocal pairs pass quality control")
    retained = magnitude[keep]
    errors = difference[keep]
    bins = np.array_split(np.argsort(retained), min(20, len(retained)))
    binned_resistance = np.asarray([retained[b].mean() for b in bins])
    binned_error = np.asarray([errors[b].mean() for b in bins])
    fit = (binned_resistance > 0) & (binned_error > 0)
    if fit.sum() < 2 or np.unique(binned_resistance[fit]).size < 2:
        raise ValueError("retained pairs cannot estimate a two-parameter error model")
    exponent, log_scale = np.polyfit(
        np.log(binned_resistance[fit]), np.log(binned_error[fit]), 1
    )
    from ofag.services.import_store import ImportStore

    output_id, destination = ImportStore(import_root).new_dataset()
    np.save(destination / "electrodes_m.npy", electrodes)
    np.save(destination / "quadrupoles.npy", quadrupoles[first[keep]])
    np.save(destination / "reciprocal_difference_ohm.npy", errors)
    signed_mean = np.sign(observations[first[keep]]) * retained
    (destination / "observations_ohm.csv").write_text(
        "resistance_ohm\n" + "\n".join(f"{v:.10e}" for v in signed_mean) + "\n",
        encoding="utf-8",
    )
    report: dict[str, object] = {
        "source_dataset_id": str(dataset_id),
        "dataset_id": str(output_id),
        "readings": int(len(observations)),
        "reciprocal_pairs": int(len(indices)),
        "unpaired_readings": int(len(observations) - 2 * len(indices)),
        "reciprocal_error_refused": int((~reciprocal_ok).sum()),
        "contact_refused": int((reciprocal_ok & ~contact_ok).sum()),
        "retained_pairs": int(keep.sum()),
        "contact_checked": contact is not None,
        "max_reciprocal_error_percent": max_reciprocal_error_percent,
        "max_contact_resistance_ohm": max_contact_resistance_ohm if contact is not None else None,
        "error_model": {"scale_ohm": float(np.exp(log_scale)), "exponent": float(exponent)},
        "electrodes_path": (destination / "electrodes_m.npy").as_posix(),
        "quadrupoles_path": (destination / "quadrupoles.npy").as_posix(),
        "observations_path": (destination / "observations_ohm.csv").as_posix(),
        "reciprocal_difference_path": (destination / "reciprocal_difference_ohm.npy").as_posix(),
    }
    (destination / "qc_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
