"""Small offline check of the installed run path."""

import tempfile
import time
from pathlib import Path

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    RunState,
    TensorMeshSpec,
)
from ofag.services.run_service import RunService


def run_offline_self_test(base_dir: Path | None = None) -> tuple[bool, str]:
    """Exercise validation, child execution, persistence and artifact reading."""
    with tempfile.TemporaryDirectory(prefix="ofag-doctor-", dir=base_dir) as temporary:
        root = Path(temporary) / "runs"
        runs = RunService(artifact_root=root)
        spec = RunSpec(
            plugin_id="ofag.fixture.gravity3d",
            dataset=DatasetSpec(
                name="doctor fixture",
                coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
                physical_quantity=QuantityType.GRAVITY_ACCELERATION,
                units="mGal",
            ),
            mesh=TensorMeshSpec(
                cell_size=QuantitySpec(
                    value=[25.0, 25.0, 25.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                shape=(2, 2, 2),
                origin=(0.0, 0.0, 0.0),
            ),
        )
        runs.create(spec)
        runs.start(spec.run_id)
        deadline = time.monotonic() + 30
        record = runs.get(spec.run_id)
        while record.state is RunState.RUNNING and time.monotonic() < deadline:
            time.sleep(0.05)
            record = runs.get(spec.run_id)
        if record.state is RunState.RUNNING:
            runs.cancel(spec.run_id)
            return False, "offline fixture did not finish within 30 seconds"
        if record.state is not RunState.SUCCEEDED:
            return False, record.error or f"offline fixture ended as {record.state.value}"
        result = RunService(artifact_root=root).result(spec.run_id)
        if result is None or not result.artifacts:
            return False, "offline fixture produced no readable result manifest"
        if any(not (root / item.relative_path).is_file() for item in result.artifacts):
            return False, "offline fixture artifact path cannot be read"
        return True, "worker, persisted result and artifact path passed"
