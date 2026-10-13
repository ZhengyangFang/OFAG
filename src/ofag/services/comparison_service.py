"""Artifact-level comparison service for completed OFAG runs."""

from uuid import UUID

import numpy as np

from ofag.core.schemas import (
    ArtifactComparison,
    ArtifactManifest,
    RunComparison,
    RunComparisonRequest,
    RunResult,
)
from ofag.services.run_service import RunService


class ComparisonService:
    """Compare compatible summaries and bounded numeric artifacts without re-running solvers."""

    def __init__(self, run_service: RunService) -> None:
        self._run_service = run_service

    def compare(self, request: RunComparisonRequest) -> RunComparison:
        baseline = self._require_completed_result(request.baseline_run_id)
        candidate = self._require_completed_result(request.candidate_run_id)
        summary_deltas = {
            key: float(candidate.summary[key]) - float(baseline.summary[key])
            for key in baseline.summary.keys() & candidate.summary.keys()
            if _is_numeric(baseline.summary[key]) and _is_numeric(candidate.summary[key])
        }
        candidate_artifacts = {artifact.artifact_type: artifact for artifact in candidate.artifacts}
        comparisons: list[ArtifactComparison] = []
        for baseline_artifact in baseline.artifacts:
            candidate_artifact = candidate_artifacts.get(baseline_artifact.artifact_type)
            if candidate_artifact is None or not _artifacts_are_compatible(
                baseline_artifact, candidate_artifact
            ):
                continue
            baseline_values = self._load_numeric_artifact(baseline_artifact.relative_path)
            candidate_values = self._load_numeric_artifact(candidate_artifact.relative_path)
            if baseline_values is None or candidate_values is None:
                continue
            if baseline_values.shape != candidate_values.shape:
                continue
            delta = candidate_values - baseline_values
            comparisons.append(
                ArtifactComparison(
                    artifact_type=baseline_artifact.artifact_type,
                    physical_quantity=baseline_artifact.physical_quantity,
                    units=baseline_artifact.units,
                    baseline_artifact_id=baseline_artifact.artifact_id,
                    candidate_artifact_id=candidate_artifact.artifact_id,
                    sample_count=int(delta.size),
                    mean_delta=float(np.mean(delta)),
                    root_mean_square_delta=float(np.sqrt(np.mean(delta**2))),
                    maximum_absolute_delta=float(np.max(np.abs(delta))),
                )
            )
        return RunComparison(
            baseline_run_id=request.baseline_run_id,
            candidate_run_id=request.candidate_run_id,
            summary_deltas=summary_deltas,
            artifact_comparisons=tuple(comparisons),
        )

    def _require_completed_result(self, run_id: UUID) -> RunResult:
        result = self._run_service.result(run_id)
        if result is None:
            raise ValueError(f"run {run_id} does not have a completed result")
        return result

    def _load_numeric_artifact(self, relative_path: str) -> np.ndarray | None:
        root = self._run_service.artifact_root.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != ".npy" or not path.is_file():
            return None
        try:
            values = np.asarray(np.load(path, allow_pickle=False), dtype=float)
        except (OSError, ValueError):
            return None
        if values.ndim != 1 or values.size == 0 or values.size > 10_000:
            return None
        return values if np.isfinite(values).all() else None


def _is_numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _artifacts_are_compatible(baseline: ArtifactManifest, candidate: ArtifactManifest) -> bool:
    return (
        baseline.physical_quantity == candidate.physical_quantity
        and baseline.units == candidate.units
    )
