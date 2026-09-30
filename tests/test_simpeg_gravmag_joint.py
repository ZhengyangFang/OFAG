import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    CrossGradientCouplingSpec,
    DataChannelSpec,
    DatasetSpec,
    GravityOptimizerSpec,
    GravMagJointInversionSpec,
    JointGravityPropertySpec,
    JointMagneticsPropertySpec,
    MagneticsInducingFieldSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
    TreeMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravmag_joint import SimPEGGravMagJointPlugin
from tests.conftest import progress_events


def test_simpeg_joint_gravity_tmi_cross_gradient_runs_with_project_units(tmp_path) -> None:
    pytest.importorskip("simpeg")
    gravity_observations = tmp_path / "gravity.csv"
    gravity_observations.write_text(
        "x_m,y_m,z_m,gravity_m_s2\n"
        "-10.0,-10.0,5.0,1.1e-7\n"
        "10.0,-10.0,5.0,1.5e-7\n"
        "-10.0,10.0,5.0,1.3e-7\n"
        "10.0,10.0,5.0,1.7e-7\n",
        encoding="utf-8",
    )
    magnetic_observations = tmp_path / "magnetics.csv"
    magnetic_observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        "-10.0,-10.0,5.0,2.0\n"
        "10.0,-10.0,5.0,2.5\n"
        "-10.0,10.0,5.0,1.8\n"
        "10.0,10.0,5.0,2.2\n",
        encoding="utf-8",
    )
    density_path = tmp_path / "initial_density.npy"
    susceptibility_path = tmp_path / "initial_susceptibility.npy"
    np.save(density_path, np.array([-20.0, -5.0, 15.0, 30.0, -10.0, 5.0, 20.0, 35.0]))
    np.save(
        susceptibility_path,
        np.array([0.001, 0.004, 0.002, 0.005, 0.003, 0.006, 0.004, 0.007]),
    )
    coordinate_convention = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")
    gravity_dataset = DatasetSpec(
        name="joint-gravity",
        coordinate_convention=coordinate_convention,
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="m/s^2",
    )
    magnetic_dataset = DatasetSpec(
        name="joint-tmi",
        coordinate_convention=coordinate_convention,
        physical_quantity=QuantityType.MAGNETIC_ANOMALY,
        units="nT",
    )
    spec = RunSpec(
        plugin_id="simpeg.joint.gravmag.cross_gradient",
        engine="simpeg",
        dataset=gravity_dataset,
        datasets=(
            DataChannelSpec(
                channel_id="gravity",
                dataset=gravity_dataset,
                observations_path=str(gravity_observations),
                data_uncertainty=QuantitySpec(
                    value=1e-8,
                    quantity_type=QuantityType.GRAVITY_ACCELERATION,
                    unit="m/s^2",
                ),
            ),
            DataChannelSpec(
                channel_id="tmi",
                dataset=magnetic_dataset,
                observations_path=str(magnetic_observations),
                data_uncertainty=QuantitySpec(
                    value=0.1,
                    quantity_type=QuantityType.MAGNETIC_ANOMALY,
                    unit="nT",
                ),
            ),
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        gravmag_joint_inversion=GravMagJointInversionSpec(
            gravity=JointGravityPropertySpec(
                model={
                    "initial_model": {
                        "path": str(density_path),
                        "quantity_type": "density_contrast",
                        "unit": "kg/m^3",
                    }
                }
            ),
            magnetics=JointMagneticsPropertySpec(
                inducing_field=MagneticsInducingFieldSpec(
                    inclination=QuantitySpec(
                        value=60.0, quantity_type=QuantityType.ANGLE, unit="degree"
                    ),
                    declination=QuantitySpec(
                        value=15.0, quantity_type=QuantityType.ANGLE, unit="degree"
                    ),
                ),
                model={
                    "initial_model": {
                        "path": str(susceptibility_path),
                        "quantity_type": "susceptibility",
                        "unit": "dimensionless",
                    }
                },
            ),
            coupling=CrossGradientCouplingSpec(
                weight=0.5,
                density_scale=QuantitySpec(
                    value=100.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="kg/m^3"
                ),
                susceptibility_scale=QuantitySpec(
                    value=0.01, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
                ),
                normalize_models=False,
            ),
            optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=16),
            directive_strategy="simpeg_cross_gradient_tutorial",
            beta={"cooling_factor": 5.0},
        ),
    )
    plugin = SimPEGGravMagJointPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["solver"] == "joint_gravity_magnetics_cross_gradient"
    assert result.summary["gravity_data_unit"] == "mGal"
    assert result.summary["magnetics_data_unit"] == "nT"
    assert result.summary["phi_cross_gradient"] >= 0
    assert {item.artifact_type for item in result.artifacts} >= {
        "recovered_density",
        "recovered_susceptibility",
        "cross_gradient_magnitude",
        "objective_components",
    }
    cross_gradient = np.load(
        tmp_path / "artifacts" / str(spec.run_id) / "cross_gradient_magnitude_1_m2.npy"
    )
    assert np.isfinite(cross_gradient).all()


def test_joint_gravity_tmi_rejects_sparse_irls() -> None:
    with pytest.raises(ValueError, match="currently supports l2"):
        GravMagJointInversionSpec.model_validate(
            {"gravity": {"regularization": {"kind": "sparse_irls"}}}
        )


def _gravity_channel(channel_id: str, path: str) -> DataChannelSpec:
    return DataChannelSpec(
        channel_id=channel_id,
        dataset=DatasetSpec(
            name=channel_id,
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        observations_path=path,
        data_uncertainty=QuantitySpec(
            value=1.0, quantity_type=QuantityType.GRAVITY_ACCELERATION, unit="mGal"
        ),
    )


def test_joint_reports_a_missing_channel_reference_as_a_validation_issue(tmp_path) -> None:
    """A dangling channel_id must name itself, not fail somewhere in the solver."""
    channel = _gravity_channel("gravity", "gravity.csv")
    spec = RunSpec(
        plugin_id="simpeg.joint.gravmag.cross_gradient",
        engine="simpeg",
        dataset=channel.dataset,
        datasets=(channel,),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        gravmag_joint_inversion=GravMagJointInversionSpec(),
    )

    report = SimPEGGravMagJointPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    issue = next(item for item in report.issues if "tmi" in item.message)
    assert issue.field == "gravmag_joint_inversion.magnetics_channel"
    assert "available: gravity" in issue.message


def test_joint_rejects_a_channel_carrying_the_wrong_quantity(tmp_path) -> None:
    spec = RunSpec(
        plugin_id="simpeg.joint.gravmag.cross_gradient",
        engine="simpeg",
        dataset=_gravity_channel("gravity", "gravity.csv").dataset,
        # Both channels are gravity; the magnetics reference resolves but is wrong.
        datasets=(
            _gravity_channel("gravity", "gravity.csv"),
            _gravity_channel("tmi", "also_gravity.csv"),
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        gravmag_joint_inversion=GravMagJointInversionSpec(),
    )

    report = SimPEGGravMagJointPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    assert any(item.field == "datasets.tmi.dataset.physical_quantity" for item in report.issues)


def test_a_data_channel_rejects_uncertainty_from_another_quantity() -> None:
    """The unit policy applies per channel, not once per run."""
    with pytest.raises(ValidationError, match="magnetic_anomaly uncertainty"):
        DataChannelSpec(
            channel_id="gravity",
            dataset=DatasetSpec(
                name="gravity",
                coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
                physical_quantity=QuantityType.GRAVITY_ACCELERATION,
                units="mGal",
            ),
            observations_path="gravity.csv",
            data_uncertainty=QuantitySpec(
                value=1.0, quantity_type=QuantityType.MAGNETIC_ANOMALY, unit="nT"
            ),
        )


def test_duplicate_channel_ids_are_rejected() -> None:
    """Channels are addressed by id, so a repeated id makes one unreachable."""
    channel = _gravity_channel("gravity", "gravity.csv")
    with pytest.raises(ValidationError, match="must be unique"):
        RunSpec(
            plugin_id="simpeg.pf.gravity3d",
            dataset=channel.dataset,
            datasets=(channel, channel),
        )


def test_simpeg_joint_gravity_tmi_runs_on_a_treemesh(tmp_path) -> None:
    pytest.importorskip("simpeg")
    gravity_observations = tmp_path / "gravity.csv"
    gravity_observations.write_text(
        "x_m,y_m,z_m,gravity_m_s2\n"
        "-20.0,-20.0,10.0,1.1e-7\n"
        "20.0,-20.0,10.0,1.5e-7\n"
        "-20.0,20.0,10.0,1.3e-7\n"
        "20.0,20.0,10.0,1.7e-7\n",
        encoding="utf-8",
    )
    magnetic_observations = tmp_path / "magnetics.csv"
    magnetic_observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        "-20.0,-20.0,10.0,2.0\n"
        "20.0,-20.0,10.0,2.4\n"
        "-20.0,20.0,10.0,1.7\n"
        "20.0,20.0,10.0,2.1\n",
        encoding="utf-8",
    )
    coordinates = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")
    gravity_dataset = DatasetSpec(
        name="tree-gravity",
        coordinate_convention=coordinates,
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="m/s^2",
    )
    magnetic_dataset = DatasetSpec(
        name="tree-tmi",
        coordinate_convention=coordinates,
        physical_quantity=QuantityType.MAGNETIC_ANOMALY,
        units="nT",
    )
    cell_size = QuantitySpec(value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m")
    padding = QuantitySpec(value=[40.0, 40.0], quantity_type=QuantityType.LENGTH, unit="m")
    spec = RunSpec(
        plugin_id="simpeg.joint.gravmag.cross_gradient",
        engine="simpeg",
        dataset=gravity_dataset,
        datasets=(
            DataChannelSpec(
                channel_id="gravity",
                dataset=gravity_dataset,
                observations_path=str(gravity_observations),
                data_uncertainty=QuantitySpec(
                    value=1e-8,
                    quantity_type=QuantityType.GRAVITY_ACCELERATION,
                    unit="m/s^2",
                ),
            ),
            DataChannelSpec(
                channel_id="tmi",
                dataset=magnetic_dataset,
                observations_path=str(magnetic_observations),
                data_uncertainty=QuantitySpec(
                    value=0.1,
                    quantity_type=QuantityType.MAGNETIC_ANOMALY,
                    unit="nT",
                ),
            ),
        ),
        mesh=TreeMeshSpec(
            cell_size=cell_size,
            padding_distance=(padding, padding, padding),
            depth_core=QuantitySpec(value=40.0, quantity_type=QuantityType.LENGTH, unit="m"),
        ),
        gravmag_joint_inversion=GravMagJointInversionSpec(
            optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=16),
        ),
    )
    result = SimPEGGravMagJointPlugin().execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["mesh_kind"] == "TreeMesh"
    assert result.summary["mesh_cells"] == result.summary["model_cells"] > 0
    assert any(item.artifact_type == "mesh_geometry" for item in result.artifacts)

    # The joint plugin reported iterations through the sink that the executor used to
    # replace with a no-op, so the workbench showed none at all.
    events = progress_events(tmp_path / "artifacts" / str(spec.run_id))
    assert [event for event in events if event["event_type"] == "iteration"]
