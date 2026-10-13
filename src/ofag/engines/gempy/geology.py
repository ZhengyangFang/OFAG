"""Build and evaluate a GemPy model from OFAG's own geological schema."""

from typing import Any
from uuid import UUID

import numpy as np

from ofag.core.schemas import (
    GeologicalModel,
    StratigraphicRelation,
    StructuralGroup,
    SurfaceOrientation,
)

ENGINE = "gempy"

#: GemPy names its units with strings, and OFAG names them with ids.
_UNIT_PREFIX = "unit_"


def pole_vector(orientation: SurfaceOrientation) -> tuple[float, float, float]:
    """The upward normal of a bed, from its dip and dip azimuth."""
    dip = np.radians(orientation.dip_degrees)
    azimuth = np.radians(orientation.dip_azimuth_degrees)
    scale = float(orientation.polarity)
    return (
        scale * float(np.sin(dip) * np.sin(azimuth)),
        scale * float(np.sin(dip) * np.cos(azimuth)),
        scale * float(np.cos(dip)),
    )


def build_geomodel(model: GeologicalModel) -> Any:
    """Assemble a computable GemPy model from OFAG's stored inputs."""
    import gempy as gp  # type: ignore[import-untyped]
    from gempy.core.data import StructuralFrame  # type: ignore[import-untyped]

    issues = model.readiness()
    if issues:
        raise ValueError("; ".join(issues))

    geo_model = gp.create_geomodel(
        project_name=str(model.geological_model_id),
        extent=list(model.extent.as_tuple()),
        # The dense grid is never read -- every result comes from the custom grid of
        # section samples -- so it is kept coarse rather than being sized for a picture
        # nothing draws.
        resolution=[2, 2, 2],
        structural_frame=StructuralFrame.initialize_default_structure(),
    )

    _install_units(geo_model, model)

    for unit_id in _interpolated_units(model):
        # Picks and logged contacts alike: a borehole's contact is a surface point with
        # a stronger claim, not a different kind of constraint.
        points = [point for point in model.all_surface_points() if point.unit_id == unit_id]
        if points:
            gp.add_surface_points(
                geo_model,
                x=[point.x_m for point in points],
                y=[point.y_m for point in points],
                z=[point.z_m for point in points],
                elements_names=[_element_name(unit_id)] * len(points),
                nugget=[point.nugget for point in points],
            )
        attitudes = [item for item in model.orientations if item.unit_id == unit_id]
        if attitudes:
            gp.add_orientations(
                geo_model,
                x=[item.x_m for item in attitudes],
                y=[item.y_m for item in attitudes],
                z=[item.z_m for item in attitudes],
                elements_names=[_element_name(unit_id)] * len(attitudes),
                pole_vector=[pole_vector(item) for item in attitudes],
                nugget=[item.nugget for item in attitudes],
            )

    # Rescaling to the data's own extent; without it GemPy interpolates under a default
    # transform and warns that the result is not to be trusted.
    geo_model.update_transform()
    return geo_model


def evaluate_at(model: GeologicalModel, points_m: np.ndarray) -> list[UUID | None]:
    """Which unit occupies each of `points_m`, as OFAG unit ids."""
    import gempy as gp

    if points_m.ndim != 2 or points_m.shape[1] != 3:
        raise ValueError("points_m must have shape (n, 3)")
    if not points_m.size:
        return []

    geo_model = build_geomodel(model)
    gp.set_custom_grid(geo_model.grid, points_m)
    solution = gp.compute_model(geo_model)
    raw = np.asarray(solution.raw_arrays.custom, dtype=float)
    if raw.size != points_m.shape[0]:
        raise ValueError(f"the engine returned {raw.size} values for {points_m.shape[0]} points")

    # GemPy numbers its elements 1..n from the top down and appends a basement of its
    # own, so its ids line up one-for-one with OFAG's pile: the engine's basement is
    # OFAG's lowest unit.
    ordered = list(model.pile())
    resolved: list[UUID | None] = []
    for value in raw:
        nearest = int(round(value))
        if abs(value - nearest) > _INTEGER_TOLERANCE:
            resolved.append(None)
        elif 1 <= nearest <= len(ordered):
            resolved.append(ordered[nearest - 1])
        else:
            resolved.append(None)
    return resolved


#: How far a returned id may sit from a whole number and still name that unit.
_INTEGER_TOLERANCE = 1e-6


def _interpolated_units(model: GeologicalModel) -> list[UUID]:
    """The units that own a surface, which is every unit but the basement."""
    basement = model.basement_unit_id()
    return [unit_id for unit_id in model.pile() if unit_id != basement]


def _element_name(unit_id: UUID) -> str:
    return f"{_UNIT_PREFIX}{unit_id.hex}"


def _install_units(geo_model: Any, model: GeologicalModel) -> None:
    """Replace GemPy's placeholder pile with this model's groups."""
    from gempy.core.data import OrientationsTable, StructuralElement, SurfacePointsTable
    from gempy.core.data import StructuralGroup as EngineGroup

    interpolated = set(_interpolated_units(model))
    if not interpolated:
        raise ValueError("a geological model needs a surface to interpolate, not only a basement")

    groups = []
    for group in model.groups:
        elements = [
            StructuralElement(
                name=_element_name(unit_id),
                color=_colour(model, unit_id),
                surface_points=SurfacePointsTable.initialize_empty(),
                orientations=OrientationsTable.initialize_empty(),
            )
            for unit_id in group.unit_ids
            if unit_id in interpolated
        ]
        # A group whose only member was the basement has nothing left to interpolate;
        # the engine supplies that unit itself.
        if elements:
            groups.append(
                EngineGroup(
                    name=group.name,
                    elements=elements,
                    structural_relation=_relation(group),
                )
            )
    geo_model.structural_frame.structural_groups = groups


def _colour(model: GeologicalModel, unit_id: UUID) -> str:
    unit = model.unit(unit_id)
    return unit.colour if unit is not None else "#7d5a3c"


def _relation(group: StructuralGroup) -> Any:
    """Map OFAG's contact relation onto the engine's stack relation."""
    # Imported as a module so the ignore fits on one line under the line cap; ruff's
    # formatter otherwise wraps the `from` form and strands the comment.
    import gempy_engine.core.data.stack_relation_type as stack  # type: ignore[import-untyped]

    match group.relation:
        case StratigraphicRelation.ERODE:
            return stack.StackRelationType.ERODE
        case StratigraphicRelation.ONLAP:
            return stack.StackRelationType.ONLAP
        case StratigraphicRelation.FAULT:
            return stack.StackRelationType.FAULT
