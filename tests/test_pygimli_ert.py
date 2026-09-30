import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DataChannelSpec,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.pygimli_ert import ERTInversionSpec, PyGIMLiERTPlugin
from ofag.services.run_service import RunService
from tests.conftest import progress_events

CONVENTION = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")


def _dipole_dipole(electrode_count: int, spacing_m: float) -> tuple[np.ndarray, np.ndarray]:
    """A surface dipole-dipole line, with the quadrupole sequence pyGIMLi builds."""
    from pygimli.physics import ert

    positions = np.arange(electrode_count, dtype=float) * spacing_m
    electrodes = np.column_stack([positions, np.zeros(electrode_count), np.zeros(electrode_count)])
    scheme = ert.createData(elecs=positions, schemeName="dd")
    quadrupoles = np.column_stack([np.asarray(scheme[token], dtype=np.int64) for token in "abmn"])
    return electrodes, quadrupoles


def _write_survey(tmp_path, electrodes: np.ndarray, quadrupoles: np.ndarray) -> dict[str, str]:
    electrodes_path = tmp_path / "electrodes.npy"
    quadrupoles_path = tmp_path / "quadrupoles.npy"
    np.save(electrodes_path, electrodes)
    np.save(quadrupoles_path, quadrupoles)
    return {
        "electrodes_path": str(electrodes_path),
        "quadrupoles_path": str(quadrupoles_path),
    }


def _dc_channel(observations_path: str, uncertainty_ohm: float = 0.02) -> DataChannelSpec:
    return DataChannelSpec(
        channel_id="dc",
        dataset=DatasetSpec(
            name="dc-line",
            coordinate_convention=CONVENTION,
            physical_quantity=QuantityType.TRANSFER_RESISTANCE,
            units="ohm",
        ),
        observations_path=observations_path,
        data_uncertainty=QuantitySpec(
            value=uncertainty_ohm,
            quantity_type=QuantityType.TRANSFER_RESISTANCE,
            unit="ohm",
        ),
    )


def _simulate_line(tmp_path, electrodes: np.ndarray, quadrupoles: np.ndarray) -> str:
    """Forward model a two-block section so the test inverts real numbers."""
    import pygimli as pg
    from pygimli.physics import ert

    scheme = ert.createData(elecs=electrodes[:, 0], schemeName="dd")
    scheme.resize(len(quadrupoles))
    for position, token in enumerate("abmn"):
        scheme[token] = quadrupoles[:, position]

    span = float(electrodes[:, 0].max())
    world = pg.meshtools.createWorld(start=[-span / 2, 0.0], end=[1.5 * span, -span / 2])
    block = pg.meshtools.createRectangle(
        start=[span * 0.35, -span * 0.06], end=[span * 0.65, -span * 0.25], marker=2
    )
    mesh = pg.meshtools.createMesh(world + block, quality=32, area=span / 8)
    data = ert.simulate(
        mesh, res=[[1, 100.0], [2, 10.0]], scheme=scheme, noiseLevel=0.02, seed=0, verbose=False
    )

    path = tmp_path / "dc_observations.csv"
    resistance = np.asarray(data["r"], dtype=float)
    lines = ["resistance_ohm"] + [f"{value:.10e}" for value in resistance]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _run_spec(tmp_path, physics: dict, channel: DataChannelSpec) -> RunSpec:
    return RunSpec(
        schema_version="1.1",
        plugin_id="pygimli.ert.dcip",
        engine="pygimli",
        dataset=channel.dataset,
        datasets=(channel,),
        physics=physics,
    )


def test_pygimli_ert_inverts_a_two_and_a_half_d_line(tmp_path) -> None:
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(24, 2.0)
    observations_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    channel = _dc_channel(observations_path)
    physics = {
        "array": _write_survey(tmp_path, electrodes, quadrupoles),
        "mesh": {"dimension": 2, "quality": 32.0},
        "optimizer": {"max_iterations": 4},
    }
    spec = _run_spec(tmp_path, physics, channel)
    plugin = PyGIMLiERTPlugin()
    context = PluginContext(tmp_path / "artifacts")

    assert plugin.validate(context, spec).valid
    result = plugin.execute(context, spec)

    assert result.summary["engine"] == "pygimli"
    assert result.summary["solver"] == "ert_2d_dc"
    assert result.summary["electrodes"] == 24
    assert result.summary["quadrupoles"] == len(quadrupoles)
    assert result.summary["model_unit"] == "ohm*m"
    assert result.summary["data_unit"] == "ohm"
    assert {item.artifact_type for item in result.artifacts} == {
        "recovered_model",
        "predicted_data",
        "residual_data",
        "predicted_apparent_resistivity",
        "observed_apparent_resistivity",
        "model_coverage",
        "mesh_geometry",
    }

    run_artifacts = tmp_path / "artifacts" / str(spec.run_id)
    observed = np.genfromtxt(observations_path, delimiter=",", names=True)["resistance_ohm"]
    predicted = np.load(run_artifacts / "predicted_data.npy")
    residual = np.load(run_artifacts / "residual_data.npy")

    # The predicted data must come back in the observation's own unit.
    assert np.allclose(residual, observed - predicted)
    relative = np.sqrt(np.mean(residual**2)) / np.sqrt(np.mean(observed**2))
    assert relative < 0.2, f"predicted data does not fit: relative RMS {relative:.3f}"

    # Judge the section where the survey actually constrains it.
    model = np.load(run_artifacts / "recovered_model.npy")
    centers = np.load(run_artifacts / "mesh_geometry.npz")["cell_centers_m"]
    assert np.isfinite(model).all()
    easting, elevation = centers[:, 0], centers[:, 1]
    span = float(electrodes[:, 0].max())
    block = (
        (easting > span * 0.38)
        & (easting < span * 0.62)
        & (elevation < -span * 0.07)
        & (elevation > -span * 0.22)
    )
    background = (
        (easting > span * 0.05)
        & (easting < span * 0.25)
        & (elevation < -span * 0.03)
        & (elevation > -span * 0.15)
    )
    assert block.any() and background.any()
    recovered_background = float(np.median(model[background]))
    recovered_block = float(np.median(model[block]))
    assert 60.0 < recovered_background < 160.0, recovered_background
    # Smoothness keeps the 10 ohm.m block from being fully resolved, but it must still
    # come out clearly more conductive than the 100 ohm.m host.
    assert recovered_block < 0.6 * recovered_background, (recovered_block, recovered_background)

    # An unstructured mesh still leaves the engine as portable arrays.
    geometry = np.load(tmp_path / "artifacts" / str(spec.run_id) / "mesh_geometry.npz")
    assert set(geometry) == {"nodes_m", "cell_nodes", "cell_centers_m", "cell_sizes"}
    assert geometry["cell_centers_m"].shape == (len(model), 3)
    assert geometry["cell_nodes"].max() < len(geometry["nodes_m"])

    # Coverage says where the section means anything.
    coverage = np.load(run_artifacts / "model_coverage.npy")
    assert coverage.shape == model.shape
    assert np.isfinite(coverage).all()
    # It has to actually discriminate: a constant array would fade nothing.
    assert coverage.max() - coverage.min() > 1.0

    # The whole convergence history reaches the monitor, not only the last value.
    events = progress_events(run_artifacts)
    iterations = [
        event for event in events if event["stage"] == "dc" and event["phi_data"] is not None
    ]
    assert len(iterations) >= 2
    assert [event["iteration"] for event in iterations] == list(range(1, len(iterations) + 1))
    assert iterations[-1]["phi_data"] < iterations[0]["phi_data"]


def test_the_ert_plugin_needs_no_field_in_the_core_schema() -> None:
    """Phase C's point: a new method registers without touching core schemas."""
    import ofag.core.schemas as core

    assert not [name for name in dir(core) if name.lower().startswith("ert")]
    assert PyGIMLiERTPlugin().physics_model() is ERTInversionSpec
    assert "ert" not in RunSpec.model_fields


def test_a_core_mesh_is_rejected_because_pygimli_owns_its_own(tmp_path) -> None:
    electrodes, quadrupoles = _dipole_dipole(8, 2.0)
    observations = tmp_path / "dc.csv"
    observations.write_text(
        "resistance_ohm\n" + "\n".join("1.0" for _ in quadrupoles) + "\n", encoding="utf-8"
    )
    channel = _dc_channel(str(observations))
    spec = _run_spec(
        tmp_path, {"array": _write_survey(tmp_path, electrodes, quadrupoles)}, channel
    ).model_copy(
        update={
            "mesh": TensorMeshSpec(
                cell_size=QuantitySpec(
                    value=[5.0, 2.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                shape=(4, 2),
                origin=(0.0, -10.0),
            )
        }
    )

    report = PyGIMLiERTPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    assert any(issue.field == "mesh" for issue in report.issues)


def test_apparent_resistivity_is_refused_as_the_observation(tmp_path) -> None:
    """The measured primitive is transfer resistance; rhoa hides a geometric factor."""
    electrodes, quadrupoles = _dipole_dipole(8, 2.0)
    observations = tmp_path / "dc.csv"
    observations.write_text("resistance_ohm\n1.0\n", encoding="utf-8")
    channel = DataChannelSpec(
        channel_id="dc",
        dataset=DatasetSpec(
            name="rhoa-line",
            coordinate_convention=CONVENTION,
            physical_quantity=QuantityType.APPARENT_RESISTIVITY,
            units="ohm*m",
        ),
        observations_path=str(observations),
        data_uncertainty=QuantitySpec(
            value=1.0, quantity_type=QuantityType.APPARENT_RESISTIVITY, unit="ohm*m"
        ),
    )
    spec = _run_spec(tmp_path, {"array": _write_survey(tmp_path, electrodes, quadrupoles)}, channel)

    report = PyGIMLiERTPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    issue = next(item for item in report.issues if "physical_quantity" in item.field)
    assert "transfer resistance in ohm" in issue.remediation


def test_quadrupole_indices_are_zero_based(tmp_path) -> None:
    """Field formats number electrodes from 1, so an off-by-one must be caught."""
    electrodes, quadrupoles = _dipole_dipole(8, 2.0)
    observations = tmp_path / "dc.csv"
    observations.write_text(
        "resistance_ohm\n" + "\n".join("1.0" for _ in quadrupoles) + "\n", encoding="utf-8"
    )
    one_based = quadrupoles + 1
    spec = _run_spec(
        tmp_path,
        {"array": _write_survey(tmp_path, electrodes, one_based)},
        _dc_channel(str(observations)),
    )

    report = PyGIMLiERTPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    issue = next(item for item in report.issues if "quadrupoles_path" in item.field)
    assert "0-based" in issue.remediation


def test_remote_electrodes_are_accepted(tmp_path) -> None:
    """Pole-dipole leaves B at infinity, which the -1 sentinel represents."""
    electrodes, quadrupoles = _dipole_dipole(8, 2.0)
    pole_dipole = quadrupoles.copy()
    pole_dipole[:, 1] = -1
    observations = tmp_path / "dc.csv"
    observations.write_text(
        "resistance_ohm\n" + "\n".join("1.0" for _ in quadrupoles) + "\n", encoding="utf-8"
    )
    spec = _run_spec(
        tmp_path,
        {"array": _write_survey(tmp_path, electrodes, pole_dipole)},
        _dc_channel(str(observations)),
    )

    report = PyGIMLiERTPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert report.valid, [issue.message for issue in report.issues]


def test_the_ip_channel_must_differ_from_the_dc_channel() -> None:
    with pytest.raises(ValidationError, match="different channel"):
        ERTInversionSpec.model_validate(
            {
                "array": {"electrodes_path": "e.npy", "quadrupoles_path": "q.npy"},
                "resistance_channel": "dc",
                "chargeability_channel": "dc",
            }
        )


def test_run_service_reports_a_malformed_ert_payload(tmp_path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    observations = tmp_path / "dc.csv"
    observations.write_text("resistance_ohm\n1.0\n", encoding="utf-8")
    spec = _run_spec(tmp_path, {"mesh": {"dimension": 4}}, _dc_channel(str(observations)))

    report = service.validate(spec)

    assert not report.valid
    assert any(issue.field.startswith("physics.") for issue in report.issues)


def _corrupted_survey(tmp_path, resistance: np.ndarray, bad: dict[int, float]) -> str:
    """A survey file with specific measurements spoiled the way field data is."""
    spoiled = resistance.copy()
    for index, value in bad.items():
        spoiled[index] = value
    path = tmp_path / "spoiled_observations.csv"
    lines = ["resistance_ohm"] + [f"{value:.10e}" for value in spoiled]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_bad_measurements_are_removed_only_when_asked_and_are_counted(tmp_path) -> None:
    """Field resistivity data is never all usable, and culling must be visible."""
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(20, 2.0)
    clean_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    resistance = np.genfromtxt(clean_path, delimiter=",", names=True)["resistance_ohm"]
    # A dead current injection and a reading of the wrong sign.
    clean = np.asarray(resistance, dtype=float)
    spoiled = _corrupted_survey(tmp_path, clean, {3: -clean[3], 11: 0.0})
    array = _write_survey(tmp_path, electrodes, quadrupoles)
    plugin = PyGIMLiERTPlugin()
    context = PluginContext(tmp_path / "artifacts")

    unfiltered_spec = _run_spec(
        tmp_path,
        {"array": array, "mesh": {"quality": 32.0}, "optimizer": {"max_iterations": 2}},
        _dc_channel(spoiled),
    )
    # A single zero makes pyGIMLi refuse the whole survey, with a message that reads as
    # though the resistance field were missing.
    with pytest.raises(ValueError, match="exactly zero"):
        plugin.execute(context, unfiltered_spec)

    filtered = plugin.execute(
        context,
        _run_spec(
            tmp_path,
            {
                "array": array,
                "mesh": {"quality": 32.0},
                "optimizer": {"max_iterations": 2},
                "quality": {"drop_non_positive": True},
            },
            _dc_channel(spoiled),
        ),
    )
    assert filtered.summary["measurements_removed"] == 2
    assert filtered.summary["quality_filtered"] is True
    assert filtered.summary["quadrupoles"] == len(quadrupoles) - 2
    assert filtered.summary["chi_squared"] > 0
    # Which measurements survived, so the residuals can be traced back.
    retained = next(
        item for item in filtered.artifacts if item.artifact_type == "retained_measurements"
    )
    kept = np.load(tmp_path / "artifacts" / retained.relative_path, allow_pickle=False)
    assert kept.size == len(quadrupoles) - 2
    assert 3 not in kept and 11 not in kept


def test_thresholds_that_remove_everything_are_refused(tmp_path) -> None:
    """Silently inverting nothing would produce a section made only of the prior."""
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(12, 2.0)
    observations_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    spec = _run_spec(
        tmp_path,
        {
            "array": _write_survey(tmp_path, electrodes, quadrupoles),
            "mesh": {"quality": 32.0},
            "optimizer": {"max_iterations": 1},
            "quality": {"maximum_geometric_factor": 1e-9},
        },
        _dc_channel(observations_path),
    )

    with pytest.raises(ValueError, match="removed every measurement"):
        PyGIMLiERTPlugin().execute(PluginContext(tmp_path / "artifacts"), spec)


def test_topography_moves_the_electrodes_and_the_summary_says_so(tmp_path) -> None:
    """A run reported terrain whenever a path was configured, while inverting flat."""
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(16, 2.0)
    observations_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    array = _write_survey(tmp_path, electrodes, quadrupoles)
    surface = tmp_path / "surface.csv"
    rows = ["x_m,y_m,z_m"] + [f"{x:.3f},0.0,{0.4 * x:.3f}" for x in np.arange(-4.0, 40.0, 0.5)]
    surface.write_text("\n".join(rows) + "\n", encoding="utf-8")
    plugin = PyGIMLiERTPlugin()
    context = PluginContext(tmp_path / "artifacts")
    base = {"array": array, "mesh": {"quality": 32.0}, "optimizer": {"max_iterations": 2}}

    flat = plugin.execute(context, _run_spec(tmp_path, base, _dc_channel(observations_path)))
    assert flat.summary["topography_applied"] is False
    assert flat.summary["electrode_elevation_shift_m"] == 0.0

    sloped = plugin.execute(
        context,
        _run_spec(
            tmp_path, {**base, "topography_path": str(surface)}, _dc_channel(observations_path)
        ),
    )
    assert sloped.summary["topography_applied"] is True
    # The line runs 0 to 30 m across a surface rising at 0.4, so the far electrode moves
    # about 12 m; a flat inversion would have reported none.
    assert sloped.summary["electrode_elevation_shift_m"] == pytest.approx(12.0, abs=0.5)


def test_the_model_norm_reaches_pygimli_and_is_reported(tmp_path) -> None:
    """L1 on the model constraint has to change the model, and say that it did."""
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(24, 2.0)
    observations_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    base = {
        "array": _write_survey(tmp_path, electrodes, quadrupoles),
        "mesh": {"quality": 32.0},
        "optimizer": {"max_iterations": 8},
    }
    plugin = PyGIMLiERTPlugin()

    def invert(regularization: dict, name: str) -> tuple[np.ndarray, dict]:
        context = PluginContext(tmp_path / name)
        result = plugin.execute(
            context,
            _run_spec(
                tmp_path, {**base, "regularization": regularization}, _dc_channel(observations_path)
            ),
        )
        model = np.load(next((tmp_path / name).rglob("recovered_model.npy")))
        return model, result.summary

    smooth, smooth_summary = invert({}, "smooth")
    blocky, blocky_summary = invert({"blocky_model": True}, "blocky")

    assert smooth_summary["blocky_model"] is False
    assert blocky_summary["blocky_model"] is True
    assert blocky_summary["robust_data"] is False
    assert smooth.shape == blocky.shape
    assert not np.allclose(smooth, blocky, rtol=0.02), "the L1 model constraint did nothing"


def test_electrodes_that_arrive_with_their_own_elevations_report_terrain(tmp_path) -> None:
    """The flag reports the surface the mesh has, not who supplied it."""
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(16, 2.0)
    # A line falling 6 m over its 30, steeper than the tolerance by far and about what
    # this costs in the field.
    electrodes = electrodes.copy()
    electrodes[:, 2] = -0.2 * electrodes[:, 0]
    observations_path = _simulate_line(tmp_path, electrodes, quadrupoles)
    result = PyGIMLiERTPlugin().execute(
        PluginContext(tmp_path / "artifacts"),
        _run_spec(
            tmp_path,
            {
                "array": _write_survey(tmp_path, electrodes, quadrupoles),
                "mesh": {"quality": 32.0},
                "optimizer": {"max_iterations": 1},
            },
            _dc_channel(observations_path),
        ),
    )

    assert result.summary["topography_applied"] is True
    assert result.summary["electrode_relief_m"] == pytest.approx(6.0, abs=0.01)
    # No file was given, so nothing moved them; the two questions stay apart.
    assert result.summary["electrode_elevation_shift_m"] == 0.0


def test_a_missing_topography_file_is_refused_rather_than_ignored(tmp_path) -> None:
    pytest.importorskip("pygimli")
    electrodes, quadrupoles = _dipole_dipole(12, 2.0)
    spec = _run_spec(
        tmp_path,
        {
            "array": _write_survey(tmp_path, electrodes, quadrupoles),
            "mesh": {"quality": 32.0},
            "optimizer": {"max_iterations": 1},
            "topography_path": str(tmp_path / "absent.csv"),
        },
        _dc_channel(_simulate_line(tmp_path, electrodes, quadrupoles)),
    )

    with pytest.raises(ValueError, match="does not exist"):
        PyGIMLiERTPlugin().execute(PluginContext(tmp_path / "artifacts"), spec)


def _wenner(electrode_count: int, spacing_m: float, relief_m: float) -> tuple:
    """A Wenner line on a constant slope, and one quadrupole from it."""
    easting = np.arange(electrode_count, dtype=float) * spacing_m
    elevation = np.linspace(0.0, relief_m, electrode_count)
    electrodes = np.column_stack([easting, np.zeros(electrode_count), elevation])
    quadrupoles = np.asarray([[0, 3, 1, 2]], dtype=np.int64)
    return electrodes, quadrupoles


def test_the_geometric_factor_belongs_to_the_quadrupoles_it_is_stored_with() -> None:
    """On flat ground a Wenner factor is 2*pi*a, whatever scheme built the container."""
    pytest.importorskip("pygimli")
    from pygimli.physics import ert

    spacing = 2.0
    electrodes, quadrupoles = _wenner(8, spacing, relief_m=0.0)
    container = PyGIMLiERTPlugin._build_data_container(
        ert,
        electrodes,
        quadrupoles,
        np.ones(1),
        np.full(1, 0.03),
        2,
    )

    assert np.asarray(container["k"])[0] == pytest.approx(2.0 * np.pi * spacing, rel=1e-6)


def test_a_sloped_line_gets_the_numerical_factor_rather_than_the_flat_formula() -> None:
    """The analytic factor is a half-space formula, exact only on a plane."""
    pytest.importorskip("pygimli")
    from pygimli.physics import ert

    spacing = 2.0
    electrodes, quadrupoles = _wenner(8, spacing, relief_m=7.0)
    container = PyGIMLiERTPlugin._build_data_container(
        ert,
        electrodes,
        quadrupoles,
        np.ones(1),
        np.full(1, 0.03),
        2,
    )
    factor = float(np.asarray(container["k"])[0])
    flat = 2.0 * np.pi * float(np.hypot(spacing, 7.0 / 7.0))

    assert factor > 0.0
    assert factor != pytest.approx(flat, rel=1e-6)
    assert 0.5 * flat < factor < 2.0 * flat
