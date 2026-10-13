"""Read finished inversions together into a geological model."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from ofag.core.schemas import (
    InterpretationReport,
    SurfaceFitReport,
    UnitReport,
    UnitRule,
    UnitRuleKind,
)

Predictor = Callable[[np.ndarray], np.ndarray]
"""A fitted surface, asked for a value at any (x, y)."""

Estimator = Callable[[np.ndarray, np.ndarray], Predictor]
"""A way of turning picks into a Predictor."""


__all__ = [
    "InterpretationService",
    "LayeredSection",
    "ContactPicks",
    "FittedSurface",
    "InterpretedModel",
    "ResolvedBand",
]


@dataclass(frozen=True)
class LayeredSection:
    """A stitched batch of 1D models: one column per station."""

    easting_m: np.ndarray
    northing_m: np.ndarray
    values: np.ndarray
    layer_top_depth_m: np.ndarray

    def __post_init__(self) -> None:
        if self.values.shape != (self.easting_m.size, self.layer_top_depth_m.size):
            raise ValueError(
                f"values is {self.values.shape}, expected "
                f"({self.easting_m.size}, {self.layer_top_depth_m.size})"
            )

    @property
    def stations_m(self) -> np.ndarray:
        return np.column_stack([self.easting_m, self.northing_m])

    def layer_of(self, depth_m: np.ndarray) -> np.ndarray:
        """Which layer holds each depth."""
        return np.clip(
            np.searchsorted(self.layer_top_depth_m, depth_m, side="right") - 1,
            0,
            self.layer_top_depth_m.size - 1,
        )


@dataclass(frozen=True)
class CellSection:
    """Cell-centre sampling in project coordinates, with an explicit support radius."""

    centres_m: np.ndarray
    values: np.ndarray

    def sample(self, targets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        from scipy.spatial import cKDTree  # type: ignore[import-untyped]

        distance, nearest = cKDTree(self.centres_m).query(targets)
        values = self.values[nearest].astype(float).copy()
        outside = (targets[:, 2] < self.centres_m[:, 2].min()) | (
            targets[:, 2] > self.centres_m[:, 2].max()
        )
        values[outside] = np.nan
        return distance, values


class CoverageConvention(StrEnum):
    """What has already been done to a stored coverage array."""

    #: The cumulative sensitivity as summed, nothing divided out.
    RAW = "raw"
    #: Already divided by cell size, still linear. pyGIMLi's MeshMethodManager.
    PER_AREA = "per_area"
    #: Already divided by cell size and logged. pyGIMLi's ERTManager, and what this
    #: project's ERT runs store.
    LOG10_PER_AREA = "log10_per_area"


@dataclass(frozen=True)
class ResolvedBand:
    """How deep a recovered model actually carries information."""

    deepest_m: float
    #: The decaying quantity, one value per depth, so a reader sees the shape rather
    #: than only where it was cut.
    profile: np.ndarray
    depth_m: np.ndarray
    threshold: float
    evidence: str = "departure from the starting model"

    def describe(self) -> str:
        pairs = ", ".join(
            f"{depth:.0f} m {value:.2f}"
            for depth, value in zip(self.depth_m, self.profile, strict=True)
            if value >= self.threshold / 4
        )
        return f"{self.evidence} by depth: {pairs}"


@dataclass(frozen=True)
class ContactPicks:
    """Where a contact was picked, and at how many stations it was not."""

    locations_m: np.ndarray
    depth_m: np.ndarray
    attempted: int
    band_m: tuple[float, float]


@dataclass(frozen=True)
class FittedSurface:
    """A surface that can be asked for a value anywhere, and its own error."""

    predict: Predictor
    report: SurfaceFitReport


@dataclass(frozen=True)
class InterpretedModel:
    """A unit per cell, with what decided it and what that rested on."""

    #: Index into `rules`, or -1 where nothing claimed the cell.
    unit: np.ndarray
    #: The deciding method, per cell, as declared by the winning rule.
    source: np.ndarray
    #: Distance to the nearest measurement the winning rule used, or NaN where the rule
    #: is a surface fitted everywhere or a remainder.
    support_distance_m: np.ndarray
    report: InterpretationReport


#: The estimators `fit_surface` chooses between.
_SMOOTHINGS = (1.0e2, 1.0e4, 1.0e6)


class InterpretationService:
    """Build a geological model from finished inversions."""

    def resolved_band(
        self,
        section: LayeredSection,
        starting_values: np.ndarray,
        *,
        threshold: float = 0.1,
    ) -> ResolvedBand:
        """The deepest layer that moved away from its prior, and by how much."""
        starting = np.broadcast_to(np.atleast_1d(starting_values), section.values.shape)
        departure = np.abs(np.log10(section.values) - np.log10(starting))
        by_layer = np.median(departure, axis=0)
        moved = np.flatnonzero(by_layer >= threshold)
        deepest = float(section.layer_top_depth_m[moved[-1]]) if moved.size else 0.0
        return ResolvedBand(
            deepest_m=deepest,
            profile=by_layer,
            depth_m=section.layer_top_depth_m,
            threshold=threshold,
        )

    def resolved_band_from_sensitivity(
        self,
        depth_m: np.ndarray,
        coverage: np.ndarray,
        cell_size: np.ndarray,
        *,
        coverage_is: CoverageConvention,
        threshold: float = 0.1,
        surface_m: float = 10.0,
        step_m: float = 5.0,
    ) -> ResolvedBand:
        """How deep a meshed section carries information, from its own coverage."""
        stored = np.asarray(coverage, dtype=float)
        size = np.maximum(np.asarray(cell_size, dtype=float), 1e-12)
        if coverage_is is CoverageConvention.LOG10_PER_AREA:
            density = 10.0**stored
        else:
            # A sensitivity is a sum of squares and cannot be negative, so a negative
            # value means the array is logged and the caller has said it is not.
            if np.any(stored < 0.0):
                raise ValueError(
                    f"coverage declared {coverage_is} holds {int(np.sum(stored < 0.0))} "
                    f"negative values (min {float(stored.min()):.3f}); a sensitivity cannot "
                    f"be negative, so this is a logged array -- pass "
                    f"{CoverageConvention.LOG10_PER_AREA} if it came from pyGIMLi's ERTManager"
                )
            density = stored / size if coverage_is is CoverageConvention.RAW else stored
        depth = np.asarray(depth_m, dtype=float)
        near_surface = density[depth <= surface_m]
        if not near_surface.size:
            raise ValueError(f"no cells within {surface_m} m of the surface to normalise against")
        top = float(np.median(near_surface))

        grid = np.arange(step_m / 2.0, float(depth.max()), step_m)
        profile = np.array(
            [
                float(np.median(density[np.abs(depth - centre) <= step_m / 2.0]) / top)
                if np.any(np.abs(depth - centre) <= step_m / 2.0)
                else np.nan
                for centre in grid
            ]
        )
        # Against the running minimum from the surface down, not the profile itself.
        envelope = np.minimum.accumulate(np.nan_to_num(profile, nan=np.inf))
        crossed = np.flatnonzero(envelope < threshold)
        deepest = float(grid[crossed[0]]) if crossed.size else float(depth.max())
        return ResolvedBand(
            deepest_m=deepest,
            profile=profile,
            depth_m=grid,
            threshold=threshold,
            evidence=(
                "sensitivity per unit area, against the top of the section, "
                f"from {coverage_is} coverage"
            ),
        )

    def pick_contact(
        self,
        section: LayeredSection,
        band_m: tuple[float, float],
        *,
        minimum_slope: float = 0.3,
        increasing: bool = True,
        within: np.ndarray | None = None,
    ) -> ContactPicks:
        """The sharpest step in a layered property, per station, inside a band."""
        middle = 0.5 * (section.layer_top_depth_m[:-1] + section.layer_top_depth_m[1:])
        # A recovered value can sit exactly on a bound, or come back as a null the
        # reader did not catch, and log10 of either poisons the whole column rather than
        # the one layer.
        values = np.maximum(np.asarray(section.values, dtype=float), 1.0e-6)
        # The depth axis, floored just under the shallowest real layer rather than at a
        # round number.
        tops = np.asarray(section.layer_top_depth_m, dtype=float)
        shallowest = tops[tops > 0].min() if np.any(tops > 0) else 1.0
        slope = np.diff(np.log10(values), axis=1) / np.diff(
            np.log10(np.maximum(tops, shallowest / 2.0))
        )
        if not increasing:
            slope = -slope
        in_band = (middle >= band_m[0]) & (middle <= band_m[1])
        chosen = np.arange(section.easting_m.size) if within is None else np.flatnonzero(within)
        depth = np.full(section.easting_m.size, np.nan)
        for index in chosen:
            masked = np.where(in_band, slope[index], -np.inf)
            if masked.max() > minimum_slope:
                depth[index] = middle[int(np.argmax(masked))]
        found = np.isfinite(depth)
        return ContactPicks(
            locations_m=section.stations_m[found],
            depth_m=depth[found],
            attempted=int(chosen.size),
            band_m=band_m,
        )

    def fit_surface(
        self, name: str, picks: ContactPicks, *, targets_m: np.ndarray
    ) -> FittedSurface:
        """Fit the picks with whichever estimator predicts a held-out pick best."""
        from scipy.spatial import cKDTree

        if picks.depth_m.size < 3:
            raise ValueError(f"surface {name!r} needs at least three picks")
        candidates = self._candidate_estimators()
        scores = {label: self._held_out_error(build, picks) for label, build in candidates.items()}
        best = min(scores, key=lambda label: scores[label])
        predict = candidates[best](picks.locations_m, picks.depth_m)
        furthest = float(cKDTree(picks.locations_m).query(targets_m[:, :2])[0].max())
        return FittedSurface(
            predict=predict,
            report=SurfaceFitReport(
                surface=name,
                estimator=best,
                held_out_error=float(scores[best]),
                pick_spread=float(picks.depth_m.std()),
                candidates={label: float(value) for label, value in scores.items()},
                pick_count=int(picks.depth_m.size),
                furthest_from_a_pick_m=furthest,
            ),
        )

    def assign_units(
        self,
        rules: tuple[UnitRule, ...],
        *,
        cell_centres_m: np.ndarray,
        cell_volume_m3: np.ndarray,
        depth_below_ground_m: np.ndarray,
        surfaces: dict[str, np.ndarray],
        sections: dict[str, LayeredSection | CellSection] | None = None,
    ) -> InterpretedModel:
        """Label every cell, first matching rule wins, and say what decided it."""
        from scipy.spatial import cKDTree

        count = cell_centres_m.shape[0]
        unit = np.full(count, -1, dtype=np.int16)
        source = np.full(count, "", dtype=object)
        support = np.full(count, np.nan)
        unclaimed = np.ones(count, dtype=bool)
        total = float(cell_volume_m3.sum())
        beyond_reach = np.zeros(len(rules))

        for index, rule in enumerate(rules):
            distance = np.full(count, np.nan)
            if rule.kind is UnitRuleKind.REMAINDER:
                matches = unclaimed.copy()
            elif rule.kind is UnitRuleKind.BELOW_SURFACE:
                matches = unclaimed & (cell_centres_m[:, 2] <= self._surface(surfaces, rule))
            elif rule.kind is UnitRuleKind.ABOVE_SURFACE:
                matches = unclaimed & (depth_below_ground_m <= self._surface(surfaces, rule))
            else:
                section = (sections or {}).get(rule.section or "")
                if section is None:
                    raise KeyError(f"rule {rule.name!r} names unknown section {rule.section!r}")
                if isinstance(section, CellSection):
                    if rule.reach_m is None:
                        raise ValueError(
                            "Cell-model rules need an explicit reach_m support radius."
                        )
                    distance, sampled = section.sample(cell_centres_m)
                else:
                    distance, nearest = cKDTree(section.stations_m).query(cell_centres_m[:, :2])
                    sampled = section.values[nearest, section.layer_of(depth_below_ground_m)]
                crossed = (
                    sampled < rule.threshold if rule.below_threshold else sampled > rule.threshold
                )
                matches = unclaimed & crossed & (depth_below_ground_m >= rule.resolved_from_depth_m)
            if rule.reach_m is not None and rule.kind is UnitRuleKind.PROPERTY_THRESHOLD:
                out_of_reach = distance > rule.reach_m
                beyond_reach[index] = (
                    float(cell_volume_m3[out_of_reach].sum() / total) if total else 0.0
                )
                matches &= ~out_of_reach
            unit[matches] = index
            source[matches] = rule.source
            support[matches] = distance[matches]
            unclaimed &= ~matches

        reports = []
        for index, rule in enumerate(rules):
            selected = unit == index
            weight = cell_volume_m3[selected]
            reports.append(
                UnitReport(
                    name=rule.name,
                    source=rule.source,
                    cell_count=int(selected.sum()),
                    volume_share=float(weight.sum() / total) if total else 0.0,
                    beyond_reach_share=float(beyond_reach[index]),
                )
            )
        return InterpretedModel(
            unit=unit,
            source=source,
            support_distance_m=support,
            report=InterpretationReport(
                units=tuple(reports),
                cell_count=count,
                undecided_cells=int(unclaimed.sum()),
            ),
        )

    @staticmethod
    def _surface(surfaces: dict[str, np.ndarray], rule: UnitRule) -> np.ndarray:
        try:
            return surfaces[rule.surface or ""]
        except KeyError:
            raise KeyError(f"rule {rule.name!r} names unknown surface {rule.surface!r}") from None

    @staticmethod
    def _candidate_estimators() -> dict[str, Estimator]:
        from scipy.interpolate import RBFInterpolator  # type: ignore[import-untyped]
        from scipy.spatial import cKDTree

        def constant(points: np.ndarray, values: np.ndarray) -> Predictor:
            mean = float(values.mean())
            return lambda targets: np.full(targets.shape[0], mean)

        def plane(points: np.ndarray, values: np.ndarray) -> Predictor:
            origin = points.mean(axis=0)
            design = np.column_stack([points - origin, np.ones(points.shape[0])])
            coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
            return lambda targets: (
                np.column_stack([targets[:, :2] - origin, np.ones(targets.shape[0])]) @ coefficients
            )

        def nearest(points: np.ndarray, values: np.ndarray) -> Predictor:
            tree = cKDTree(points)
            return lambda targets: values[tree.query(targets[:, :2])[1]]

        def smooth(strength: float) -> Estimator:
            def build(points: np.ndarray, values: np.ndarray) -> Predictor:
                fitted = RBFInterpolator(points, values, kernel="linear", smoothing=strength)
                return lambda targets: fitted(targets[:, :2])

            return build

        return {
            "constant": constant,
            "plane": plane,
            "nearest": nearest,
            **{f"smooth {strength:.0e}": smooth(strength) for strength in _SMOOTHINGS},
        }

    @staticmethod
    def _held_out_error(build: Estimator, picks: ContactPicks) -> float:
        errors = np.empty(picks.depth_m.size)
        for index in range(picks.depth_m.size):
            keep = np.ones(picks.depth_m.size, dtype=bool)
            keep[index] = False
            try:
                predict = build(picks.locations_m[keep], picks.depth_m[keep])
                errors[index] = predict(picks.locations_m[index : index + 1])[0]
            except Exception:  # noqa: BLE001 - an estimator that cannot fit has not won
                return float("inf")
        return float(np.sqrt(np.mean(np.square(errors - picks.depth_m))))
