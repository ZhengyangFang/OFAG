"""Lossless run reuse and dataset identity, shared by the GUI and agents."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ofag.core.schemas import ExecutorSpec, QuantitySpec, RunSpec, TensorMeshSpec, TreeMeshSpec


class RunInputs(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    mesh: TensorMeshSpec | TreeMeshSpec | None = None
    parameters: dict[str, QuantitySpec | float | int | str | bool] = Field(default_factory=dict)
    seed: int = 0
    executor: ExecutorSpec = Field(default_factory=ExecutorSpec)


def uses_dataset(spec: RunSpec, dataset: Any) -> bool:
    ids = set(spec.source_dataset_ids) | {
        channel.source_dataset_id for channel in spec.datasets if channel.source_dataset_id
    }
    if ids:
        return dataset.dataset_id in ids
    if str(spec.run_id) in map(str, dataset.payload.get("used_by_runs") or ()):
        return True
    # Legacy records carry the dataset identity in DatasetSpec.
    return dataset.dataset_id in {spec.dataset.dataset_id} | {
        channel.dataset.dataset_id for channel in spec.datasets
    }


def reuse_spec(spec: RunSpec, **changes: Any) -> RunSpec:
    payload = spec.model_dump(mode="json")
    payload.update(run_id=str(uuid4()))
    payload.update(changes)
    return RunSpec.model_validate(payload)
