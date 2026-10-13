"""Recompute saved model labels under stated interpretation choices."""

from dataclasses import dataclass
from itertools import product

import numpy as np

from ofag.agent.volumes import CellGrid
from ofag.core.schemas import UnitRule, UnitRuleKind
from ofag.services.interpretation_service import (
    CellSection,
    InterpretationService,
    LayeredSection,
)


@dataclass(frozen=True)
class Stability:
    baseline: np.ndarray
    agreement: np.ndarray
    invariant: np.ndarray
    variant_count: int
    depth_profile: list[dict[str, float | int]]

    @property
    def invariant_share(self) -> float:
        return float(np.mean(self.invariant))

    @property
    def mean_agreement(self) -> float:
        return float(np.mean(self.agreement))


def evaluate(
    grid: CellGrid,
    rules: tuple[UnitRule, ...],
    surfaces: dict[str, np.ndarray],
    sections: dict[str, LayeredSection | CellSection],
    *,
    rule_name: str,
    thresholds: list[float],
    reaches_m: list[float],
    depth_limits_m: list[float],
) -> Stability:
    """Compare all parameter combinations with the saved recipe's baseline."""
    indices = [index for index, rule in enumerate(rules) if rule.name == rule_name]
    if len(indices) != 1 or rules[indices[0]].kind is not UnitRuleKind.PROPERTY_THRESHOLD:
        raise ValueError("Name one property-threshold rule in the saved model recipe.")
    axes = (thresholds, reaches_m, depth_limits_m)
    if any(not 2 <= len(values) <= 5 for values in axes):
        raise ValueError("Each parameter needs 2 to 5 stated values.")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not np.isfinite(value)
        or value <= 0
        for values in axes
        for value in values
    ):
        raise ValueError("Thresholds, reaches and depth limits must be positive and finite.")
    count = len(thresholds) * len(reaches_m) * len(depth_limits_m)
    if count > 125:
        raise ValueError("At most 125 parameter combinations are supported.")

    service = InterpretationService()
    def assign(choices: tuple[UnitRule, ...]) -> np.ndarray:
        return service.assign_units(
            choices,
            cell_centres_m=grid.cell_centres_m,
            cell_volume_m3=grid.cell_volume_m3,
            depth_below_ground_m=grid.depth_below_ground_m,
            surfaces=surfaces,
            sections=sections,
        ).unit

    baseline = assign(rules)
    agreement_count = np.zeros(grid.cells, dtype=np.uint16)
    invariant = np.ones(grid.cells, dtype=bool)
    index = indices[0]
    for threshold, reach, limit in product(*axes):
        changed = list(rules)
        changed[index] = UnitRule.model_validate(
            rules[index].model_dump()
            | {
                "threshold": threshold,
                "reach_m": reach,
                "resolved_to_depth_m": limit,
            }
        )
        labels = assign(tuple(changed))
        same = labels == baseline
        agreement_count += same
        invariant &= same
    agreement = agreement_count / count
    profile = [
        {
            "depth_m": float(depth),
            "cells": int(np.sum(grid.depth_below_ground_m == depth)),
            "mean_agreement": float(np.mean(agreement[grid.depth_below_ground_m == depth])),
            "invariant_share": float(np.mean(invariant[grid.depth_below_ground_m == depth])),
        }
        for depth in np.unique(grid.depth_below_ground_m)
    ]
    return Stability(
        baseline=baseline,
        agreement=agreement,
        invariant=invariant,
        variant_count=count,
        depth_profile=profile,
    )
