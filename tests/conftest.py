import json
import time
from pathlib import Path
from typing import Any

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
)


def await_terminal_state(service: Any, run_id: Any, timeout_s: float = 90.0) -> Any:
    """Poll a dispatched run until it leaves RUNNING."""
    from ofag.core.schemas import RunState

    deadline = time.monotonic() + timeout_s
    record = service.get(run_id)
    while record.state is RunState.RUNNING and time.monotonic() < deadline:
        time.sleep(0.05)
        record = service.get(run_id)
    return record


def progress_events(run_dir: Path) -> list[dict[str, Any]]:
    """Read the events a plugin reported through `PluginContext.emit`."""
    path = run_dir / "progress.jsonl"
    assert path.is_file(), f"no progress.jsonl under {run_dir}"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def gravity_run_spec() -> RunSpec:
    return RunSpec(
        plugin_id="ofag.fixture.gravity3d",
        dataset=DatasetSpec(
            name="synthetic-gravity",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[25.0, 25.0, 25.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(4, 4, 4),
            origin=(0.0, 0.0, 0.0),
        ),
    )
