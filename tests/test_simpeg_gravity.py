from uuid import uuid4

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArrayInputSpec,
    CoordinateConvention,
    DatasetSpec,
    GravityInversionSpec,
    GravityModelSpec,
    GravityOptimizerKind,
    GravityOptimizerSpec,
    GravityRegularizationSpec,
    GravitySimulationSpec,
    GravityTilingSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
    TreeMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin


@pytest.mark.parametrize(
    ("optimizer_kind", "simulation_engine"),
    [
        (GravityOptimizerKind.INEXACT_GAUSS_NEWTON, "geoana"),
        (GravityOptimizerKind.PROJECTED_GNCG, "choclo"),
    ],
)
def test_simpeg_gravity_adapter_runs_with_project_units(
    tmp_path, optimizer_kind: GravityOptimizerKind, simulation_engine: str
) -> None:
    pytest.importorskip("simpeg")
    observations = tmp_path / "observations.csv"
    payload = (
        "x_m,y_m,z_m,gravity_m_s2\n"
        "-10.0,-10.0,5.0,1.1e-7\n"
        "10.0,-10.0,5.0,1.5e-7\n"
        "-10.0,10.0,5.0,1.3e-7\n"
        "10.0,10.0,5.0,1.7e-7\n"
    )
    observations.write_text(payload, encoding="utf-8")
    initial_path = tmp_path / "initial_density.npy"
    reference_path = tmp_path / "reference_density.npy"
    weights_path = tmp_path / "cell_weights.npy"
    np.save(initial_path, np.linspace(-10.0, 10.0, 8))
    np.save(reference_path, np.zeros(8))
    np.save(weights_path, np.ones(8))

    def density_input(path) -> ArrayInputSpec:
        return ArrayInputSpec(
            path=str(path),
            quantity_type=QuantityType.DENSITY_CONTRAST,
            unit="kg/m^3",
        )

    weight_input = ArrayInputSpec(
        path=str(weights_path),
        quantity_type=QuantityType.DIMENSIONLESS,
        unit="dimensionless",
    )
    spec = RunSpec(
        plugin_id="simpeg.pf.gravity3d",
        plugin_version="0.1.0",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-si-gravity",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="m/s^2",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        gravity_inversion=GravityInversionSpec(
            simulation=GravitySimulationSpec(engine=simulation_engine),
            model=GravityModelSpec(
                initial_model=density_input(initial_path),
                reference_model=density_input(reference_path),
            ),
            regularization=GravityRegularizationSpec(cell_weights={"user": weight_input}),
            optimizer=GravityOptimizerSpec(
                kind=optimizer_kind,
                max_iterations=1,
                cg_max_iterations=8,
            ),
        ),
        parameters={
            "observations_path": str(observations),
            "initial_density_contrast": QuantitySpec(
                value=0.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="kg/m^3"
            ),
            "data_uncertainty": QuantitySpec(
                value=1e-8,
                quantity_type=QuantityType.GRAVITY_ACCELERATION,
                unit="m/s^2",
            ),
            "max_iterations": 1,
        },
    )
    plugin = SimPEGGravity3DPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["engine"] == "simpeg"
    assert result.summary["solver"] == "least_squares_gravity3d"
    assert result.summary["data_unit"] == "mGal"
    assert len(result.artifacts) == 11
    assert {item.units for item in result.artifacts} == {"dimensionless", "g/cm^3", "mGal"}
    assert {item.artifact_type for item in result.artifacts} >= {
        "iteration_metrics",
        "residual_data",
        "normalized_residual",
        "observation_map",
        "prediction_map",
        "residual_map",
        "model_slice",
    }


def test_simpeg_gravity_adapter_builds_and_runs_a_treemesh(tmp_path) -> None:
    pytest.importorskip("simpeg")
    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,gravity_m_s2\n"
        "-20.0,-20.0,10.0,1.1e-7\n"
        "20.0,-20.0,10.0,1.5e-7\n"
        "-20.0,20.0,10.0,1.3e-7\n"
        "20.0,20.0,10.0,1.7e-7\n",
        encoding="utf-8",
    )
    topography = tmp_path / "topography.csv"
    topography.write_text(
        "x_m,y_m,z_m\n-40.0,-40.0,0.0\n40.0,-40.0,0.0\n-40.0,40.0,0.0\n40.0,40.0,0.0\n",
        encoding="utf-8",
    )
    length_vector = QuantitySpec(
        value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
    )
    padding = QuantitySpec(value=[40.0, 40.0], quantity_type=QuantityType.LENGTH, unit="m")
    spec = RunSpec(
        plugin_id="simpeg.pf.gravity3d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-tree-si-gravity",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="m/s^2",
        ),
        mesh=TreeMeshSpec(
            cell_size=length_vector,
            padding_distance=(padding, padding, padding),
            depth_core=QuantitySpec(value=40.0, quantity_type=QuantityType.LENGTH, unit="m"),
        ),
        gravity_inversion=GravityInversionSpec(
            optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=8)
        ),
        parameters={
            "observations_path": str(observations),
            "topography_path": str(topography),
            "data_uncertainty": QuantitySpec(
                value=1e-8,
                quantity_type=QuantityType.GRAVITY_ACCELERATION,
                unit="m/s^2",
            ),
        },
    )
    plugin = SimPEGGravity3DPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["mesh_cells"] > result.summary["model_cells"] > 0
    assert result.summary["observation_count"] == 4
    assert result.summary["mesh_kind"] == "TreeMesh"
    assert any(item.artifact_type == "mesh_geometry" for item in result.artifacts)

    tiled_spec = spec.model_copy(
        update={
            "run_id": uuid4(),
            "gravity_inversion": GravityInversionSpec(
                simulation=GravitySimulationSpec(
                    tiling=GravityTilingSpec(enabled=True, tile_count=2, sensitivity_storage="disk")
                ),
                optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=8),
            ),
        }
    )
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), tiled_spec).valid
    tiled_result = plugin.execute(PluginContext(tmp_path / "artifacts"), tiled_spec)
    assert tiled_result.summary["tile_count"] == 2
    assert any(item.artifact_type == "tiling_manifest" for item in tiled_result.artifacts)
    assert (
        tmp_path
        / "artifacts"
        / str(tiled_spec.run_id)
        / "sensitivities"
        / "tile_0"
        / "sensitivity.npy"
    ).is_file()


def _restartable_spec(tmp_path) -> RunSpec:
    """The smallest gravity inversion that really iterates, for restart tests."""
    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,gravity_m_s2\n"
        "-10.0,-10.0,5.0,1.1e-7\n"
        "10.0,-10.0,5.0,1.5e-7\n"
        "-10.0,10.0,5.0,1.3e-7\n"
        "10.0,10.0,5.0,1.7e-7\n",
        encoding="utf-8",
    )
    return RunSpec(
        plugin_id="simpeg.pf.gravity3d",
        plugin_version="0.1.0",
        engine="simpeg",
        dataset=DatasetSpec(
            name="restartable-gravity",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="m/s^2",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        gravity_inversion=GravityInversionSpec(
            optimizer=GravityOptimizerSpec(max_iterations=2, cg_max_iterations=4),
        ),
        parameters={
            "observations_path": str(observations),
            "initial_density_contrast": QuantitySpec(
                value=0.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="kg/m^3"
            ),
            "data_uncertainty": QuantitySpec(
                value=1e-8, quantity_type=QuantityType.GRAVITY_ACCELERATION, unit="m/s^2"
            ),
            "max_iterations": 2,
        },
    )


def test_a_gravity_inversion_saves_its_model_and_continues_from_it(tmp_path) -> None:
    """Restart proved on a real solver, not only on a fixture."""
    pytest.importorskip("simpeg")
    spec = _restartable_spec(tmp_path)
    context = PluginContext(tmp_path / "artifacts")
    plugin = SimPEGGravity3DPlugin()

    first = plugin.execute(context, spec)
    assert first.summary["resumed"] is False

    checkpoint = context.resume_from(spec)
    assert checkpoint is not None, "the inversion saved nothing to continue from"
    assert checkpoint.plugin_id == plugin.plugin_id
    saved = checkpoint.state["model_path"]
    assert isinstance(saved, str)
    assert np.load(saved, allow_pickle=False).size == int(first.summary["model_cells"])

    second = plugin.execute(context, spec)

    assert second.summary["resumed"] is True
    assert second.summary["resumed_from_iteration"] == checkpoint.iteration


def test_a_checkpoint_from_a_different_mesh_is_not_used_as_a_starting_model(tmp_path) -> None:
    """Padding a mismatched model to fit would invent values nobody chose."""
    pytest.importorskip("simpeg")
    spec = _restartable_spec(tmp_path)
    context = PluginContext(tmp_path / "artifacts")
    plugin = SimPEGGravity3DPlugin()
    wrong = context.run_dir(spec.run_id) / "checkpoint_model.npy"
    np.save(wrong, np.zeros(3))
    context.checkpoint(
        spec,
        {"model_path": str(wrong)},
        plugin_id=plugin.plugin_id,
        plugin_version=plugin.plugin_version,
        iteration=9,
    )

    result = plugin.execute(context, spec)

    assert result.summary["resumed"] is False
