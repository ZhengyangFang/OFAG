"""Preflight for user-facing run entry points."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from ofag.core.safety import SAMPLE_ABOVE_SECONDS
from ofag.core.schemas import ResourceEstimate, RunSpec, RunState, spec_fingerprint
from ofag.services.run_service import RunService


@dataclass(frozen=True)
class StartAssessment:
    estimate: ResourceEstimate
    sample_run_id: UUID | None
    waived: bool


class RunStartPolicy:
    def __init__(self, runs: RunService) -> None:
        self._runs = runs

    def check(
        self,
        spec: RunSpec,
        *,
        sample_run_id: UUID | None = None,
        allow_unchecked_large_run: bool = False,
    ) -> StartAssessment:
        """Require a readable, smaller completed run unless explicitly waived."""
        estimate = self._runs.estimate_resources(spec)
        if sample_run_id is not None:
            self._verify_sample(spec, estimate, sample_run_id)
        if estimate.estimated_seconds > SAMPLE_ABOVE_SECONDS:
            if sample_run_id is None and not allow_unchecked_large_run:
                raise ValueError(
                    f"rough estimate is {estimate.estimated_seconds} s, above the "
                    f"{SAMPLE_ABOVE_SECONDS} s trial threshold; supply a completed smaller "
                    "sample run or explicitly allow an unchecked large run"
                )
        return StartAssessment(
            estimate=estimate,
            sample_run_id=sample_run_id,
            waived=bool(allow_unchecked_large_run and sample_run_id is None),
        )

    def _verify_sample(
        self, spec: RunSpec, estimate: ResourceEstimate, sample_run_id: UUID
    ) -> None:
        if sample_run_id == spec.run_id:
            raise ValueError("the trial run must be different from the full run")
        sample = self._runs.get(sample_run_id)
        if sample.state is not RunState.SUCCEEDED:
            raise ValueError("the trial run has not succeeded")
        if sample.spec.plugin_id != spec.plugin_id:
            raise ValueError("the trial run must use the same numerical plugin")
        if spec_fingerprint(sample.spec) == spec_fingerprint(spec):
            raise ValueError("the trial run has the same configuration as the full run")
        sample_estimate = self._runs.estimate_resources(sample.spec)
        if sample_estimate.estimated_seconds >= estimate.estimated_seconds:
            raise ValueError("the trial run is not estimated to be smaller")
        result = self._runs.result(sample_run_id)
        if result is None or not result.artifacts:
            raise ValueError("the trial run has no result artifacts to inspect")
        root = self._runs.artifact_root.resolve()
        for artifact in result.artifacts:
            path = (root / artifact.relative_path).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError(f"trial artifact is not readable: {artifact.relative_path}")

    def record(self, spec: RunSpec, assessment: StartAssessment) -> Path:
        """Persist what authorized the start, before dispatching the worker."""
        path = self._runs.run_dir(spec.run_id) / "preflight.json"
        payload = {
            "checked_at": datetime.now(UTC).isoformat(),
            "spec_fingerprint": spec_fingerprint(spec),
            "estimate": assessment.estimate.model_dump(mode="json"),
            "sample_run_id": str(assessment.sample_run_id) if assessment.sample_run_id else None,
            "unchecked_large_run_waived": assessment.waived,
        }
        temporary = path.with_name(".preflight.json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(path)
        return path
