"""2D elastic full-waveform inversion of a land line, through Deepwave."""

from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import CoordinateConvention, DatasetSpec, RunEvent, RunSpec
from ofag.engines.deepwave.elastic import (
    MINIMUM_SHEAR_VELOCITY_M_S,
    from_lame,
    grid_indices,
    to_lame,
)
from ofag.plugins.deepwave_fwi import (
    MAXIMUM_COURANT,
    MINIMUM_CELLS_PER_WAVELENGTH,
    MINIMUM_VP_OVER_VS,
    DeepwaveElasticFwiPlugin,
    ElasticFwiSpec,
    _highest_frequency,
)
from ofag.plugins.protocol import PluginContext
from ofag.services.run_service import RunService

needs_deepwave = pytest.mark.skipif(
    find_spec("deepwave") is None, reason="the seismic extra is not installed"
)

CONVENTION = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")
NZ, NX = 40, 90
SPACING_M = 5.0
TIME_STEP_S = 0.0006
SAMPLES = 350
PEAK_HZ = 10.0


def test_the_lame_conversion_round_trips() -> None:
    """A model handed over unconverted propagates a plausible, wrong wavefield."""
    vp = np.array([[1500.0, 2400.0], [1800.0, 2600.0]])
    vs = np.array([[800.0, 1300.0], [950.0, 1400.0]])
    density = np.array([[1900.0, 2200.0], [2000.0, 2300.0]])

    lame = to_lame(vp, vs, density)

    # mu = rho vs^2 and lamb = rho vp^2 - 2 mu, exactly.
    assert lame.mu == pytest.approx(density * vs**2)
    assert lame.lamb == pytest.approx(density * vp**2 - 2.0 * density * vs**2)
    assert lame.buoyancy == pytest.approx(1.0 / density)

    back_vp, back_vs, back_density = from_lame(lame)
    assert back_vp == pytest.approx(vp)
    assert back_vs == pytest.approx(vs)
    assert back_density == pytest.approx(density)


def test_exchanged_velocity_files_are_refused_by_the_physics() -> None:
    """vp below sqrt(2) vs is a negative Poisson ratio, so vp and vs were swapped."""
    vp = np.full((3, 3), 900.0)
    vs = np.full((3, 3), 1800.0)
    density = np.full((3, 3), 2000.0)

    with pytest.raises(ValueError, match="were not exchanged"):
        to_lame(vp, vs, density)


def test_a_fluid_layer_is_refused_before_the_solver_diverges() -> None:
    """The free-surface vacuum method is unstable where mu is zero."""
    vp = np.full((3, 3), 1500.0)
    vs = np.full((3, 3), MINIMUM_SHEAR_VELOCITY_M_S / 2)
    density = np.full((3, 3), 1000.0)

    with pytest.raises(ValueError, match="shear velocity"):
        to_lame(vp, vs, density)


def test_grid_indices_put_depth_first_to_match_the_engines_plane() -> None:
    """Deepwave's 2D `y` is depth downwards; OFAG's y is Northing."""
    positions = np.array([[0.0, 0.0], [50.0, 20.0]])

    indices = grid_indices(positions, (0.0, 0.0), 5.0, (40, 90))

    assert indices.tolist() == [[0, 0], [4, 10]]


def test_a_station_outside_the_grid_is_refused_rather_than_clamped() -> None:
    """Clamping moves a shot to the model edge and the misfit is then fitted by a velocity
    error somewhere else entirely."""
    positions = np.array([[1000.0, 0.0]])

    with pytest.raises(ValueError, match="falls outside"):
        grid_indices(positions, (0.0, 0.0), 5.0, (40, 90))


def _layered(deep_vp: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    vp = np.full((NZ, NX), 1500.0)
    vs = np.full((NZ, NX), 800.0)
    density = np.full((NZ, NX), 1900.0)
    vp[22:, :] = deep_vp
    vs[22:, :] = deep_vp / 1.9
    density[22:, :] = 2100.0
    return vp, vs, density


def _survey(tmp_path: Path) -> dict[str, Any]:
    """A land line, with observed data forward-modelled through the same engine."""
    import torch
    from deepwave.wavelets import ricker

    from ofag.engines.deepwave.elastic import propagate

    true_vp, true_vs, true_density = _layered(2400.0)
    sources = np.array([[100.0, 5.0], [250.0, 5.0]])
    receivers = np.array([[x, 5.0] for x in range(150, 400, 15)], dtype=float)

    tensors = {
        name: torch.tensor(values, dtype=torch.float64)
        for name, values in (("vp", true_vp), ("vs", true_vs), ("density", true_density))
    }
    mu = tensors["density"] * tensors["vs"] ** 2
    wavelet = ricker(PEAK_HZ, SAMPLES, TIME_STEP_S, 1.3 / PEAK_HZ).to(torch.float64)
    source_indices = torch.tensor(grid_indices(sources, (0.0, 0.0), SPACING_M, (NZ, NX))).reshape(
        len(sources), 1, 2
    )
    receiver_indices = torch.tensor(
        grid_indices(receivers, (0.0, 0.0), SPACING_M, (NZ, NX))
    ).repeat(len(sources), 1, 1)
    observed = propagate(
        tensors["density"] * tensors["vp"] ** 2 - 2.0 * mu,
        mu,
        1.0 / tensors["density"],
        spacing_m=SPACING_M,
        time_step_s=TIME_STEP_S,
        wavelet=wavelet.reshape(1, 1, -1).repeat(len(sources), 1, 1),
        source_indices=source_indices,
        receiver_indices=receiver_indices,
        peak_frequency_hz=PEAK_HZ,
        pml_cells=15,
    )

    paths = {}
    for name, values in (
        ("sources", sources),
        ("receivers", receivers),
        ("observations", observed.detach().numpy()),
        ("vp0", 0.88 * true_vp),
        ("vs0", 0.88 * true_vs),
        ("density", true_density),
    ):
        path = tmp_path / f"{name}.npy"
        np.save(path, values)
        paths[name] = str(path)
    return {"paths": paths, "true_vp": true_vp, "start_vp": 0.88 * true_vp}


def _physics(paths: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "grid": {
            "shape": [NZ, NX],
            "cell_size": {"value": SPACING_M, "quantity_type": "length", "unit": "m"},
        },
        "geometry": {
            "sources_path": paths["sources"],
            "receivers_path": paths["receivers"],
            "observations_path": paths["observations"],
            "time_step": {"value": TIME_STEP_S, "quantity_type": "time", "unit": "s"},
            "pml_cells": 15,
        },
        "wavelet": {
            "peak_frequency": {"value": PEAK_HZ, "quantity_type": "frequency", "unit": "Hz"}
        },
        "stages": [
            {
                "corner_frequency": {"value": 8.0, "quantity_type": "frequency", "unit": "Hz"},
                "iterations": 6,
            },
            {"iterations": 6},
        ],
        "misfit": "l2",
        "initial_vp_path": paths["vp0"],
        "initial_vs_path": paths["vs0"],
        "density_path": paths["density"],
        "learning_rate": 15.0,
    }
    payload.update(overrides)
    return payload


def _spec(physics: dict[str, Any]) -> RunSpec:
    return RunSpec(
        schema_version="1.1",
        plugin_id="deepwave.fwi.elastic2d",
        engine="deepwave",
        dataset=DatasetSpec(
            name="land line",
            coordinate_convention=CONVENTION,
            physical_quantity=QuantityType.PARTICLE_VELOCITY,
            units="m/s",
        ),
        physics=physics,
    )


@needs_deepwave
def test_the_inversion_reduces_the_misfit_and_moves_the_model_towards_truth(
    tmp_path: Path,
) -> None:
    survey = _survey(tmp_path)
    spec = _spec(_physics(survey["paths"]))
    context = PluginContext(tmp_path / "artifacts")
    plugin = DeepwaveElasticFwiPlugin()

    assert plugin.validate(context, spec).valid
    result = plugin.execute(context, spec)

    initial = float(result.summary["misfit_initial"])
    final = float(result.summary["misfit_final"])
    # The misfit is relative to the observed data's own energy, so a value near one
    # means "as wrong as predicting silence" and this comparison means something across
    # surveys of different amplitude.
    assert result.summary["misfit_is_relative"] is True
    assert 0.05 < initial < 5.0, "the starting model should be visibly wrong, not already fitted"
    assert final < 0.5 * initial, f"the misfit did not fall: {initial:g} to {final:g}"

    recovered = np.load(
        tmp_path / "artifacts" / str(spec.run_id) / "recovered_model.npy", allow_pickle=False
    )
    # Where the data has sensitivity -- the shallow section a surface wave samples --
    # the model must move towards the truth rather than away.
    shallow = (10, 45)
    assert survey["start_vp"][shallow] < recovered[shallow] <= survey["true_vp"][shallow] * 1.05


@needs_deepwave
def test_every_iteration_reports_which_stage_of_the_ladder_it_is_in(tmp_path: Path) -> None:
    """A staged solve restarts its iteration count in each band, so the stage is what makes a
    progress plot readable."""
    survey = _survey(tmp_path)
    physics = _physics(
        survey["paths"],
        stages=[
            {
                "corner_frequency": {"value": 8.0, "quantity_type": "frequency", "unit": "Hz"},
                "iterations": 2,
            },
            {"iterations": 3},
        ],
    )
    spec = _spec(physics)
    context = PluginContext(tmp_path / "artifacts")

    DeepwaveElasticFwiPlugin().execute(context, spec)

    lines = (
        (tmp_path / "artifacts" / str(spec.run_id) / "progress.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    import json

    iterations = [
        json.loads(line) for line in lines if json.loads(line)["event_type"] == "iteration"
    ]
    assert [item["stage"] for item in iterations] == [
        "stage-1",
        "stage-1",
        "stage-2",
        "stage-2",
        "stage-2",
    ]
    assert {item["stage_total"] for item in iterations} == {2}
    assert [item["iteration"] for item in iterations] == [1, 2, 1, 2, 3]


@needs_deepwave
def test_a_resumed_run_continues_in_the_stage_it_reached(tmp_path: Path) -> None:
    """Without the stage index a resume would repeat the whole frequency ladder from the
    bottom, which is worse than not resuming at all."""
    survey = _survey(tmp_path)
    spec = _spec(
        _physics(
            survey["paths"],
            stages=[
                {
                    "corner_frequency": {"value": 8.0, "quantity_type": "frequency", "unit": "Hz"},
                    "iterations": 2,
                },
                {"iterations": 2},
            ],
        )
    )
    context = PluginContext(tmp_path / "artifacts")
    plugin = DeepwaveElasticFwiPlugin()

    plugin.execute(context, spec)
    checkpoint = context.resume_from(spec)
    assert checkpoint is not None
    assert checkpoint.state["stage"] == 1
    assert checkpoint.iteration == 2

    plugin.execute(context, spec)

    events = (
        (tmp_path / "artifacts" / str(spec.run_id) / "progress.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    import json

    resumed = [
        json.loads(line) for line in events if "resumed" in (json.loads(line).get("message") or "")
    ]
    assert resumed, "the second run did not report resuming"
    assert resumed[0]["stage"] == "stage-2"


@needs_deepwave
def test_the_wavelet_is_published_whether_or_not_it_was_inverted(tmp_path: Path) -> None:
    """A result read a year later must say what source it assumed."""
    survey = _survey(tmp_path)
    spec = _spec(
        _physics(
            survey["paths"],
            stages=[{"iterations": 1}],
            wavelet={
                "peak_frequency": {"value": PEAK_HZ, "quantity_type": "frequency", "unit": "Hz"},
                "inverted": False,
            },
        )
    )
    context = PluginContext(tmp_path / "artifacts")

    result = DeepwaveElasticFwiPlugin().execute(context, spec)

    assert result.summary["wavelet_inverted"] is False
    assert "source_wavelet" in {item.artifact_type for item in result.artifacts}


@needs_deepwave
def test_an_inverted_wavelet_actually_changes(tmp_path: Path) -> None:
    """Getting the source wrong on field data is fitted by a wrong model, so solving for it
    has to really solve for it."""
    survey = _survey(tmp_path)
    spec = _spec(
        _physics(
            survey["paths"],
            stages=[{"iterations": 3}],
            wavelet={
                "peak_frequency": {"value": PEAK_HZ, "quantity_type": "frequency", "unit": "Hz"},
                "inverted": True,
            },
            invert_vp=False,
            invert_vs=False,
        )
    )
    context = PluginContext(tmp_path / "artifacts")

    result = DeepwaveElasticFwiPlugin().execute(context, spec)

    assert result.summary["wavelet_inverted"] is True
    from deepwave.wavelets import ricker

    started = ricker(PEAK_HZ, SAMPLES, TIME_STEP_S, 1.3 / PEAK_HZ).numpy()
    recovered = np.load(
        tmp_path / "artifacts" / str(spec.run_id) / "source_wavelet.npy", allow_pickle=False
    )
    assert not np.allclose(recovered, started), "the wavelet was declared inverted but never moved"


@needs_deepwave
def test_a_time_step_that_would_diverge_is_refused_before_the_run_starts(tmp_path: Path) -> None:
    """The Courant limit is cheap to check and expensive to discover."""
    survey = _survey(tmp_path)
    physics = _physics(survey["paths"])
    physics["geometry"]["time_step"] = {"value": 0.01, "quantity_type": "time", "unit": "s"}

    report = DeepwaveElasticFwiPlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(physics)
    )

    assert not report.valid
    assert any("Courant" in issue.message for issue in report.issues)


@needs_deepwave
def test_a_grid_too_coarse_for_its_highest_frequency_is_refused(tmp_path: Path) -> None:
    """Below about five cells per shear wavelength the wavefield is numerical dispersion
    rather than physics."""
    survey = _survey(tmp_path)
    physics = _physics(survey["paths"])
    physics["stages"] = [
        {
            "corner_frequency": {"value": 60.0, "quantity_type": "frequency", "unit": "Hz"},
            "iterations": 1,
        }
    ]

    report = DeepwaveElasticFwiPlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(physics)
    )

    assert not report.valid
    assert any("dispersion" in issue.message for issue in report.issues)


@needs_deepwave
def test_a_core_mesh_is_rejected_because_the_plugin_owns_its_grid(tmp_path: Path) -> None:
    from ofag.core.schemas import QuantitySpec, TensorMeshSpec

    survey = _survey(tmp_path)
    spec = _spec(_physics(survey["paths"])).model_copy(
        update={
            "mesh": TensorMeshSpec(
                cell_size=QuantitySpec(value=5.0, quantity_type=QuantityType.LENGTH, unit="m"),
                shape=(NZ, NX),
                origin=(0.0, 0.0),
            )
        }
    )

    report = DeepwaveElasticFwiPlugin().validate(PluginContext(tmp_path / "artifacts"), spec)

    assert not report.valid
    assert any(issue.field == "mesh" for issue in report.issues)


def test_a_configuration_that_inverts_for_nothing_is_refused() -> None:
    from pydantic import ValidationError

    from ofag.plugins.deepwave_fwi import ElasticFwiSpec

    with pytest.raises(ValidationError, match="nothing is being inverted"):
        ElasticFwiSpec.model_validate(
            {
                "grid": {
                    "shape": [NZ, NX],
                    "cell_size": {"value": 5.0, "quantity_type": "length", "unit": "m"},
                },
                "geometry": {
                    "sources_path": "a",
                    "receivers_path": "b",
                    "observations_path": "c",
                    "time_step": {"value": 0.001, "quantity_type": "time", "unit": "s"},
                },
                "wavelet": {
                    "peak_frequency": {"value": 10.0, "quantity_type": "frequency", "unit": "Hz"}
                },
                "stages": [{"iterations": 1}],
                "initial_vp_path": "d",
                "initial_vs_path": "e",
                "density_path": "f",
                "invert_vp": False,
                "invert_vs": False,
                "invert_density": False,
            }
        )


def test_the_manifest_says_what_this_engine_cannot_do() -> None:
    """A 2D acoustic-era limitation list is what stops it being used for a 3D land survey by
    somebody who did not read the engine document."""
    manifest = DeepwaveElasticFwiPlugin().manifest()

    assert manifest.supports_restart is True
    joined = " ".join(manifest.limitations)
    assert "2D elastic only" in joined
    assert "attenuation" in joined
    assert "anisotropy" in joined


@needs_deepwave
def test_data_that_no_longer_matches_the_digest_is_refused_before_the_run(
    tmp_path: Path,
) -> None:
    """A run's record has to say which data it fitted, not which path it read."""
    import hashlib

    paths = _survey(tmp_path)["paths"]
    observations = np.load(paths["observations"], allow_pickle=False)
    digest = hashlib.sha256(np.ascontiguousarray(observations).tobytes()).hexdigest()
    plugin = DeepwaveElasticFwiPlugin()

    context = PluginContext(tmp_path / "artifacts")
    pinned = _spec(
        _physics(paths, geometry=_physics(paths)["geometry"] | {"observations_sha256": digest})
    )

    matched = plugin.validate(context, pinned)
    assert matched.valid, matched.issues

    np.save(paths["observations"], observations * 2.0)
    stale = plugin.validate(context, pinned)

    assert not stale.valid
    assert any("re-prepared or overwritten" in issue.message for issue in stale.issues)


@needs_deepwave
def test_a_run_assembled_without_a_digest_is_still_allowed(tmp_path: Path) -> None:
    """Not every run comes from the preparation step; the pin is optional."""
    paths = _survey(tmp_path)["paths"]

    report = DeepwaveElasticFwiPlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(_physics(paths))
    )

    assert report.valid, report.issues


@needs_deepwave
def test_the_torch_preprocessing_matches_the_numpy_one_it_mirrors() -> None:
    """One declared sequence, two executions, which is a drift risk worth a test."""
    import torch

    from ofag.core.schemas import QuantitySpec
    from ofag.services.seismic_preprocess import (
        BandpassSpec,
        MuteSpec,
        SeismicPreprocessingSpec,
        apply_preprocessing,
    )

    rng = np.random.default_rng(11)
    gathers = rng.normal(0.0, 1.0, (2, 5, 256))
    gathers[0, 3] = 0.0  # a dead trace, which the RMS step must not divide by
    offsets = np.tile(np.arange(5) * 120.0 + 60.0, (2, 1))
    step = 0.002
    spec = SeismicPreprocessingSpec(
        remove_mean=True,
        bandpass=BandpassSpec(
            high_pass=QuantitySpec(value=4.0, quantity_type=QuantityType.FREQUENCY, unit="Hz"),
            low_pass=QuantitySpec(value=30.0, quantity_type=QuantityType.FREQUENCY, unit="Hz"),
        ),
        top_mute=MuteSpec(
            velocity=QuantitySpec(
                value=800.0, quantity_type=QuantityType.P_WAVE_VELOCITY, unit="m/s"
            ),
            delay=QuantitySpec(value=0.01, quantity_type=QuantityType.TIME, unit="s"),
            taper=QuantitySpec(value=0.02, quantity_type=QuantityType.TIME, unit="s"),
        ),
        time_gain_power=1.5,
        trace_normalisation="rms",
    )

    expected, _ = apply_preprocessing(gathers, offsets, step, spec)
    plugin = DeepwaveElasticFwiPlugin()
    constants = plugin._preprocessing_constants(spec, gathers.shape, offsets, step)
    actual = plugin._preprocessed(torch.tensor(gathers, dtype=torch.float64), spec, constants)

    assert np.allclose(actual.detach().numpy(), expected, atol=1e-12)


@needs_deepwave
def test_the_gradient_survives_the_preprocessing_it_is_measured_through() -> None:
    """It runs inside the graph, so a numpy step here would silently detach."""
    import torch

    from ofag.services.seismic_preprocess import SeismicPreprocessingSpec

    spec = SeismicPreprocessingSpec(remove_mean=True, trace_normalisation="rms")
    data = torch.tensor(np.random.default_rng(3).normal(0.0, 1.0, (1, 4, 64)), dtype=torch.float64)
    data.requires_grad_(True)
    plugin = DeepwaveElasticFwiPlugin()

    processed = plugin._preprocessed(
        data, spec, plugin._preprocessing_constants(spec, data.shape, np.zeros((1, 4)), 0.002)
    )
    (processed**2).sum().backward()

    assert data.grad is not None
    assert torch.isfinite(data.grad).all()
    assert float(data.grad.abs().sum()) > 0.0


@needs_deepwave
def test_the_solve_is_held_to_the_grid_limits_it_had_to_start_within(
    tmp_path: Path,
) -> None:
    """The validator judges the starting model; the inversion moves it."""
    paths = _survey(tmp_path)["paths"]
    config = ElasticFwiSpec.model_validate(_physics(paths))

    bounds = DeepwaveElasticFwiPlugin()._bounds(config)

    # The same number the validator judged the starting model by, through the one helper
    # they share.
    highest = _highest_frequency(config)
    assert bounds["vs_low"] == pytest.approx(MINIMUM_CELLS_PER_WAVELENGTH * SPACING_M * highest)
    assert bounds["vp_high"] == pytest.approx(MAXIMUM_COURANT * SPACING_M / TIME_STEP_S)
    # vp can never be allowed under sqrt(2) vs, or the medium is a fluid and the free
    # surface is unstable.
    assert bounds["vp_low"] >= bounds["vs_low"] * MINIMUM_VP_OVER_VS


@needs_deepwave
def test_a_stated_bound_narrows_the_grid_limits_and_never_widens_them(
    tmp_path: Path,
) -> None:
    """What the rocks can be is knowledge about the site; what the grid can represent is not
    negotiable."""
    paths = _survey(tmp_path)["paths"]
    plugin = DeepwaveElasticFwiPlugin()
    open_limits = plugin._bounds(ElasticFwiSpec.model_validate(_physics(paths)))

    narrowed = plugin._bounds(
        ElasticFwiSpec.model_validate(
            _physics(
                paths,
                vs_bounds={
                    "minimum": {
                        "value": open_limits["vs_low"] + 100.0,
                        "quantity_type": "s_wave_velocity",
                        "unit": "m/s",
                    },
                    "maximum": {
                        "value": 900.0,
                        "quantity_type": "s_wave_velocity",
                        "unit": "m/s",
                    },
                },
            )
        )
    )
    widened = plugin._bounds(
        ElasticFwiSpec.model_validate(
            _physics(
                paths,
                vs_bounds={
                    "minimum": {"value": 1.0, "quantity_type": "s_wave_velocity", "unit": "m/s"},
                    "maximum": {
                        "value": 99_000.0,
                        "quantity_type": "s_wave_velocity",
                        "unit": "m/s",
                    },
                },
            )
        )
    )

    assert narrowed["vs_low"] == pytest.approx(open_limits["vs_low"] + 100.0)
    assert narrowed["vs_high"] == pytest.approx(900.0)
    assert widened["vs_low"] == pytest.approx(open_limits["vs_low"])
    assert widened["vs_high"] == pytest.approx(open_limits["vs_high"])


@needs_deepwave
def test_bounds_the_wrong_way_round_are_refused() -> None:
    from pydantic import ValidationError

    from ofag.core.schemas import QuantitySpec
    from ofag.plugins.deepwave_fwi import VelocityBoundsSpec

    with pytest.raises(ValidationError, match="at or above the maximum"):
        VelocityBoundsSpec(
            minimum=QuantitySpec(
                value=900.0, quantity_type=QuantityType.S_WAVE_VELOCITY, unit="m/s"
            ),
            maximum=QuantitySpec(
                value=300.0, quantity_type=QuantityType.S_WAVE_VELOCITY, unit="m/s"
            ),
        )


@needs_deepwave
def test_a_stage_can_be_measured_by_its_own_misfit(tmp_path: Path) -> None:
    """Envelope down the ladder, L2 at the top, which is the usual sequence."""
    survey = _survey(tmp_path)
    events: list[RunEvent] = []
    context = PluginContext(tmp_path / "artifacts", emit=events.append)
    spec = _spec(
        _physics(
            survey["paths"],
            misfit="envelope",
            stages=[
                {
                    "corner_frequency": {
                        "value": 8.0,
                        "quantity_type": "frequency",
                        "unit": "Hz",
                    },
                    "iterations": 2,
                },
                {"iterations": 2, "misfit": "l2"},
            ],
        )
    )

    result = DeepwaveElasticFwiPlugin().execute(context, spec)

    measured = {
        event.stage: set(event.misfits) for event in events if event.event_type == "iteration"
    }
    assert measured["stage-1"] == {"envelope"}
    assert measured["stage-2"] == {"l2"}
    assert result.summary["misfit"] == "envelope, l2"


@needs_deepwave
def test_each_stage_is_normalised_by_its_own_functional(tmp_path: Path) -> None:
    """Otherwise the reported misfit jumps between stages for no reason."""
    import torch

    survey = _survey(tmp_path)
    events: list[RunEvent] = []
    context = PluginContext(tmp_path / "artifacts", emit=events.append)
    spec = _spec(
        _physics(
            survey["paths"],
            misfit="l2",
            stages=[{"iterations": 1, "misfit": "envelope"}, {"iterations": 1, "misfit": "l2"}],
        )
    )

    DeepwaveElasticFwiPlugin().execute(context, spec)

    first, second = (event.phi_data for event in events if event.event_type == "iteration")
    assert first is not None and second is not None

    # The baseline is the misfit of a zero prediction, and the two functionals do not
    # give the same one: L2 measures the data's own energy, the envelope measures its
    # analytic signal's, which for a narrowband trace is twice as much.
    observed = torch.tensor(
        np.load(survey["paths"]["observations"], allow_pickle=False), dtype=torch.float64
    )
    plugin = DeepwaveElasticFwiPlugin()
    baselines = {
        kind: float(plugin._misfit(torch.zeros_like(observed), observed, kind))
        for kind in ("envelope", "l2")
    }
    assert baselines["envelope"] / baselines["l2"] == pytest.approx(2.0, rel=0.05)
    # And both are around 1e-12, which is why the normalisation is there at all.
    assert max(baselines.values()) < 1e-6

    # Both reported values are relative numbers of order one, so neither carries a raw
    # misfit or a baseline from the other stage.
    for value in (first, second):
        assert 0.0 < value < 5.0


@needs_deepwave
def test_the_probe_says_which_parameter_the_data_can_see(tmp_path: Path) -> None:
    """The question the other pre-run checks do not ask."""
    paths = _survey(tmp_path)["paths"]
    plugin = DeepwaveElasticFwiPlugin()

    probe = plugin.parameter_sensitivity(
        PluginContext(tmp_path / "artifacts"), _spec(_physics(paths))
    )

    assert set(probe.sensitivity) == {"vp", "vs", "density"}
    assert probe.inverted == ("vp", "vs")
    assert all(value > 0.0 for value in probe.sensitivity.values())
    # Ratios against the most sensitive, which is the only comparison the numbers
    # support: they are in the misfit's own units.
    ratios = probe.ratios()
    assert max(ratios.values()) == pytest.approx(1.0)
    assert all(0.0 <= value <= 1.0 for value in ratios.values())


@needs_deepwave
def test_muting_the_ground_roll_is_visible_in_the_shear_sensitivity(
    tmp_path: Path,
) -> None:
    """The measurement that settled the Soda Lake shear question, in miniature."""
    paths = _survey(tmp_path)["paths"]
    plugin = DeepwaveElasticFwiPlugin()
    context = PluginContext(tmp_path / "artifacts")

    whole = plugin.parameter_sensitivity(context, _spec(_physics(paths)))
    muted = plugin.parameter_sensitivity(
        context,
        _spec(
            _physics(
                paths,
                observed_preprocessing={
                    "bottom_mute": {
                        "velocity": {
                            "value": 1200.0,
                            "quantity_type": "p_wave_velocity",
                            "unit": "m/s",
                        },
                        "delay": {"value": 0.02, "quantity_type": "time", "unit": "s"},
                        "taper": {"value": 0.01, "quantity_type": "time", "unit": "s"},
                    }
                },
            )
        ),
    )

    # Against Vp rather than against whichever is largest: this fixture is surface-wave
    # dominated by construction, so Vs is the maximum either way and a ratio to the
    # maximum is 1.0 in both.
    assert whole.sensitivity["vs"] / whole.sensitivity["vp"] > 3.0
    assert muted.sensitivity["vs"] / muted.sensitivity["vp"] < 1.0


@needs_deepwave
def test_a_plugin_that_cannot_answer_is_refused_rather_than_guessed_for(
    tmp_path: Path,
) -> None:
    """A number that did not come from the method's own adjoint is a guess."""
    from ofag.plugins.protocol import SensitivityCapable
    from ofag.plugins.registry import PluginRegistry
    from ofag.plugins.synthetic_gravity import SyntheticGravityPlugin

    assert isinstance(DeepwaveElasticFwiPlugin(), SensitivityCapable)
    assert not isinstance(SyntheticGravityPlugin(), SensitivityCapable)

    registry = PluginRegistry()
    registry.register(SyntheticGravityPlugin())
    service = RunService(artifact_root=tmp_path / "artifacts", registry=registry)
    spec = _spec(_physics(_survey(tmp_path)["paths"]))
    spec = spec.model_copy(update={"plugin_id": SyntheticGravityPlugin().plugin_id})

    with pytest.raises(ValueError, match="cannot report what its data sees"):
        service.parameter_sensitivity(spec)


@needs_deepwave
def test_the_result_says_how_much_data_produced_it(tmp_path: Path) -> None:
    """A section cannot be judged without knowing what it was fitted to."""
    survey = _survey(tmp_path)
    observed = np.load(survey["paths"]["observations"], allow_pickle=False)
    context = PluginContext(tmp_path / "artifacts")

    result = DeepwaveElasticFwiPlugin().execute(
        context,
        _spec(_physics(survey["paths"], stages=[{"iterations": 1}])),
    )

    assert result.summary["shots"] == observed.shape[0]
    assert result.summary["channels"] == observed.shape[1]
    assert result.summary["samples"] == observed.shape[2]
    assert result.summary["observations_sha256"] == "not pinned"
