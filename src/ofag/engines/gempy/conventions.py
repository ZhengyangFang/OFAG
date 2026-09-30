"""What has to hold about GemPy before a geological model is interpolated."""

import numpy as np

from ofag.core.conventions import ConventionCheck, ConventionResult
from ofag.core.schemas import (
    GeologicalModel,
    ModelExtent,
    StratigraphicUnit,
    StructuralGroup,
    SurfaceOrientation,
    SurfacePoint,
)

__all__ = ["surface_points_are_a_base", "dip_azimuth_descends", "checks"]

#: A box big enough that the probes are nowhere near its walls, small enough that the
#: interpolation is instant.
_EXTENT = (0.0, 100.0, 0.0, 100.0, -60.0, 0.0)
#: Where the contact crosses the box's centre.
_CONTACT_Z = -20.0
#: Far enough either side of centre that a 20 degree dip moves the contact by 15 m,
#: which is three times the probe offset below.
_ARM = 40.0
_DIP = 20.0


def _two_unit_model(
    dip_degrees: float, azimuth_degrees: float, *, along_strike_only: bool = False
) -> tuple[GeologicalModel, object]:
    """Cover over bedrock, split by one plane of exactly known attitude."""
    from uuid import uuid4

    cover, bedrock = uuid4(), uuid4()
    centre = np.array([50.0, 50.0])
    descent = np.array([np.sin(np.radians(azimuth_degrees)), np.cos(np.radians(azimuth_degrees))])
    slope = np.tan(np.radians(dip_degrees))

    def height(x: float, y: float) -> float:
        return float(_CONTACT_Z - slope * float(np.dot(np.array([x, y]) - centre, descent)))

    if along_strike_only:
        strike = np.array([-descent[1], descent[0]])
        corners = [tuple(centre + strike * reach) for reach in (-30.0, -10.0, 10.0, 30.0)]
    else:
        corners = [(20.0, 20.0), (80.0, 20.0), (20.0, 80.0), (80.0, 80.0), (50.0, 50.0)]
    model = GeologicalModel(
        name="convention probe",
        extent=ModelExtent(
            min_x_m=_EXTENT[0],
            max_x_m=_EXTENT[1],
            min_y_m=_EXTENT[2],
            max_y_m=_EXTENT[3],
            min_z_m=_EXTENT[4],
            max_z_m=_EXTENT[5],
        ),
        units=(
            StratigraphicUnit(unit_id=cover, name="Cover", colour="#c9a227"),
            StratigraphicUnit(unit_id=bedrock, name="Bedrock", colour="#7d5a3c"),
        ),
        groups=(StructuralGroup(name="Probe", unit_ids=(cover, bedrock)),),
        surface_points=tuple(
            SurfacePoint(unit_id=cover, x_m=x, y_m=y, z_m=height(x, y)) for x, y in corners
        ),
        orientations=(
            SurfaceOrientation(
                unit_id=cover,
                x_m=float(centre[0]),
                y_m=float(centre[1]),
                z_m=_CONTACT_Z,
                dip_degrees=dip_degrees,
                dip_azimuth_degrees=azimuth_degrees,
            ),
        ),
    )
    return model, cover


def surface_points_are_a_base() -> ConventionCheck:
    """A unit's surface points are the contact it rests on, not its roof."""

    def run() -> ConventionResult:
        from ofag.engines.gempy.geology import evaluate_at

        model, cover = _two_unit_model(0.0, 0.0)
        above, below = evaluate_at(
            model, np.array([[50.0, 50.0, _CONTACT_Z + 8.0], [50.0, 50.0, _CONTACT_Z - 8.0]])
        )
        passed = above == cover and below is not None and below != cover
        return ConventionResult(
            passed=passed,
            detail=(
                f"with the cover's points on a flat contact at {_CONTACT_Z:.0f} m, the engine "
                f"puts {_CONTACT_Z + 8.0:+.0f} m in "
                f"{'the cover' if above == cover else 'the lower unit'} and "
                f"{_CONTACT_Z - 8.0:+.0f} m in "
                f"{'the cover' if below == cover else 'the lower unit'}"
            ),
        )

    return ConventionCheck(
        name="surface points are a unit's base",
        catches=(
            "attaching a contact to the unit above it instead of the unit below, which builds "
            "a model one unit out of register and interpolates without complaint"
        ),
        against=(
            "the definition the schema now states and the pile relies on -- the lowest unit "
            "needs no points because nothing bounds it below"
        ),
        run=run,
    )


def dip_azimuth_descends() -> ConventionCheck:
    """Dip azimuth points the way the surface goes down, not up."""

    def run() -> ConventionResult:
        from ofag.engines.gempy.geology import evaluate_at

        # Dipping due east, so the contact is deeper in the east.
        model, cover = _two_unit_model(_DIP, 90.0, along_strike_only=True)
        east, west = evaluate_at(
            model,
            np.array([[50.0 + _ARM, 50.0, _CONTACT_Z], [50.0 - _ARM, 50.0, _CONTACT_Z]]),
        )
        passed = east == cover and west is not None and west != cover
        drop = _ARM * float(np.tan(np.radians(_DIP)))
        return ConventionResult(
            passed=passed,
            detail=(
                f"dipping {_DIP:.0f} deg toward 090, so the contact is {drop:.0f} m deeper "
                f"{_ARM:.0f} m east and {drop:.0f} m shallower {_ARM:.0f} m west. At "
                f"{_CONTACT_Z:.0f} m the engine puts the east in "
                f"{'the cover' if east == cover else 'the lower unit'} and the west in "
                f"{'the cover' if west == cover else 'the lower unit'}"
            ),
        )

    return ConventionCheck(
        name="dip azimuth is the direction of descent",
        catches=(
            "reading dip azimuth as the direction the surface rises, a 180 degree error that "
            "put a basement 2 km too high on one side of a case and reported nothing (F028)"
        ),
        against="the field definition of dip azimuth, and the plane the points were generated on",
        run=run,
    )


def checks() -> tuple[ConventionCheck, ...]:
    return (surface_points_are_a_base(), dip_azimuth_descends())
