"""Interpolate a geological model and read it where the geophysics is."""

from importlib.util import find_spec

import numpy as np

from ofag.core.schemas import (
    Borehole,
    BoreholeOnSection,
    GeologicalModel,
    GeologicalSection,
    SectionGeometry,
)

#: What the convention cache calls this engine.
SUBJECT = "gempy.geology"


class GeologyService:
    """Evaluate stored geological models."""

    def dependency_available(self) -> bool:
        return find_spec("gempy") is not None

    def readiness(self, model: GeologicalModel) -> tuple[str, ...]:
        """What stops this model from being interpolated, engine included."""
        issues = list(model.readiness())
        if not self.dependency_available():
            issues.append(
                "The GemPy engine is not installed. Install the 'gempy' extra to "
                "interpolate geological models."
            )
            return tuple(issues)
        issues.extend(self.convention_issues())
        return tuple(issues)

    @staticmethod
    def convention_issues() -> tuple[str, ...]:
        """Confirm GemPy's conventions, once per session and engine version."""
        from ofag.core.conventions import engine_fingerprint, run_checks
        from ofag.engines.gempy import conventions

        outcome = run_checks(
            SUBJECT, engine_fingerprint("gempy", "gempy_engine", "numpy"), conventions.checks()
        )
        if outcome.unverified_reason is not None:
            return (f"{SUBJECT}: {outcome.unverified_reason}",)
        return tuple(
            f"{SUBJECT} failed the convention check {check.name!r}: {result.detail}. "
            f"This catches: {check.catches}"
            for check, result in outcome.failures
        )

    def section(self, model: GeologicalModel, section: SectionGeometry) -> GeologicalSection:
        """Which unit occupies each cell of a vertical slice."""
        issues = self.readiness(model)
        if issues:
            raise ValueError("; ".join(issues))

        from ofag.engines.gempy.geology import evaluate_at

        points = section.sample_points()
        resolved = evaluate_at(model, points)
        distances = np.linspace(0.0, section.length_m, section.samples_along)
        elevations = np.linspace(section.min_z_m, section.max_z_m, section.samples_vertical)
        return GeologicalSection(
            samples_along=section.samples_along,
            samples_vertical=section.samples_vertical,
            distances_m=tuple(float(value) for value in distances),
            elevations_m=tuple(float(value) for value in elevations),
            unit_ids=tuple(resolved),
            undecided_cells=sum(1 for unit_id in resolved if unit_id is None),
            boreholes=tuple(_on_section(hole, section) for hole in model.boreholes),
        )


def _on_section(hole: Borehole, section: SectionGeometry) -> BoreholeOnSection:
    """Project a hole onto a section, path and contacts together."""
    start = np.asarray(section.start_m, dtype=float)
    end = np.asarray(section.end_m, dtype=float)
    axis = end - start
    length = float(np.hypot(*axis))
    direction = axis / length if length > 0 else np.array([1.0, 0.0])
    normal = np.array([-direction[1], direction[0]])

    def place(east: float, north: float) -> tuple[float, float]:
        offset = np.array([east, north]) - start
        return float(offset @ direction), float(offset @ normal)

    # Sampled rather than assumed straight: a surveyed hole bends, and two points would
    # draw a chord through ground it never entered.
    depths = np.linspace(0.0, hole.total_depth_m, 33)
    path = [hole.position_at(float(depth)) for depth in depths]
    contacts = [(unit_id, hole.position_at(depth)) for _, unit_id, depth in hole.contacts()]
    collar_distance, collar_offline = place(hole.collar_x_m, hole.collar_y_m)
    return BoreholeOnSection(
        borehole_id=hole.borehole_id,
        name=hole.name,
        collar_distance_m=collar_distance,
        collar_offline_m=collar_offline,
        path_distance_m=tuple(place(east, north)[0] for east, north, _ in path),
        path_elevation_m=tuple(elevation for _, _, elevation in path),
        contact_distance_m=tuple(place(east, north)[0] for _, (east, north, _) in contacts),
        contact_elevation_m=tuple(elevation for _, (_, _, elevation) in contacts),
        contact_unit_ids=tuple(unit_id for unit_id, _ in contacts),
    )
