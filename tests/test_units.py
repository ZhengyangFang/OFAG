import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from ofag.core.constants import CANONICAL_UNITS, QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    GravityInversionSpec,
    GravityRegularizationKind,
    GravityRegularizationSpec,
    GravitySimulationSpec,
    GravityTilingSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
    TreeMeshSpec,
)
from ofag.core.units import (
    UnitValidationError,
    canonicalize_quantity,
    convert_from_engine_units,
    convert_to_engine_units,
    validate_unit_dimension,
)


def test_length_and_time_canonicalization() -> None:
    assert canonicalize_quantity(1.0, "ft", QuantityType.LENGTH) == pytest.approx(0.3048)
    assert canonicalize_quantity(2.0, "km", QuantityType.LENGTH) == pytest.approx(2000.0)
    assert canonicalize_quantity(500.0, "ms", QuantityType.TIME) == pytest.approx(0.5)
    assert canonicalize_quantity(10.0, "us", QuantityType.TIME) == pytest.approx(1e-5)


def test_geophysical_units_and_simpeg_round_trip() -> None:
    density = canonicalize_quantity(1.0, "g / cm^3", QuantityType.DENSITY_CONTRAST)
    gravity = canonicalize_quantity(1.0, "mGal", QuantityType.GRAVITY_ACCELERATION)
    magnetic = canonicalize_quantity(1.0, "nT", QuantityType.MAGNETIC_ANOMALY)
    assert density == pytest.approx(1.0)
    assert gravity == pytest.approx(1.0)
    assert magnetic == pytest.approx(1.0)
    assert canonicalize_quantity(180.0, "degree", QuantityType.ANGLE) == pytest.approx(math.pi)
    engine_value = convert_to_engine_units(2.0, QuantityType.GRAVITY_ACCELERATION, "simpeg")
    assert engine_value == pytest.approx(2.0)
    restored = convert_from_engine_units(engine_value, QuantityType.GRAVITY_ACCELERATION, "simpeg")
    assert restored == pytest.approx(2.0)


def test_every_quantity_type_declares_a_usable_canonical_unit() -> None:
    """A new QuantityType is unusable until CANONICAL_UNITS knows its unit."""
    missing = [item.value for item in QuantityType if item not in CANONICAL_UNITS]
    assert not missing, f"QuantityType members without a canonical unit: {missing}"
    for quantity_type, unit in CANONICAL_UNITS.items():
        validate_unit_dimension(unit, quantity_type)


def test_resistivity_and_conductivity_are_not_interchangeable() -> None:
    """They are reciprocals, so converting one into the other must be explicit."""
    assert canonicalize_quantity(1.0, "ohm * m", QuantityType.RESISTIVITY) == pytest.approx(1.0)
    with pytest.raises(UnitValidationError, match="invalid for resistivity"):
        canonicalize_quantity(1.0, "S/m", QuantityType.RESISTIVITY)
    with pytest.raises(UnitValidationError, match="invalid for conductivity"):
        canonicalize_quantity(1.0, "ohm * m", QuantityType.CONDUCTIVITY)


def test_seismic_density_is_separate_from_potential_field_density_contrast() -> None:
    """kg/m^3 bulk density must never be silently read as g/cm^3 density contrast."""
    bulk = canonicalize_quantity(2500.0, "kg/m^3", QuantityType.BULK_DENSITY)
    assert bulk == pytest.approx(2500.0)
    # Both are densities dimensionally, so only the canonical unit separates them.
    assert (
        CANONICAL_UNITS[QuantityType.BULK_DENSITY] != CANONICAL_UNITS[QuantityType.DENSITY_CONTRAST]
    )
    assert canonicalize_quantity(2.5, "g/cm^3", QuantityType.BULK_DENSITY) == pytest.approx(2500.0)


def test_bad_dimension_is_rejected() -> None:
    with pytest.raises(UnitValidationError, match="invalid for length"):
        canonicalize_quantity(1.0, "second", QuantityType.LENGTH)
    with pytest.raises(ValidationError):
        QuantitySpec(value=1.0, quantity_type=QuantityType.LENGTH, unit="second")


def test_nonuniform_tensor_mesh_widths_are_explicit_and_match_shape() -> None:
    width = QuantitySpec(value=[5.0, 6.5], quantity_type=QuantityType.LENGTH, unit="m")
    mesh = TensorMeshSpec(
        cell_size=QuantitySpec(value=[5.0, 5.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"),
        shape=(2, 2, 2),
        origin=(0.0, 0.0, -10.0),
        cell_widths=(width, width, width),
    )
    assert mesh.cell_widths is not None
    with pytest.raises(ValidationError, match="exactly 2 values"):
        TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[5.0, 5.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(0.0, 0.0, -10.0),
            cell_widths=(
                QuantitySpec(value=[5.0], quantity_type=QuantityType.LENGTH, unit="m"),
                width,
                width,
            ),
        )


def _length(value: float | list[float]) -> QuantitySpec:
    return QuantitySpec(value=value, quantity_type=QuantityType.LENGTH, unit="m")


def test_a_two_dimensional_tensor_mesh_is_an_easting_elevation_section() -> None:
    """2.5D resistivity works in x-z with Northing as the invariant strike axis."""
    mesh = TensorMeshSpec(
        cell_size=_length([5.0, 2.0]),
        shape=(40, 20),
        origin=(-100.0, -40.0),
    )

    assert mesh.dimension == 2
    assert (
        TensorMeshSpec(
            cell_size=_length([5.0, 5.0, 2.0]), shape=(4, 4, 2), origin=(0.0, 0.0, -10.0)
        ).dimension
        == 3
    )


def test_mesh_axes_must_agree_on_dimension() -> None:
    with pytest.raises(ValidationError, match="origin must have 2 components"):
        TensorMeshSpec(cell_size=_length([5.0, 2.0]), shape=(4, 2), origin=(0.0, 0.0, -10.0))
    with pytest.raises(ValidationError, match="cell_size must have 2 components"):
        TensorMeshSpec(cell_size=_length([5.0, 5.0, 2.0]), shape=(4, 2), origin=(0.0, -10.0))
    with pytest.raises(ValidationError, match="cell_widths must have 2 axes"):
        TensorMeshSpec(
            cell_size=_length([5.0, 2.0]),
            shape=(2, 2),
            origin=(0.0, -10.0),
            cell_widths=(_length([5.0, 5.0]), _length([2.0, 2.0]), _length([2.0, 2.0])),
        )


def test_volume_methods_reject_a_two_dimensional_mesh(tmp_path: Path) -> None:
    """Gravity has no meaning without a Northing extent, so it must say so."""
    from ofag.plugins.protocol import PluginContext
    from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin

    spec = RunSpec(
        plugin_id="simpeg.pf.gravity3d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="section",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        mesh=TensorMeshSpec(cell_size=_length([5.0, 2.0]), shape=(4, 2), origin=(0.0, -10.0)),
    )

    report = SimPEGGravity3DPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    assert any(
        issue.field == "mesh.shape" and "3D mesh" in issue.message for issue in report.issues
    )


def test_sparse_gravity_configuration_requires_irls_directive() -> None:
    with pytest.raises(ValidationError, match="requires directives.irls.enabled=true"):
        GravityInversionSpec(
            regularization=GravityRegularizationSpec(kind=GravityRegularizationKind.SPARSE_IRLS)
        )


def test_tiled_gravity_configuration_requires_a_treemesh() -> None:
    with pytest.raises(ValidationError, match="requires a TreeMeshSpec"):
        RunSpec(
            plugin_id="simpeg.pf.gravity3d",
            dataset={
                "name": "gravity",
                "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
                "physical_quantity": "gravity_acceleration",
                "units": "m/s^2",
            },
            mesh=TensorMeshSpec(
                cell_size=QuantitySpec(
                    value=[1.0, 1.0, 1.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                shape=(1, 1, 1),
                origin=(0.0, 0.0, 0.0),
            ),
            gravity_inversion=GravityInversionSpec(
                simulation=GravitySimulationSpec(
                    tiling=GravityTilingSpec(enabled=True, tile_count=2)
                )
            ),
        )

    tree = TreeMeshSpec(
        cell_size=QuantitySpec(value=[1.0, 1.0, 1.0], quantity_type=QuantityType.LENGTH, unit="m"),
        padding_distance=tuple(
            QuantitySpec(value=[1.0, 1.0], quantity_type=QuantityType.LENGTH, unit="m")
            for _ in range(3)
        ),
        depth_core=QuantitySpec(value=1.0, quantity_type=QuantityType.LENGTH, unit="m"),
    )
    assert tree.diagonal_balance
