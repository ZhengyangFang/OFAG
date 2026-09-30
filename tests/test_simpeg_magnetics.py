import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArrayInputSpec,
    CoordinateConvention,
    DatasetSpec,
    GravityOptimizerSpec,
    MagneticsInducingFieldSpec,
    MagneticsInversionSpec,
    MagneticsModelSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
    TreeMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_magnetics import SimPEGMagnetics3DPlugin
from tests.conftest import progress_events


def test_simpeg_tmi_magnetics_adapter_runs_in_nanotesla(tmp_path) -> None:
    pytest.importorskip("simpeg")
    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        "-10.0,-10.0,5.0,2.0\n"
        "10.0,-10.0,5.0,2.5\n"
        "-10.0,10.0,5.0,1.8\n"
        "10.0,10.0,5.0,2.2\n",
        encoding="utf-8",
    )
    initial_model = tmp_path / "initial_susceptibility.npy"
    reference_model = tmp_path / "reference_susceptibility.npy"
    weights = tmp_path / "cell_weights.npy"
    np.save(initial_model, np.full(8, 1e-4))
    np.save(reference_model, np.zeros(8))
    np.save(weights, np.ones(8))

    def susceptibility_array(path) -> ArrayInputSpec:
        return ArrayInputSpec(
            path=str(path), quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )

    spec = RunSpec(
        plugin_id="simpeg.pf.magnetics3d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-nt-tmi",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_ANOMALY,
            units="nT",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(2, 2, 2),
            origin=(-20.0, -20.0, -40.0),
        ),
        magnetics_inversion=MagneticsInversionSpec(
            inducing_field=MagneticsInducingFieldSpec(
                amplitude=QuantitySpec(
                    value=50_000.0,
                    quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY,
                    unit="nT",
                ),
                inclination=QuantitySpec(
                    value=60.0, quantity_type=QuantityType.ANGLE, unit="degree"
                ),
                declination=QuantitySpec(
                    value=15.0, quantity_type=QuantityType.ANGLE, unit="degree"
                ),
            ),
            model=MagneticsModelSpec(
                # A signed effective-susceptibility parameterization is deliberately
                # supported for scalar TMI workflows that must absorb remanence or other
                # modelling mismatch.
                initial_susceptibility=QuantitySpec(
                    value=1e-6,
                    quantity_type=QuantityType.SUSCEPTIBILITY,
                    unit="dimensionless",
                ),
                lower_bound=QuantitySpec(
                    value=-2.0,
                    quantity_type=QuantityType.SUSCEPTIBILITY,
                    unit="dimensionless",
                ),
                upper_bound=QuantitySpec(
                    value=2.0,
                    quantity_type=QuantityType.SUSCEPTIBILITY,
                    unit="dimensionless",
                ),
                initial_model=susceptibility_array(initial_model),
                reference_model=susceptibility_array(reference_model),
            ),
            optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=8),
        ),
        parameters={
            "observations_path": str(observations),
            "data_uncertainty": QuantitySpec(
                value=0.1, quantity_type=QuantityType.MAGNETIC_ANOMALY, unit="nT"
            ),
        },
    )
    plugin = SimPEGMagnetics3DPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["engine"] == "simpeg"
    assert result.summary["solver"] == "least_squares_magnetics3d_tmi"
    assert result.summary["data_unit"] == "nT"
    assert result.summary["model_unit"] == "dimensionless"
    assert {item.artifact_type for item in result.artifacts} >= {
        "recovered_model",
        "predicted_data",
        "residual_data",
        "iteration_metrics",
    }
    prediction = np.load(tmp_path / "artifacts" / str(spec.run_id) / "predicted_tmi_nt.npy")
    assert np.isfinite(prediction).all()
    events = progress_events(tmp_path / "artifacts" / str(spec.run_id))
    assert any(event["event_type"] == "iteration" and event["iteration"] == 1 for event in events)


def test_tmi_magnetics_rejects_tiling() -> None:
    with pytest.raises(ValueError, match="does not yet support tiling"):
        MagneticsInversionSpec.model_validate(
            {"simulation": {"tiling": {"enabled": True, "tile_count": 2}}}
        )


def test_simpeg_tmi_magnetics_runs_on_a_treemesh(tmp_path) -> None:
    pytest.importorskip("simpeg")
    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        "-20.0,-20.0,10.0,2.0\n"
        "20.0,-20.0,10.0,2.4\n"
        "-20.0,20.0,10.0,1.7\n"
        "20.0,20.0,10.0,2.1\n",
        encoding="utf-8",
    )
    topography = tmp_path / "topography.csv"
    topography.write_text(
        "x_m,y_m,z_m\n-40.0,-40.0,0.0\n40.0,-40.0,0.0\n-40.0,40.0,0.0\n40.0,40.0,0.0\n",
        encoding="utf-8",
    )
    cell_size = QuantitySpec(value=[20.0, 20.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m")
    padding = QuantitySpec(value=[40.0, 40.0], quantity_type=QuantityType.LENGTH, unit="m")
    spec = RunSpec(
        plugin_id="simpeg.pf.magnetics3d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-tree-nt-tmi",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_ANOMALY,
            units="nT",
        ),
        mesh=TreeMeshSpec(
            cell_size=cell_size,
            padding_distance=(padding, padding, padding),
            depth_core=QuantitySpec(value=40.0, quantity_type=QuantityType.LENGTH, unit="m"),
        ),
        magnetics_inversion=MagneticsInversionSpec(
            optimizer=GravityOptimizerSpec(max_iterations=1, cg_max_iterations=8)
        ),
        parameters={
            "observations_path": str(observations),
            "topography_path": str(topography),
            "data_uncertainty": QuantitySpec(
                value=0.1, quantity_type=QuantityType.MAGNETIC_ANOMALY, unit="nT"
            ),
        },
    )
    result = SimPEGMagnetics3DPlugin().execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["mesh_kind"] == "TreeMesh"
    assert result.summary["mesh_cells"] > result.summary["model_cells"] > 0
    assert any(item.artifact_type == "mesh_geometry" for item in result.artifacts)


def test_the_summary_reports_chi_squared_and_not_only_simpegs_objective() -> None:
    """`phi_data` is half the sum of squared normalised residuals, so a reader dividing it by
    the observation count gets half the true value."""
    from ofag.plugins.simpeg_gravity import chi_squared

    # Ten observations each one sigma out: sum of squares 10, phi_data 5.
    assert chi_squared(5.0, 10) == pytest.approx(1.0)
    assert chi_squared(0.0, 10) == 0.0
    # An observation count of zero cannot divide, and reporting infinity for a run with
    # no data would be worse than reporting the objective itself.
    assert chi_squared(5.0, 0) == pytest.approx(10.0)
