import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    GravityInversionSpec,
    LayeredEarthSpec,
    QuantitySpec,
    RunSpec,
    TDEMBetaSpec,
    TDEMInversionSpec,
    TDEMModelSpec,
    TDEMOptimizerSpec,
    TDEMSystemSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_tdem1d import SimPEGTDEM1DPlugin
from ofag.services.run_service import RunService
from tests.conftest import progress_events


def test_simpeg_tdem1d_adapter_runs_in_si_units(tmp_path) -> None:
    pytest.importorskip("simpeg")
    observations = tmp_path / "sounding.csv"
    observations.write_text(
        "time_s,magnetic_flux_density_t\n"
        "1e-5,6.65728853e-11\n"
        "2.5118864315e-5,2.75417785e-11\n"
        "6.3095734448e-5,9.06325616e-12\n"
        "1.5848931925e-4,2.18525817e-12\n"
        "3.9810717055e-4,4.21439370e-13\n"
        "1e-3,7.70720620e-14\n",
        encoding="utf-8",
    )

    def vector_length(value: list[float]) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=QuantityType.LENGTH, unit="m")

    spec = RunSpec(
        plugin_id="simpeg.aem.tdem1d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-si-tdem-sounding",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
            units="T",
        ),
        tdem_inversion=TDEMInversionSpec(
            system=TDEMSystemSpec(
                times=QuantitySpec(
                    value=[
                        1e-5,
                        2.5118864315e-5,
                        6.3095734448e-5,
                        1.5848931925e-4,
                        3.9810717055e-4,
                        1e-3,
                    ],
                    quantity_type=QuantityType.TIME,
                    unit="s",
                ),
                source_location=vector_length([0.0, 0.0, 20.0]),
                receiver_location=vector_length([0.0, 0.0, 20.0]),
                source_radius=QuantitySpec(value=6.0, quantity_type=QuantityType.LENGTH, unit="m"),
                source_current=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.ELECTRIC_CURRENT, unit="A"
                ),
            ),
            earth=LayeredEarthSpec(layer_thicknesses=vector_length([5.0, 10.0, 20.0])),
            model=TDEMModelSpec(
                initial_conductivity=QuantitySpec(
                    value=0.03, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
                lower_bound=QuantitySpec(
                    value=1e-4, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
                upper_bound=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
            ),
            optimizer=TDEMOptimizerSpec(max_iterations=1, cg_max_iterations=4),
            beta=TDEMBetaSpec(n_power_iterations=2),
        ),
        parameters={
            "observations_path": str(observations),
            "data_uncertainty": QuantitySpec(
                value=5e-12,
                quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY,
                unit="T",
            ),
        },
    )
    plugin = SimPEGTDEM1DPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["engine"] == "simpeg"
    assert result.summary["solver"] == "tdem1d_layered"
    assert result.summary["model_layers"] == 4
    assert {item.artifact_type for item in result.artifacts} >= {
        "recovered_model",
        "recovered_log_model",
        "layer_top_depth",
        "predicted_data",
        "residual_data",
        "normalized_residual",
        "iteration_metrics",
    }
    events = progress_events(tmp_path / "artifacts" / str(spec.run_id))
    assert any(event["event_type"] == "iteration" and event["iteration"] == 1 for event in events)

    # The same configuration carried as a schema 1.1 physics payload -- the form ERT and
    # seismic will use -- must reach the plugin identically.
    assert spec.tdem_inversion is not None
    payload_spec = RunSpec.model_validate(
        spec.model_dump(mode="json", exclude={"run_id", "tdem_inversion"})
        | {
            "schema_version": "1.1",
            "physics": spec.tdem_inversion.model_dump(mode="json"),
        }
    )
    assert payload_spec.tdem_inversion is None
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), payload_spec).valid
    payload_result = plugin.execute(PluginContext(tmp_path / "artifacts"), payload_spec)
    assert payload_result.summary == result.summary


def test_run_service_reports_a_malformed_physics_payload_before_dispatch(tmp_path) -> None:
    """A payload the plugin cannot parse becomes issues, not a solver crash."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = RunSpec(
        schema_version="1.1",
        plugin_id="simpeg.aem.tdem1d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="broken",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
            units="T",
        ),
        physics={"earth": {"layer_thicknesses": "not a quantity"}},
    )

    report = service.validate(spec)

    assert not report.valid
    assert all(issue.field.startswith("physics.") for issue in report.issues)
    assert any("TDEMInversionSpec" in issue.remediation for issue in report.issues)


def test_a_plugin_without_a_physics_model_rejects_a_payload(tmp_path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = RunSpec(
        schema_version="1.1",
        plugin_id="ofag.fixture.gravity3d",
        dataset=DatasetSpec(
            name="fixture",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        physics={"anything": 1},
    )

    report = service.validate(spec)

    assert not report.valid
    assert report.issues[0].field == "physics"
    assert "does not accept a physics payload" in report.issues[0].message


def test_the_two_configuration_forms_cannot_be_combined() -> None:
    with pytest.raises(ValidationError, match="state the method configuration once"):
        RunSpec(
            plugin_id="simpeg.aem.tdem1d",
            dataset=DatasetSpec(
                name="both",
                coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
                physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
                units="T",
            ),
            physics={"anything": 1},
            tdem3d_forward=None,
            gravity_inversion=GravityInversionSpec(),
        )


def test_simpeg_tdem1d_supports_dbdt_and_piecewise_linear_waveforms(tmp_path) -> None:
    pytest.importorskip("simpeg")
    times = [1e-5, 2.5118864315e-5, 6.3095734448e-5, 1.5848931925e-4, 3.9810717055e-4, 1e-3]
    response = [
        -6.649729633576208e-08,
        -2.7468114227374207e-08,
        -8.994307895115611e-09,
        -2.1262561542375276e-09,
        -3.7937686821599554e-10,
        -5.477199081599099e-11,
    ]
    observations = tmp_path / "dbdt_sounding.csv"
    observations.write_text(
        "time_s,magnetic_flux_density_time_derivative_t_s\n"
        + "".join(
            f"{time:.12e},{value:.12e}\n" for time, value in zip(times, response, strict=True)
        ),
        encoding="utf-8",
    )

    def length(value: float | list[float]) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=QuantityType.LENGTH, unit="m")

    spec = RunSpec(
        plugin_id="simpeg.aem.tdem1d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-dbdt-tdem",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
            units="T/s",
        ),
        tdem_inversion=TDEMInversionSpec(
            system=TDEMSystemSpec(
                times=QuantitySpec(value=times, quantity_type=QuantityType.TIME, unit="s"),
                source_location=length([0.0, 0.0, 20.0]),
                receiver_location=length([0.0, 0.0, 20.0]),
                source_radius=length(6.0),
                source_current=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.ELECTRIC_CURRENT, unit="A"
                ),
                receiver_quantity="magnetic_flux_density_time_derivative",
                waveform="piecewise_linear",
                waveform_times=QuantitySpec(
                    value=[-0.002, -0.001, 0.0], quantity_type=QuantityType.TIME, unit="s"
                ),
                waveform_current_fractions=(1.0, 1.0, 0.0),
            ),
            earth=LayeredEarthSpec(layer_thicknesses=length([5.0, 10.0, 20.0])),
            model=TDEMModelSpec(
                initial_conductivity=QuantitySpec(
                    value=0.03, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
                lower_bound=QuantitySpec(
                    value=1e-4, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
                upper_bound=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.CONDUCTIVITY, unit="S/m"
                ),
            ),
            optimizer=TDEMOptimizerSpec(max_iterations=1, cg_max_iterations=4),
            beta=TDEMBetaSpec(n_power_iterations=2),
        ),
        parameters={
            "observations_path": str(observations),
            "data_uncertainty": QuantitySpec(
                value=5e-9,
                quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
                unit="T/s",
            ),
        },
    )
    plugin = SimPEGTDEM1DPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid
    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["data_unit"] == "T/s"
    assert {
        artifact.units
        for artifact in result.artifacts
        if artifact.artifact_type in {"predicted_data", "residual_data"}
    } == {"T/s"}


def test_an_unset_smoothness_weight_is_the_cell_size_squared_not_one() -> None:
    """The trap both layered plugins now guard against (F021)."""
    pytest.importorskip("simpeg")
    import numpy as np
    from discretize import TensorMesh
    from simpeg import regularization

    thicknesses = np.array([3.0, 4.0, 6.0, 9.0])
    mesh = TensorMesh([np.r_[thicknesses, thicknesses[-1]]])
    reference = np.zeros(5)

    unset = regularization.WeightedLeastSquares(mesh, alpha_s=0.01, reference_model=reference)
    wrong_axis = regularization.WeightedLeastSquares(
        mesh, alpha_s=0.01, alpha_z=1.0, reference_model=reference
    )
    named = regularization.WeightedLeastSquares(
        mesh, alpha_s=0.01, alpha_x=1.0, reference_model=reference
    )

    assert unset.alpha_x == pytest.approx(9.0), "unset is the first cell's size squared"
    assert wrong_axis.alpha_x == pytest.approx(9.0), "alpha_z on a 1D mesh does nothing"
    assert named.alpha_x == pytest.approx(1.0)
