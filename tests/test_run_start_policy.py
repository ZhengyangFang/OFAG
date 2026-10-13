"""The same preflight decision is used by the CLI, HTTP API and desktop."""

import json
from pathlib import Path

import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import ArtifactManifest, ResourceEstimate, RunResult
from ofag.services.run_service import RunService
from ofag.services.run_start_policy import RunStartPolicy
from tests.conftest import gravity_run_spec


def test_a_large_run_needs_a_readable_smaller_trial_or_recorded_waiver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = RunService(artifact_root=tmp_path / "runs")
    sample = gravity_run_spec()
    full = gravity_run_spec()
    sample_file = runs.run_dir(sample.run_id) / "summary.txt"
    sample_file.write_text("small result", encoding="utf-8")
    runs.adopt_external_result(
        sample,
        RunResult(
            run_id=sample.run_id,
            summary={},
            artifacts=(
                ArtifactManifest(
                    artifact_type="summary",
                    physical_quantity=QuantityType.GRAVITY_ACCELERATION,
                    units="mGal",
                    source_run_id=sample.run_id,
                    relative_path=f"{sample.run_id}/summary.txt",
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        runs,
        "estimate_resources",
        lambda spec: ResourceEstimate(
            cpu_cores=1,
            memory_mb=64,
            estimated_seconds=10 if spec.run_id == sample.run_id else 120,
        ),
    )
    policy = RunStartPolicy(runs)

    with pytest.raises(ValueError, match="smaller sample"):
        policy.check(full)
    accepted = policy.check(full, sample_run_id=sample.run_id)
    receipt = json.loads(policy.record(full, accepted).read_text(encoding="utf-8"))
    assert receipt["sample_run_id"] == str(sample.run_id)
    assert receipt["unchecked_large_run_waived"] is False

    sample_file.unlink()
    with pytest.raises(ValueError, match="not readable"):
        policy.check(full, sample_run_id=sample.run_id)
    waived = policy.check(full, allow_unchecked_large_run=True)
    receipt = json.loads(policy.record(full, waived).read_text(encoding="utf-8"))
    assert receipt["unchecked_large_run_waived"] is True
