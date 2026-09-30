"""The modelling step, on ground whose answer is known by construction."""

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.schemas import UnitRule, UnitRuleKind
from ofag.services.interpretation_service import (
    ContactPicks,
    CoverageConvention,
    InterpretationService,
    LayeredSection,
)

LAYER_TOPS = np.array([0.0, 20.0, 45.0, 80.0, 130.0, 220.0, 400.0, 900.0])


def _section(values: np.ndarray, spacing: float = 500.0) -> LayeredSection:
    """A four-by-four grid of stations, each carrying the same profile."""
    east, north = np.meshgrid(np.arange(4) * spacing, np.arange(4) * spacing)
    stations = east.size
    return LayeredSection(
        easting_m=east.ravel().astype(float),
        northing_m=north.ravel().astype(float),
        values=np.tile(values, (stations, 1)),
        layer_top_depth_m=LAYER_TOPS,
    )


def test_a_section_must_be_the_shape_it_claims() -> None:
    with pytest.raises(ValueError, match="expected"):
        LayeredSection(
            easting_m=np.zeros(3),
            northing_m=np.zeros(3),
            values=np.zeros((3, 5)),
            layer_top_depth_m=LAYER_TOPS,
        )


def test_layers_that_never_moved_are_not_counted_as_resolved() -> None:
    """The measurement that stops a prior being read as ground (F081)."""
    profile = np.array([200.0, 120.0, 30.0, 90.0, 50.0, 50.0, 50.0, 50.0])
    band = InterpretationService().resolved_band(_section(profile), np.asarray(50.0))

    assert band.deepest_m == pytest.approx(80.0)
    assert band.profile[:4].min() > 0.1
    assert band.profile[4:] == pytest.approx(0.0)
    assert "80 m" in band.describe()


def test_a_contact_is_picked_at_the_step_and_nowhere_else() -> None:
    service = InterpretationService()
    # Conductive down to 45 m, resistive below: the step is the 45 m boundary, so the
    # pick belongs between the layer centred above it and the one below.
    profile = np.array([80.0, 60.0, 8.0, 400.0, 420.0, 430.0, 440.0, 450.0])
    picks = service.pick_contact(_section(profile), (10.0, 200.0))

    assert picks.depth_m.size == 16
    assert picks.attempted == 16
    assert picks.depth_m.min() == picks.depth_m.max()
    assert 45.0 <= picks.depth_m[0] <= 80.0

    # A profile with no step that sharp contributes nothing, rather than contributing
    # the edge of the search window.
    flat = service.pick_contact(_section(np.full(LAYER_TOPS.size, 50.0)), (10.0, 200.0))
    assert flat.depth_m.size == 0
    assert flat.attempted == 16


def test_the_surface_fit_reports_the_estimator_that_lost_to_a_constant() -> None:
    """F027 as a test: a spatial estimator must be scored against no estimator."""
    rng = np.random.default_rng(11)
    locations = rng.uniform(0.0, 4_000.0, size=(40, 2))
    picks = ContactPicks(
        locations_m=locations,
        depth_m=70.0 + rng.normal(0.0, 20.0, size=40),
        attempted=40,
        band_m=(10.0, 200.0),
    )
    targets = np.column_stack([rng.uniform(0.0, 4_000.0, size=(50, 2)), np.zeros(50)])

    fitted = InterpretationService().fit_surface("cover base", picks, targets_m=targets)

    assert fitted.report.candidates["nearest"] > fitted.report.candidates["constant"]
    assert fitted.report.estimator != "nearest"
    assert fitted.report.pick_count == 40
    assert fitted.report.furthest_from_a_pick_m > 0.0
    # And it answers everywhere it was asked, which is what earns the guard's removal
    # only once the distance above is reported beside it.
    assert np.isfinite(fitted.predict(targets)).all()


def test_the_surface_fit_finds_a_trend_when_there_is_one() -> None:
    rng = np.random.default_rng(3)
    locations = rng.uniform(0.0, 4_000.0, size=(40, 2))
    depth = 40.0 + 0.02 * locations[:, 0] + rng.normal(0.0, 2.0, size=40)
    picks = ContactPicks(locations_m=locations, depth_m=depth, attempted=40, band_m=(0.0, 200.0))
    targets = np.column_stack([locations, np.zeros(40)])

    fitted = InterpretationService().fit_surface("dipping", picks, targets_m=targets)

    assert fitted.report.held_out_error < fitted.report.candidates["constant"] / 3


def _box(n: int = 6) -> dict:
    """A cube of cells, 100 m on a side, ground flat at zero elevation."""
    axis = np.linspace(50.0, 550.0, n)
    x, y, z = np.meshgrid(axis, axis, -axis, indexing="ij")
    centres = np.column_stack([x.ravel(), y.ravel(), z.ravel()])
    return {
        "cell_centres_m": centres,
        "cell_volume_m3": np.full(centres.shape[0], 1.0e6),
        "depth_below_ground_m": -centres[:, 2],
    }


def test_every_cell_gets_a_unit_and_says_what_decided_it() -> None:
    box = _box()
    rules = (
        UnitRule(
            name="bedrock",
            source="seismic",
            kind=UnitRuleKind.BELOW_SURFACE,
            surface="basement",
        ),
        UnitRule(name="cover", source="TEM", kind=UnitRuleKind.ABOVE_SURFACE, surface="cover"),
        UnitRule(name="fill", source="gravity", kind=UnitRuleKind.REMAINDER),
    )
    model = InterpretationService().assign_units(
        rules,
        surfaces={
            "basement": np.full(box["cell_centres_m"].shape[0], -400.0),
            "cover": np.full(box["cell_centres_m"].shape[0], 120.0),
        },
        **box,
    )

    assert model.report.undecided_cells == 0
    assert (model.unit >= 0).all()
    assert sum(unit.volume_share for unit in model.report.units) == pytest.approx(1.0)
    # The deepest cell is bedrock and the shallowest is cover, and each says so.
    deepest = int(np.argmin(box["cell_centres_m"][:, 2]))
    shallowest = int(np.argmax(box["cell_centres_m"][:, 2]))
    assert model.source[deepest] == "seismic"
    assert model.source[shallowest] == "TEM"


def test_the_hardest_evidence_is_not_overwritten_by_what_lies_over_it() -> None:
    """Order is precedence, and the cover must not relabel outcropping bedrock."""
    box = _box()
    count = box["cell_centres_m"].shape[0]
    surfaces = {"basement": np.zeros(count), "cover": np.full(count, 120.0)}
    rules = (
        UnitRule(
            name="bedrock", source="seismic", kind=UnitRuleKind.BELOW_SURFACE, surface="basement"
        ),
        UnitRule(name="cover", source="TEM", kind=UnitRuleKind.ABOVE_SURFACE, surface="cover"),
        UnitRule(name="fill", source="gravity", kind=UnitRuleKind.REMAINDER),
    )
    model = InterpretationService().assign_units(rules, surfaces=surfaces, **box)
    assert model.report.units[0].volume_share == pytest.approx(1.0)
    assert model.report.units[1].cell_count == 0


def test_a_rule_beyond_its_reach_reports_silence_rather_than_a_negative() -> None:
    """The 11 per cent this field was hiding (F085)."""
    box = _box()
    conductive = np.array([[1.0] * LAYER_TOPS.size])
    section = LayeredSection(
        easting_m=np.array([50.0]),
        northing_m=np.array([50.0]),
        values=conductive,
        layer_top_depth_m=LAYER_TOPS,
    )
    rules = (
        UnitRule(
            name="conductor",
            source="MT",
            kind=UnitRuleKind.PROPERTY_THRESHOLD,
            section="mt",
            threshold=5.0,
            reach_m=200.0,
        ),
        UnitRule(name="everything else", source="gravity", kind=UnitRuleKind.REMAINDER),
    )
    model = InterpretationService().assign_units(
        rules, surfaces={}, sections={"mt": section}, **box
    )

    conductor, remainder = model.report.units
    assert 0.0 < conductor.volume_share < 1.0
    assert conductor.beyond_reach_share > 0.5
    assert remainder.beyond_reach_share == 0.0
    # Where the rule did decide, the cell records how far the evidence was.
    decided = model.unit == 0
    assert np.isfinite(model.support_distance_m[decided]).all()
    assert model.support_distance_m[decided].max() <= 200.0
    assert not np.isfinite(model.support_distance_m[~decided]).any()


def test_a_rule_must_carry_what_its_kind_needs() -> None:
    with pytest.raises(ValidationError, match="needs a surface"):
        UnitRule(name="cover", source="TEM", kind=UnitRuleKind.ABOVE_SURFACE)
    with pytest.raises(ValidationError, match="needs a section and a threshold"):
        UnitRule(name="conductor", source="MT", kind=UnitRuleKind.PROPERTY_THRESHOLD)


def test_a_rule_naming_something_that_is_not_there_says_so() -> None:
    box = _box(3)
    service = InterpretationService()
    with pytest.raises(KeyError, match="unknown surface"):
        service.assign_units(
            (UnitRule(name="a", source="x", kind=UnitRuleKind.BELOW_SURFACE, surface="absent"),),
            surfaces={},
            **box,
        )
    with pytest.raises(KeyError, match="unknown section"):
        service.assign_units(
            (
                UnitRule(
                    name="a",
                    source="x",
                    kind=UnitRuleKind.PROPERTY_THRESHOLD,
                    section="absent",
                    threshold=1.0,
                ),
            ),
            surfaces={},
            **box,
        )


def test_a_section_resolves_to_where_its_sensitivity_per_area_runs_out() -> None:
    """Coverage has to be divided by cell size before it means anything."""
    # Chosen so the two effects are in the ratio a real section shows: the cell area
    # grows faster than the information decays, so raw coverage rises while density
    # falls through a tenth inside the section.
    depth = np.arange(2.5, 60.0, 5.0)
    size = (1.0 + depth) ** 4
    coverage = np.exp(-depth / 16.0) * size

    assert np.all(np.diff(coverage) > 0), "the fixture must have rising raw coverage"

    band = InterpretationService().resolved_band_from_sensitivity(
        depth,
        coverage,
        size,
        coverage_is=CoverageConvention.RAW,
        threshold=0.1,
        surface_m=10.0,
        step_m=5.0,
    )

    # exp(-d/16) falls to a tenth of its near-surface median at about 42 m.
    assert 30.0 <= band.deepest_m <= 55.0
    assert "sensitivity per unit area" in band.describe()
    assert band.profile[0] > band.profile[-1]


def test_reading_the_raw_coverage_instead_inverts_the_profile() -> None:
    """The mistake the method exists to prevent, asserted rather than described."""
    depth = np.arange(2.5, 60.0, 5.0)
    size = (1.0 + depth) ** 4
    coverage = np.exp(-depth / 16.0) * size

    service = InterpretationService()
    raw = CoverageConvention.RAW
    honest = service.resolved_band_from_sensitivity(depth, coverage, size, coverage_is=raw)
    naive = service.resolved_band_from_sensitivity(
        depth, coverage, np.ones_like(size), coverage_is=raw
    )

    assert np.all(np.diff(honest.profile) < 0), "sensitivity per unit area must decay"
    assert np.all(np.diff(naive.profile) > 0), "raw coverage rises, which is the trap"
    assert honest.deepest_m != naive.deepest_m


def _pygimli_ert_coverage() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A section stored the way this project's ERT runs store one."""
    depth = np.arange(1.25, 40.0, 2.5)
    size = (0.5 + depth) ** 2
    cov_trans = np.exp(-depth / 5.0) * size * 12.0
    stored = np.log10(cov_trans / size)
    return depth, stored, size


def test_a_logged_coverage_read_as_raw_is_refused() -> None:
    """The defect, reproduced, and the refusal that now meets it."""
    depth, stored, size = _pygimli_ert_coverage()
    assert np.any(stored < 0.0), "the fixture must be logged, which is what makes it negative"

    with pytest.raises(ValueError, match="logged array"):
        InterpretationService().resolved_band_from_sensitivity(
            depth, stored, size, coverage_is=CoverageConvention.RAW
        )


def test_the_same_coverage_declared_correctly_stops_well_above_the_mesh() -> None:
    """And the other half: declared for what it is, it answers."""
    depth, stored, size = _pygimli_ert_coverage()

    band = InterpretationService().resolved_band_from_sensitivity(
        depth, stored, size, coverage_is=CoverageConvention.LOG10_PER_AREA
    )

    assert band.deepest_m < 0.5 * float(depth.max())
    assert "log10_per_area" in band.evidence


def test_per_area_and_raw_disagree_on_the_same_array() -> None:
    """Three conventions, and the two linear ones are not interchangeable."""
    depth, stored, size = _pygimli_ert_coverage()
    linear = 10.0**stored
    service = InterpretationService()

    per_area = service.resolved_band_from_sensitivity(
        depth, linear, size, coverage_is=CoverageConvention.PER_AREA
    )
    as_raw = service.resolved_band_from_sensitivity(
        depth, linear, size, coverage_is=CoverageConvention.RAW
    )

    assert per_area.deepest_m != as_raw.deepest_m


def test_the_convention_has_to_be_stated() -> None:
    """No default, because every default here is wrong for some caller and silent for all of
    them."""
    depth, stored, size = _pygimli_ert_coverage()

    with pytest.raises(TypeError, match="coverage_is"):
        InterpretationService().resolved_band_from_sensitivity(depth, stored, size)  # type: ignore[call-arg]
