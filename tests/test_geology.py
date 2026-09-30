"""Structural modelling: OFAG's conventions, held against the engine's."""

import math
from importlib.util import find_spec
from uuid import UUID, uuid4

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.schemas import (
    Borehole,
    BoreholeInterval,
    BoreholeSurveyStation,
    GeologicalModel,
    LogKind,
    ModelExtent,
    SectionGeometry,
    StratigraphicRelation,
    StratigraphicUnit,
    StructuralGroup,
    SurfaceOrientation,
    SurfacePoint,
)
from ofag.engines.gempy.geology import pole_vector
from ofag.services.geology_service import GeologyService

needs_gempy = pytest.mark.skipif(
    find_spec("gempy") is None, reason="the gempy extra is not installed"
)

#: A gently east-dipping two-layer sequence, the shape of a weathering profile.
DIP_DEGREES = 20.0


def _sloping(intercept_m: float):
    """The plane through (50, intercept) dipping DIP_DEGREES towards Easting."""

    def at(x_m: float) -> float:
        return intercept_m - (x_m - 50.0) * float(np.tan(np.radians(DIP_DEGREES)))

    return at


def _weathering_profile() -> tuple[GeologicalModel, UUID, UUID, UUID]:
    cover, saprolite, bedrock = uuid4(), uuid4(), uuid4()
    base_cover, base_saprolite = _sloping(-12.0), _sloping(-32.0)
    model = GeologicalModel(
        name="Hillslope",
        extent=ModelExtent(min_x_m=0, max_x_m=100, min_y_m=-5, max_y_m=5, min_z_m=-60, max_z_m=0),
        units=(
            StratigraphicUnit(unit_id=cover, name="Cover", colour="#c9a227"),
            StratigraphicUnit(unit_id=saprolite, name="Saprolite", colour="#9f5f7d"),
            StratigraphicUnit(unit_id=bedrock, name="Bedrock", colour="#7d5a3c"),
        ),
        groups=(
            StructuralGroup(
                name="Regolith",
                relation=StratigraphicRelation.ERODE,
                unit_ids=(cover, saprolite, bedrock),
            ),
        ),
        surface_points=tuple(
            [
                SurfacePoint(unit_id=cover, x_m=x, y_m=0.0, z_m=base_cover(x))
                for x in (10.0, 50.0, 90.0)
            ]
            + [
                SurfacePoint(unit_id=saprolite, x_m=x, y_m=0.0, z_m=base_saprolite(x))
                for x in (10.0, 50.0, 90.0)
            ]
        ),
        orientations=(
            SurfaceOrientation(
                unit_id=cover,
                x_m=50.0,
                y_m=0.0,
                z_m=-12.0,
                dip_degrees=DIP_DEGREES,
                dip_azimuth_degrees=90.0,
            ),
            SurfaceOrientation(
                unit_id=saprolite,
                x_m=50.0,
                y_m=0.0,
                z_m=-32.0,
                dip_degrees=DIP_DEGREES,
                dip_azimuth_degrees=90.0,
            ),
        ),
    )
    return model, cover, saprolite, bedrock


def test_a_pole_vector_points_up_and_away_from_the_dip_direction() -> None:
    """Dip azimuth is clockwise from Northing, and x is Easting."""
    flat = pole_vector(
        SurfaceOrientation(
            unit_id=uuid4(), x_m=0, y_m=0, z_m=0, dip_degrees=0.0, dip_azimuth_degrees=0.0
        )
    )
    assert flat == pytest.approx((0.0, 0.0, 1.0), abs=1e-12)

    east = pole_vector(
        SurfaceOrientation(
            unit_id=uuid4(), x_m=0, y_m=0, z_m=0, dip_degrees=30.0, dip_azimuth_degrees=90.0
        )
    )
    # Dipping east: the normal tilts west (negative Easting is not it -- the normal
    # leans *towards* the dip azimuth in map view for an upward normal).
    assert east[0] == pytest.approx(0.5)
    assert east[1] == pytest.approx(0.0, abs=1e-12)
    assert east[2] == pytest.approx(np.cos(np.radians(30.0)))

    north = pole_vector(
        SurfaceOrientation(
            unit_id=uuid4(), x_m=0, y_m=0, z_m=0, dip_degrees=30.0, dip_azimuth_degrees=0.0
        )
    )
    assert north[0] == pytest.approx(0.0, abs=1e-12)
    assert north[1] == pytest.approx(0.5)

    overturned = pole_vector(
        SurfaceOrientation(
            unit_id=uuid4(),
            x_m=0,
            y_m=0,
            z_m=0,
            dip_degrees=0.0,
            dip_azimuth_degrees=0.0,
            polarity=-1,
        )
    )
    assert overturned == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)


def test_a_model_reports_what_it_still_needs_instead_of_failing_cryptically() -> None:
    """The engine's complaint is "Inconsistent shapes in StacksStructure"."""
    cover, bedrock = uuid4(), uuid4()
    model = GeologicalModel(
        name="Half built",
        extent=ModelExtent(min_x_m=0, max_x_m=100, min_y_m=-5, max_y_m=5, min_z_m=-60, max_z_m=0),
        units=(
            StratigraphicUnit(unit_id=cover, name="Cover", colour="#c9a227"),
            StratigraphicUnit(unit_id=bedrock, name="Bedrock", colour="#7d5a3c"),
        ),
        groups=(StructuralGroup(name="Regolith", unit_ids=(cover, bedrock)),),
        surface_points=(SurfacePoint(unit_id=cover, x_m=10.0, y_m=0.0, z_m=-12.0),),
    )

    issues = model.readiness()

    assert any("orientation" in issue for issue in issues)
    assert any("Cover" in issue and "1 surface point" in issue for issue in issues)
    # The bedrock is the basement: it is bounded above by the cover's base and below by
    # nothing, so demanding a surface for it would demand an invention.
    assert not any("Bedrock" in issue for issue in issues)


def test_the_lowest_unit_is_the_basement() -> None:
    model, _cover, _saprolite, bedrock = _weathering_profile()
    assert model.basement_unit_id() == bedrock
    assert model.readiness() == ()


def test_a_group_may_not_claim_a_unit_twice() -> None:
    cover = uuid4()
    with pytest.raises(ValidationError, match="twice"):
        StructuralGroup(name="Regolith", unit_ids=(cover, cover))


def test_a_surface_point_must_name_a_unit_the_model_declares() -> None:
    cover = uuid4()
    with pytest.raises(ValidationError, match="unknown unit"):
        GeologicalModel(
            name="Dangling",
            extent=ModelExtent(
                min_x_m=0, max_x_m=100, min_y_m=-5, max_y_m=5, min_z_m=-60, max_z_m=0
            ),
            units=(StratigraphicUnit(unit_id=cover, name="Cover", colour="#c9a227"),),
            groups=(StructuralGroup(name="Regolith", unit_ids=(cover,)),),
            surface_points=(SurfacePoint(unit_id=uuid4(), x_m=0.0, y_m=0.0, z_m=-1.0),),
        )


def test_a_section_samples_along_its_own_azimuth() -> None:
    """A resistivity line rarely runs along Easting, so a section is two points."""
    section = SectionGeometry(
        start_m=(0.0, 0.0),
        end_m=(30.0, 40.0),
        min_z_m=-10.0,
        max_z_m=0.0,
        samples_along=3,
        samples_vertical=2,
    )

    assert section.length_m == pytest.approx(50.0)
    points = section.sample_points()
    assert points.shape == (6, 3)
    # Row-major by elevation: the first row is the whole line at min_z.
    assert points[:3, 2] == pytest.approx([-10.0, -10.0, -10.0])
    assert points[3:, 2] == pytest.approx([0.0, 0.0, 0.0])
    assert points[1, :2] == pytest.approx([15.0, 20.0])


@needs_gempy
def test_a_dipping_bed_deepens_in_its_dip_direction() -> None:
    """The whole convention chain, checked against an analytic surface."""
    from ofag.engines.gempy.geology import evaluate_at

    model, cover, saprolite, bedrock = _weathering_profile()
    base_cover, base_saprolite = _sloping(-12.0), _sloping(-32.0)

    probes = [(x, z) for x in (20.0, 80.0) for z in (-5.0, -20.0, -30.0, -50.0)]
    points = np.array([[x, 0.0, z] for x, z in probes])

    resolved = evaluate_at(model, points)

    for (x, z), unit_id in zip(probes, resolved, strict=True):
        if z > base_cover(x):
            expected = cover
        elif z > base_saprolite(x):
            expected = saprolite
        else:
            expected = bedrock
        assert unit_id == expected, f"at ({x}, {z}) the model says the wrong unit"
    # West of centre the contacts are shallower, so a 20 m depth is already saprolite
    # there and still cover in the east: the section really dips.
    assert resolved[1] == saprolite
    assert resolved[5] == cover


@needs_gempy
def test_a_section_comes_back_as_a_rectangular_raster_of_units() -> None:
    model, cover, _saprolite, bedrock = _weathering_profile()
    section = SectionGeometry(
        start_m=(5.0, 0.0),
        end_m=(95.0, 0.0),
        min_z_m=-55.0,
        max_z_m=-2.0,
        samples_along=12,
        samples_vertical=9,
    )

    result = GeologyService().section(model, section)

    assert len(result.unit_ids) == 12 * 9
    assert result.distances_m[-1] == pytest.approx(90.0)
    # The bottom row is under both contacts everywhere; the top row is above the cover's
    # base only in the east, where that base is deepest.
    assert set(result.unit_ids[:12]) == {bedrock}
    assert cover in result.unit_ids[-12:]


@needs_gempy
def test_an_unfinished_model_is_refused_with_its_own_reasons() -> None:
    cover, bedrock = uuid4(), uuid4()
    model = GeologicalModel(
        name="Half built",
        extent=ModelExtent(min_x_m=0, max_x_m=100, min_y_m=-5, max_y_m=5, min_z_m=-60, max_z_m=0),
        units=(
            StratigraphicUnit(unit_id=cover, name="Cover", colour="#c9a227"),
            StratigraphicUnit(unit_id=bedrock, name="Bedrock", colour="#7d5a3c"),
        ),
        groups=(StructuralGroup(name="Regolith", unit_ids=(cover, bedrock)),),
    )
    section = SectionGeometry(start_m=(0.0, 0.0), end_m=(100.0, 0.0), min_z_m=-50.0, max_z_m=0.0)

    with pytest.raises(ValueError, match="orientation"):
        GeologyService().section(model, section)


@needs_gempy
def test_the_api_returns_a_section_for_a_model_that_was_never_saved() -> None:
    """The editor recomputes while a point is still being dragged."""
    from fastapi.testclient import TestClient

    from ofag.api.app import create_app
    from ofag.services.run_service import RunService

    model, cover, _saprolite, _bedrock = _weathering_profile()
    client = TestClient(create_app(RunService()))

    response = client.post(
        "/geology/section",
        json={
            "model": model.model_dump(mode="json"),
            "section": {
                "start_m": [5.0, 0.0],
                "end_m": [95.0, 0.0],
                "min_z_m": -55.0,
                "max_z_m": -2.0,
                "samples_along": 10,
                "samples_vertical": 8,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["unit_ids"]) == 80
    assert str(cover) in payload["unit_ids"]
    assert payload["undecided_cells"] == 0

    engine = client.get("/geology/engine")
    assert engine.status_code == 200
    assert engine.json() == {"engine": "gempy", "available": True}


def _hole(unit_a: UUID, unit_b: UUID, **overrides: object) -> Borehole:
    fields: dict[str, object] = {
        "name": "BH-1",
        "collar_x_m": 100.0,
        "collar_y_m": 200.0,
        "collar_z_m": 350.0,
        "total_depth_m": 60.0,
        "intervals": (
            BoreholeInterval(unit_id=unit_a, from_depth_m=0.0, to_depth_m=20.0),
            BoreholeInterval(unit_id=unit_b, from_depth_m=20.0, to_depth_m=55.0),
        ),
    }
    fields.update(overrides)
    return Borehole(**fields)


def test_a_vertical_hole_turns_depth_into_elevation_once() -> None:
    """The one place a depth becomes a z, so it happens once and is testable."""
    unit_a, unit_b = uuid4(), uuid4()
    hole = _hole(unit_a, unit_b)

    assert hole.position_at(0.0) == (100.0, 200.0, 350.0)
    assert hole.position_at(20.0) == (100.0, 200.0, 330.0)
    assert hole.position_at(60.0) == (100.0, 200.0, 290.0)


def test_a_surveyed_hole_moves_away_from_its_collar() -> None:
    """A deviated hole read as vertical puts every contact too shallow and too near the
    collar, and nothing downstream can tell."""
    unit_a, unit_b = uuid4(), uuid4()
    slanted = _hole(
        unit_a,
        unit_b,
        vertical=False,
        survey=(
            BoreholeSurveyStation(depth_m=0.0, inclination_degrees=30.0, azimuth_degrees=90.0),
            BoreholeSurveyStation(depth_m=60.0, inclination_degrees=30.0, azimuth_degrees=90.0),
        ),
    )

    east, north, elevation = slanted.position_at(20.0)
    # Thirty degrees off vertical, due east: ten metres across, 17.3 down.
    assert east == pytest.approx(110.0)
    assert north == pytest.approx(200.0)
    assert elevation == pytest.approx(350.0 - 20.0 * math.cos(math.radians(30.0)))
    # And the vertical reading of the same hole would have been 20 m down.
    assert elevation > _hole(unit_a, unit_b).position_at(20.0)[2]


def test_a_hole_with_a_survey_may_not_also_claim_to_be_vertical() -> None:
    unit_a, unit_b = uuid4(), uuid4()

    with pytest.raises(ValidationError, match="not declared vertical"):
        _hole(
            unit_a,
            unit_b,
            survey=(
                BoreholeSurveyStation(depth_m=0.0, inclination_degrees=10.0, azimuth_degrees=0.0),
            ),
        )


def test_overlapping_intervals_are_refused_because_a_depth_is_one_unit() -> None:
    unit_a, unit_b = uuid4(), uuid4()

    with pytest.raises(ValidationError, match="intervals overlap"):
        _hole(
            unit_a,
            unit_b,
            intervals=(
                BoreholeInterval(unit_id=unit_a, from_depth_m=0.0, to_depth_m=25.0),
                BoreholeInterval(unit_id=unit_b, from_depth_m=20.0, to_depth_m=55.0),
            ),
        )


def test_an_interval_deeper_than_the_hole_is_refused() -> None:
    unit_a, unit_b = uuid4(), uuid4()

    with pytest.raises(ValidationError, match="in a hole"):
        _hole(unit_a, unit_b, total_depth_m=30.0)


def test_the_bottom_of_the_deepest_interval_is_not_a_contact() -> None:
    """The hole ended there, which says nothing about where the unit does."""
    unit_a, unit_b = uuid4(), uuid4()

    contacts = _hole(unit_a, unit_b).contacts()

    assert [(unit, depth) for _, unit, depth in contacts] == [(unit_a, 0.0), (unit_b, 20.0)]


def test_logged_contacts_reach_the_interpolation_as_surface_points() -> None:
    """A unit constrained only by holes is constrained, not missing."""
    model, top, bottom, _ = _weathering_profile()
    with_holes = model.model_copy(
        update={
            "surface_points": (),
            "boreholes": (
                _hole(top, bottom),
                _hole(top, bottom, name="BH-2", collar_x_m=160.0),
            ),
        }
    )

    points = with_holes.borehole_points()
    assert len(points) == 4
    # Derived twice and identical, ids included: anything that references a logged
    # contact needs it to still be the same point next time.
    assert with_holes.borehole_points() == points
    assert with_holes.all_surface_points() == points
    assert {point.unit_id for point in points} == {top, bottom}
    # Two holes give the top unit two contacts, which is what readiness wants.
    assert not any("surface point" in issue for issue in with_holes.readiness())


@needs_gempy
def test_a_hole_is_placed_on_the_section_by_the_same_arithmetic() -> None:
    """Projected on the server, because depth becomes elevation in one place."""
    from ofag.services.geology_service import GeologyService

    model, top, bottom, _ = _weathering_profile()
    # A hole on the section line at x = 40, and one two hundred metres off it.
    on_line = Borehole(
        name="BH-on",
        collar_x_m=40.0,
        collar_y_m=0.0,
        collar_z_m=0.0,
        total_depth_m=40.0,
        intervals=(
            BoreholeInterval(unit_id=top, from_depth_m=0.0, to_depth_m=12.0),
            BoreholeInterval(unit_id=bottom, from_depth_m=12.0, to_depth_m=35.0),
        ),
    )
    off_line = on_line.model_copy(update={"name": "BH-off", "collar_y_m": 200.0})
    with_holes = model.model_copy(update={"boreholes": (on_line, off_line)})
    geometry = SectionGeometry(
        start_m=(0.0, 0.0),
        end_m=(100.0, 0.0),
        min_z_m=-60.0,
        max_z_m=0.0,
        samples_along=20,
        samples_vertical=12,
    )

    section = GeologyService().section(with_holes, geometry)

    placed = {hole.name: hole for hole in section.boreholes}
    assert placed["BH-on"].collar_distance_m == pytest.approx(40.0)
    assert placed["BH-on"].collar_offline_m == pytest.approx(0.0)
    # The section runs due east, so a hole 200 m north is 200 m off it — which is what
    # says whether this section may lean on it.
    assert placed["BH-off"].collar_offline_m == pytest.approx(200.0)

    # Contacts at 0 m and 12 m down a vertical hole from a collar at zero.
    assert placed["BH-on"].contact_elevation_m == pytest.approx((0.0, -12.0))
    assert placed["BH-on"].contact_unit_ids == (top, bottom)
    # The path is sampled rather than assumed straight, and ends at the bottom.
    assert placed["BH-on"].path_elevation_m[-1] == pytest.approx(-40.0)


@needs_gempy
def test_the_engine_conventions_hold() -> None:
    """The pre-flight GemPy never had, because it is not an inversion plugin."""
    from ofag.core.conventions import engine_fingerprint, forget, run_checks
    from ofag.engines.gempy import conventions

    forget()
    outcome = run_checks(
        "gempy.geology", engine_fingerprint("gempy", "numpy"), conventions.checks()
    )
    assert outcome.subject == "gempy.geology"
    assert outcome.passed, [result.detail for _, result in outcome.failures]
    assert {check.name for check, _ in outcome.results} == {
        "surface points are a unit's base",
        "dip azimuth is the direction of descent",
    }


@needs_gempy
def test_the_azimuth_check_is_not_blind_to_the_error_it_names() -> None:
    """A check that cannot fail is decoration."""
    from ofag.engines.gempy import conventions as gempy_conventions
    from ofag.engines.gempy.geology import evaluate_at

    def verdict(declared_azimuth: float) -> bool:
        model, cover = gempy_conventions._two_unit_model(
            gempy_conventions._DIP, declared_azimuth, along_strike_only=True
        )
        arm, contact = gempy_conventions._ARM, gempy_conventions._CONTACT_Z
        east, west = evaluate_at(
            model, np.array([[50.0 + arm, 50.0, contact], [50.0 - arm, 50.0, contact]])
        )
        return east == cover and west is not None and west != cover

    assert verdict(90.0), "descending east must read as descending east"
    assert not verdict(270.0), "the azimuth read backwards must fail the check"


@needs_gempy
def test_the_base_convention_check_is_not_blind() -> None:
    """Reverse what the engine returns and the base check must notice."""
    from ofag.engines.gempy import conventions as gempy_conventions

    check = gempy_conventions.surface_points_are_a_base()
    assert check.run().passed

    import ofag.engines.gempy.geology as geology

    real = geology.evaluate_at
    try:
        geology.evaluate_at = lambda model, points: list(reversed(real(model, points)))
        assert not check.run().passed
    finally:
        geology.evaluate_at = real


@needs_gempy
def test_a_model_is_not_interpolated_until_the_engine_is_checked() -> None:
    """The service asks, so no caller can interpolate past the pre-flight."""
    from ofag.services import geology_service

    model, _cover, _saprolite, _bedrock = _weathering_profile()
    assert GeologyService().readiness(model) == ()

    calls: list[str] = []

    def refuse() -> tuple[str, ...]:
        calls.append("asked")
        return ("gempy.geology failed the convention check 'probe': deliberately",)

    original = geology_service.GeologyService.convention_issues
    try:
        geology_service.GeologyService.convention_issues = staticmethod(refuse)
        issues = GeologyService().readiness(model)
        assert calls == ["asked"]
        assert any("failed the convention check" in issue for issue in issues)
        geometry = SectionGeometry(
            start_m=(0.0, 0.0), end_m=(100.0, 0.0), min_z_m=-50.0, max_z_m=0.0
        )
        with pytest.raises(ValueError, match="failed the convention check"):
            GeologyService().section(model, geometry)
    finally:
        # staticmethod(), not the bare function: reading a staticmethod off the class
        # hands back the plain function, and assigning that back makes it an ordinary
        # method that gets self.
        geology_service.GeologyService.convention_issues = staticmethod(original)


def _lithological_hole(granite: UUID, schist: UUID) -> dict[str, object]:
    """Granite, schist, granite: one rock type logged twice down one hole."""
    return {
        "name": "BH-litho",
        "collar_x_m": 0.0,
        "collar_y_m": 0.0,
        "collar_z_m": 300.0,
        "total_depth_m": 90.0,
        "intervals": (
            BoreholeInterval(unit_id=granite, from_depth_m=0.0, to_depth_m=30.0),
            BoreholeInterval(unit_id=schist, from_depth_m=30.0, to_depth_m=60.0),
            BoreholeInterval(unit_id=granite, from_depth_m=60.0, to_depth_m=90.0),
        ),
    }


def test_a_log_that_repeats_a_unit_is_refused_as_a_pile() -> None:
    """F071, reproduced: the same columns, and the tops mean something else."""
    granite, schist = uuid4(), uuid4()

    with pytest.raises(ValidationError, match="lithological log"):
        Borehole(**_lithological_hole(granite, schist), log_kind=LogKind.STRATIGRAPHIC)


def test_an_undeclared_log_that_repeats_a_unit_is_read_as_rock_types() -> None:
    """And a record saved before the field existed still loads."""
    granite, schist = uuid4(), uuid4()

    hole = Borehole(**_lithological_hole(granite, schist))

    assert hole.log_kind is LogKind.LITHOLOGICAL


def test_two_touching_intervals_of_one_unit_are_one_crossing() -> None:
    """The false positive the first version had."""
    sandstone, shale = uuid4(), uuid4()
    hole = Borehole(
        name="split",
        collar_x_m=0.0,
        collar_y_m=0.0,
        collar_z_m=300.0,
        total_depth_m=12.0,
        log_kind=LogKind.STRATIGRAPHIC,
        intervals=(
            BoreholeInterval(unit_id=sandstone, from_depth_m=0.0, to_depth_m=5.0, notes="fine"),
            BoreholeInterval(unit_id=sandstone, from_depth_m=5.0, to_depth_m=8.0, notes="coarse"),
            BoreholeInterval(unit_id=shale, from_depth_m=8.0, to_depth_m=12.0),
        ),
    )

    assert hole.log_kind is LogKind.STRATIGRAPHIC


def test_declared_lithological_the_same_log_is_accepted_and_contributes_nothing() -> None:
    """And the other half. The log is fine; reading its tops as surfaces is not."""
    granite, schist = uuid4(), uuid4()
    hole = Borehole(**_lithological_hole(granite, schist), log_kind=LogKind.LITHOLOGICAL)

    # The tops are still there -- they are real, they are where the rock changes.
    assert len(hole.contacts()) == 3

    model = GeologicalModel(
        name="repeat",
        extent=ModelExtent(
            min_x_m=-50.0, max_x_m=50.0, min_y_m=-50.0, max_y_m=50.0, min_z_m=200.0, max_z_m=300.0
        ),
        units=(
            StratigraphicUnit(unit_id=granite, name="Granite", colour="#b05a3c"),
            StratigraphicUnit(unit_id=schist, name="Schist", colour="#4c6b8a"),
        ),
        boreholes=(hole,),
    )

    # But none of them reaches the interpolation, and the model says so rather than
    # quietly being short of constraints.
    assert model.borehole_points() == ()
    assert any("logged lithologically" in issue for issue in model.readiness())
    assert any("BH-litho" in issue for issue in model.readiness())


def test_a_pile_still_contributes_its_tops() -> None:
    """The gate must not cost the stratigraphic case anything."""
    unit_a, unit_b = uuid4(), uuid4()
    hole = _hole(unit_a, unit_b)

    model = GeologicalModel(
        name="pile",
        extent=ModelExtent(
            min_x_m=0.0, max_x_m=200.0, min_y_m=100.0, max_y_m=300.0, min_z_m=200.0, max_z_m=400.0
        ),
        units=(
            StratigraphicUnit(unit_id=unit_a, name="Cover", colour="#c9a227"),
            StratigraphicUnit(unit_id=unit_b, name="Bedrock", colour="#7d5a3c"),
        ),
        boreholes=(hole,),
    )

    assert len(model.borehole_points()) == 2
    assert not any("lithologically" in issue for issue in model.readiness())
