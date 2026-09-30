"""The configuration form must make no difference to the run."""

from typing import Any

import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArrayInputSpec,
    CoordinateConvention,
    DataChannelSpec,
    DatasetSpec,
    GravityInversionSpec,
    GravityModelSpec,
    GravMagJointInversionSpec,
    JointGravityPropertySpec,
    JointMagneticsPropertySpec,
    MagneticsInversionSpec,
    MagneticsModelSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin
from ofag.plugins.simpeg_gravmag_joint import SimPEGGravMagJointPlugin
from ofag.plugins.simpeg_magnetics import SimPEGMagnetics3DPlugin

CONVENTION = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")

#: Plugin, the typed field it also accepts, and a configuration to put in both.
_DENSITY = ArrayInputSpec(
    path="absent.npy", quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
)
_SUSCEPTIBILITY = ArrayInputSpec(
    path="absent.npy", quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
)

CASES: tuple[tuple[Any, str, Any], ...] = (
    (
        SimPEGGravity3DPlugin(),
        "gravity_inversion",
        GravityInversionSpec(model=GravityModelSpec(initial_model=_DENSITY)),
    ),
    (
        SimPEGMagnetics3DPlugin(),
        "magnetics_inversion",
        MagneticsInversionSpec(model=MagneticsModelSpec(initial_model=_SUSCEPTIBILITY)),
    ),
    (
        SimPEGGravMagJointPlugin(),
        "gravmag_joint_inversion",
        GravMagJointInversionSpec(
            gravity=JointGravityPropertySpec(model=GravityModelSpec(initial_model=_DENSITY)),
            magnetics=JointMagneticsPropertySpec(
                model=MagneticsModelSpec(initial_model=_SUSCEPTIBILITY)
            ),
        ),
    ),
)


def _channel(channel_id: str, quantity: QuantityType, units: str) -> DataChannelSpec:
    return DataChannelSpec(
        channel_id=channel_id,
        dataset=DatasetSpec(
            name=channel_id,
            coordinate_convention=CONVENTION,
            physical_quantity=quantity,
            units=units,
        ),
        observations_path="absent.csv",
        data_uncertainty=QuantitySpec(value=1.0, quantity_type=quantity, unit=units),
    )


def _spec(plugin: Any, quantity: QuantityType, **configuration: Any) -> RunSpec:
    return RunSpec(
        schema_version="1.1" if "physics" in configuration else "1.0",
        plugin_id=plugin.plugin_id,
        plugin_version=plugin.plugin_version,
        engine="simpeg",
        dataset=DatasetSpec(
            name="equivalence",
            coordinate_convention=CONVENTION,
            physical_quantity=quantity,
            units="mGal" if quantity is QuantityType.GRAVITY_ACCELERATION else "nT",
        ),
        mesh=TensorMeshSpec(
            shape=(4, 4, 4),
            origin=(0.0, 0.0, -100.0),
            cell_size=QuantitySpec(value=25.0, quantity_type=QuantityType.LENGTH, unit="m"),
        ),
        # The joint method resolves two channels before it looks at anything else, so
        # without them its validation returns early and never reaches the paths this is
        # here to compare.
        datasets=(
            _channel("gravity", QuantityType.GRAVITY_ACCELERATION, "mGal"),
            _channel("tmi", QuantityType.MAGNETIC_ANOMALY, "nT"),
        ),
        **configuration,
    )


PARAMETRIZE = pytest.mark.parametrize(
    ("plugin", "field", "configuration"), CASES, ids=[case[1] for case in CASES]
)


@PARAMETRIZE
def test_both_forms_resolve_to_the_same_configuration(
    plugin: Any, field: str, configuration: Any
) -> None:
    quantity = (
        QuantityType.MAGNETIC_ANOMALY
        if field == "magnetics_inversion"
        else QuantityType.GRAVITY_ACCELERATION
    )
    payload = configuration.model_dump(mode="json")
    resolve = getattr(plugin, "_configuration", None) or plugin._declared_configuration

    from_physics = resolve(_spec(plugin, quantity, physics=payload))
    from_typed = resolve(_spec(plugin, quantity, **{field: configuration}))

    assert from_physics == from_typed == configuration


@PARAMETRIZE
def test_both_forms_validate_to_the_same_report(
    plugin: Any, field: str, configuration: Any, tmp_path
) -> None:
    """Including the field paths, which are what anything acting on a report uses."""
    quantity = (
        QuantityType.MAGNETIC_ANOMALY
        if field == "magnetics_inversion"
        else QuantityType.GRAVITY_ACCELERATION
    )
    context = PluginContext(tmp_path)
    payload = configuration.model_dump(mode="json")

    physics_report = plugin.validate(context, _spec(plugin, quantity, physics=payload))
    typed_report = plugin.validate(context, _spec(plugin, quantity, **{field: configuration}))

    assert physics_report.valid == typed_report.valid
    assert [issue.message for issue in physics_report.issues] == [
        issue.message for issue in typed_report.issues
    ]
    for physics_issue, typed_issue in zip(physics_report.issues, typed_report.issues, strict=True):
        assert physics_issue.field == typed_issue.field.replace(field, "physics", 1)
