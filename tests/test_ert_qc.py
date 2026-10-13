"""Check reciprocal filtering through the Data Agent tool."""

import csv
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest

from ofag.agent.dispatch import ToolError
from ofag.agent.roles import Role, dispatcher_for
from ofag.services.ert_qc import process_reciprocals


def _dataset(root: Path) -> tuple[str, Path]:
    identifier = uuid4()
    folder = root / str(identifier)
    folder.mkdir()
    electrodes = np.column_stack((np.arange(8), np.zeros(8), np.zeros(8)))
    quadrupoles = []
    resistance = []
    readings = ((100, 102), (200, 204), (300, 360), (400, 408), (500, 505))
    for index, pair in enumerate(readings):
        normal = [index, index + 1, index + 2, index + 3]
        quadrupoles.extend((normal, normal[2:] + normal[:2]))
        resistance.extend(pair)
    np.save(folder / "electrodes_m.npy", electrodes)
    np.save(folder / "quadrupoles.npy", np.asarray(quadrupoles, dtype=int))
    with (folder / "observations_ohm.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("resistance_ohm",))
        writer.writerows((value,) for value in resistance)
    return str(identifier), folder


def test_data_agent_filters_reciprocal_and_contact_errors(tmp_path: Path) -> None:
    identifier, _ = _dataset(tmp_path)
    contact_path = tmp_path / "contact.csv"
    with contact_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("contact_resistance_ohm",))
        writer.writerows((3000 if index == 7 else 100,) for index in range(10))
    data = dispatcher_for(Role.DATA, tmp_path)
    result = data.call(
        "ofag.ert_reciprocal_qc",
        {"dataset_id": identifier, "contact_resistance_csv": str(contact_path)},
    )
    assert result["reciprocal_pairs"] == 5
    assert result["reciprocal_error_refused"] == 1
    assert result["contact_refused"] == 1
    assert result["retained_pairs"] == 3
    assert result["contact_checked"] is True
    assert result["error_model"]["scale_ohm"] > 0
    output = tmp_path / str(result["dataset_id"])
    assert np.load(output / "quadrupoles.npy").shape == (3, 4)
    assert (output / "qc_report.json").is_file()
    with pytest.raises(ToolError, match="not a tool"):
        dispatcher_for(Role.AUDIT, tmp_path).call(
            "ofag.ert_reciprocal_qc", {"dataset_id": identifier}
        )


def test_reciprocal_qc_refuses_unpaired_dataset(tmp_path: Path) -> None:
    identifier, folder = _dataset(tmp_path)
    np.save(folder / "quadrupoles.npy", np.load(folder / "quadrupoles.npy")[:1])
    (folder / "observations_ohm.csv").write_text("resistance_ohm\n100\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no reciprocal pairs"):
        process_reciprocals(tmp_path, UUID(identifier))
