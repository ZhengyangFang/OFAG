from uuid import uuid4

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArrayInputSpec,
    CoordinateConvention,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    TDEM3DForwardSpec,
    TDEM3DModelSpec,
    TDEMSystemSpec,
    TDEMTimeGateSpec,
    TDEMTimeStepSpec,
    TensorMeshSpec,
    TreeMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_tdem3d_forward import SimPEGTDEM3DForwardPlugin


def test_simpeg_tdem3d_forward_runs_on_tensor_and_tree_meshes(tmp_path) -> None:
    pytest.importorskip("simpeg")
    spec = RunSpec(
        plugin_id="simpeg.aem.tdem3d_forward",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-3d-tdem-forward",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
            units="T",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[5.0, 5.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(8, 8, 12),
            origin=(-20.0, -20.0, -40.0),
        ),
        tdem3d_forward=TDEM3DForwardSpec(
            system=TDEMSystemSpec(
                times=QuantitySpec(value=[1e-5, 3e-5], quantity_type=QuantityType.TIME, unit="s"),
                source_location=QuantitySpec(
                    value=[0.0, 0.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                receiver_location=QuantitySpec(
                    value=[1.0, 0.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                source_radius=QuantitySpec(value=5.0, quantity_type=QuantityType.LENGTH, unit="m"),
                source_current=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.ELECTRIC_CURRENT, unit="A"
                ),
            ),
            model=TDEM3DModelSpec(
                conductivity=QuantitySpec(
                    value=0.05, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                )
            ),
            time_steps=(
                TDEMTimeStepSpec(
                    step=QuantitySpec(value=1e-6, quantity_type=QuantityType.TIME, unit="s"),
                    count=10,
                ),
                TDEMTimeStepSpec(
                    step=QuantitySpec(value=5e-6, quantity_type=QuantityType.TIME, unit="s"),
                    count=10,
                ),
                TDEMTimeStepSpec(
                    step=QuantitySpec(value=2e-5, quantity_type=QuantityType.TIME, unit="s"),
                    count=10,
                ),
            ),
        ),
    )
    plugin = SimPEGTDEM3DForwardPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid
    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)
    assert result.summary["solver"] == "tdem3d_forward"
    assert result.summary["model_cells"] > 0
    assert {artifact.artifact_type for artifact in result.artifacts} == {
        "predicted_data",
        "mesh_geometry",
        "survey_definition",
    }
    tensor_prediction = (
        tmp_path
        / "artifacts"
        / next(
            artifact.relative_path
            for artifact in result.artifacts
            if artifact.artifact_type == "predicted_data"
        )
    )
    assert np.isfinite(np.load(tensor_prediction, allow_pickle=False)).all()

    topography = tmp_path / "topography.csv"
    topography.write_text("x_m,y_m,z_m\n-20,-20,0\n20,-20,0\n-20,20,0\n20,20,0\n", encoding="utf-8")
    padding = QuantitySpec(value=[20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m")
    source_locations = tmp_path / "source_locations.npy"
    receiver_locations = tmp_path / "receiver_locations.npy"
    np.save(source_locations, np.array([[-5.0, 0.0, 5.0], [5.0, 0.0, 5.0]]))
    np.save(receiver_locations, np.array([[-5.0, 0.0, 5.0], [5.0, 0.0, 5.0]]))
    multi_source_system = spec.tdem3d_forward.system.model_copy(
        update={
            "times": QuantitySpec(value=[], quantity_type=QuantityType.TIME, unit="s"),
            "source_locations": ArrayInputSpec(
                path=str(source_locations),
                quantity_type=QuantityType.LENGTH,
                unit="m",
            ),
            "receiver_locations": ArrayInputSpec(
                path=str(receiver_locations),
                quantity_type=QuantityType.LENGTH,
                unit="m",
            ),
            "source_kind": "magnetic_dipole",
            "source_moment": QuantitySpec(
                value=1.0,
                quantity_type=QuantityType.MAGNETIC_DIPOLE_MOMENT,
                unit="A*m^2",
            ),
            "time_gates": (
                TDEMTimeGateSpec(
                    start=QuantitySpec(value=1e-5, quantity_type=QuantityType.TIME, unit="s"),
                    end=QuantitySpec(value=3e-5, quantity_type=QuantityType.TIME, unit="s"),
                    integration_points=3,
                ),
            ),
            "waveform": "piecewise_linear",
            "waveform_times": QuantitySpec(
                value=[-2e-5, 0.0], quantity_type=QuantityType.TIME, unit="s"
            ),
            "waveform_current_fractions": (1.0, 0.0),
        }
    )
    tree_spec = spec.model_copy(
        update={
            "run_id": uuid4(),
            "mesh": TreeMeshSpec(
                cell_size=QuantitySpec(
                    value=[5.0, 5.0, 5.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                padding_distance=(padding, padding, padding),
                depth_core=QuantitySpec(value=20.0, quantity_type=QuantityType.LENGTH, unit="m"),
            ),
            "parameters": {
                "topography_path": str(topography),
            },
            "tdem3d_forward": spec.tdem3d_forward.model_copy(
                update={
                    "system": multi_source_system,
                    "initial_time": QuantitySpec(
                        value=-2e-5, quantity_type=QuantityType.TIME, unit="s"
                    ),
                }
            ),
        }
    )
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), tree_spec).valid
    tree_result = plugin.execute(PluginContext(tmp_path / "artifacts"), tree_spec)
    assert tree_result.summary["mesh_cells"] > tree_result.summary["model_cells"] > 0
    assert tree_result.summary["sounding_count"] == 2
    assert tree_result.summary["channel_count"] == 1
    assert tree_result.summary["observation_count"] == 2
    tree_prediction = (
        tmp_path
        / "artifacts"
        / next(
            artifact.relative_path
            for artifact in tree_result.artifacts
            if artifact.artifact_type == "predicted_data"
        )
    )
    assert np.isfinite(np.load(tree_prediction, allow_pickle=False)).all()
