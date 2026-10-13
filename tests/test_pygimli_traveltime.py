"""The refraction tomography plugin."""

from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DataChannelSpec,
    DatasetSpec,
    QuantitySpec,
    RunSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.pygimli_traveltime import PyGIMLiTravelTimePlugin, TravelTimeInversionSpec

_SENSORS = 16
_SPACING = 4.0
_TOP_VELOCITY = 600.0
_BOTTOM_VELOCITY = 2500.0
_INTERFACE_DEPTH = 6.0

#: How far the recovered shallow velocity may sit from the true 600 m/s.
_TOP_WINDOW = (400.0, 1400.0)


def _sensors() -> np.ndarray:
    return np.column_stack([np.arange(_SENSORS) * _SPACING, np.zeros(_SENSORS), np.zeros(_SENSORS)])


def _pairs() -> np.ndarray:
    """Two end shots into the whole spread, each skipping its own position."""
    rows = []
    for shot in (0, _SENSORS - 1):
        rows += [[shot, g] for g in range(_SENSORS) if g != shot]
    return np.asarray(rows, dtype=np.int64)


def _simulate(sensors: np.ndarray, pairs: np.ndarray) -> np.ndarray:
    import pygimli as pg
    import pygimli.physics.traveltime as tt

    span = float(sensors[:, 0].max())
    world = pg.meshtools.createWorld(
        start=[-span * 0.3, 0.0], end=[span * 1.3, -span * 0.6], layers=[-_INTERFACE_DEPTH]
    )
    mesh = pg.meshtools.createMesh(world, quality=33.0, area=span / 8.0)
    # An array, not a list: `simulate` takes the reciprocal of whatever it is given, and
    # a list has no reciprocal.
    velocity = np.asarray(
        [_TOP_VELOCITY if int(marker) == 1 else _BOTTOM_VELOCITY for marker in mesh.cellMarkers()],
        dtype=float,
    )
    scheme = pg.DataContainer()
    for x, _, z in sensors:
        scheme.createSensor([float(x), float(z)])
    scheme.registerSensorIndex("s")
    scheme.registerSensorIndex("g")
    scheme.resize(len(pairs))
    scheme["s"] = pairs[:, 0].tolist()
    scheme["g"] = pairs[:, 1].tolist()
    data = tt.simulate(mesh, scheme=scheme, vel=velocity, secNodes=3, noiseLevel=0.0, verbose=False)
    return np.asarray(data["t"], dtype=float)


def _write(tmp_path: Path, sensors: np.ndarray, pairs: np.ndarray, times: np.ndarray) -> dict:
    np.save(tmp_path / "sensors.npy", sensors)
    np.save(tmp_path / "pairs.npy", pairs)
    path = tmp_path / "t.csv"
    path.write_text(
        "traveltime_s\n" + "\n".join(f"{v:.10e}" for v in times) + "\n", encoding="utf-8"
    )
    return {
        "sensors_path": str(tmp_path / "sensors.npy"),
        "shot_receiver_path": str(tmp_path / "pairs.npy"),
        "observations_path": str(path),
    }


def _quantity(value: float, quantity: QuantityType, unit: str) -> dict:
    return QuantitySpec(value=value, quantity_type=quantity, unit=unit).model_dump(mode="json")


def _spec(paths: dict, physics: dict, *, error_s: float = 1.0e-3) -> RunSpec:
    dataset = DatasetSpec(
        name="synthetic",
        coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
        physical_quantity=QuantityType.TRAVELTIME,
        units="s",
    )
    uncertainty = QuantitySpec(value=error_s, quantity_type=QuantityType.TRAVELTIME, unit="s")
    return RunSpec(
        plugin_id="pygimli.seismic.traveltime",
        plugin_version="0.1.0",
        engine="pygimli",
        project_id=uuid4(),
        label="synthetic refraction",
        dataset=dataset,
        datasets=(
            DataChannelSpec(
                channel_id="traveltime",
                dataset=dataset,
                observations_path=paths["observations_path"],
                data_uncertainty=uncertainty,
            ),
        ),
        physics={
            "array": {
                "sensors_path": paths["sensors_path"],
                "shot_receiver_path": paths["shot_receiver_path"],
            },
            **physics,
        },
    )


def _base_physics() -> dict:
    return {
        "mesh": {
            "dimension": 2,
            "depth": _quantity(20.0, QuantityType.LENGTH, "m"),
            "secondary_nodes": 3,
        },
        "regularization": {
            "lam": 20.0,
            "lower_velocity": _quantity(200.0, QuantityType.P_WAVE_VELOCITY, "m/s"),
            "upper_velocity": _quantity(6000.0, QuantityType.P_WAVE_VELOCITY, "m/s"),
        },
        "starting_model": {
            "use_gradient": True,
            "top_velocity": _quantity(500.0, QuantityType.P_WAVE_VELOCITY, "m/s"),
            "bottom_velocity": _quantity(3000.0, QuantityType.P_WAVE_VELOCITY, "m/s"),
        },
        "optimizer": {"max_iterations": 8},
    }


def test_a_two_layer_earth_is_recovered_and_the_run_reports_its_reach(tmp_path) -> None:
    """The section comes back faster with depth, and says how much of it rays lit."""
    pytest.importorskip("pygimli")
    sensors, pairs = _sensors(), _pairs()
    paths = _write(tmp_path, sensors, pairs, _simulate(sensors, pairs))
    result = PyGIMLiTravelTimePlugin().execute(
        PluginContext(tmp_path / "artifacts"), _spec(paths, _base_physics())
    )

    assert result.summary["chi_squared"] < result.summary["chi_squared_initial"]
    assert result.summary["picks"] == len(pairs)
    # A refraction mesh is far larger than the rays crossing it, and reporting a
    # velocity for every cell without saying which were reached is the whole trap this
    # number exists for.
    assert 0 < result.summary["cells_touched_by_a_ray"] < result.summary["model_cells"]
    assert result.summary["cells_touched_share"] == pytest.approx(
        result.summary["cells_touched_by_a_ray"] / result.summary["model_cells"]
    )

    root = tmp_path / "artifacts" / str(result.run_id)
    velocity = np.load(root / "recovered_model.npy")
    geometry = np.load(root / "mesh_geometry.npz")
    touched = np.load(root / "cells_touched_by_a_ray.npy")
    depth = -geometry["cell_centers_m"][:, 1]
    shallow = touched.astype(bool) & (depth < _INTERFACE_DEPTH)
    deep = touched.astype(bool) & (depth > _INTERFACE_DEPTH)
    assert np.median(velocity[deep]) > np.median(velocity[shallow])
    assert _TOP_WINDOW[0] < np.median(velocity[shallow]) < _TOP_WINDOW[1]


def test_every_artifact_path_resolves_against_the_artifact_root(tmp_path) -> None:
    """A bare filename would resolve to the root and find another run's file."""
    pytest.importorskip("pygimli")
    sensors, pairs = _sensors(), _pairs()
    paths = _write(tmp_path, sensors, pairs, _simulate(sensors, pairs))
    root = tmp_path / "artifacts"
    result = PyGIMLiTravelTimePlugin().execute(PluginContext(root), _spec(paths, _base_physics()))

    for artifact in result.artifacts:
        assert artifact.relative_path.startswith(f"{result.run_id}/")
        assert (root / artifact.relative_path).is_file()


def test_a_velocity_bound_below_one_is_refused_as_a_hidden_slowness() -> None:
    """pyGIMLi reads bounds as slowness unless the lower one exceeds 1."""
    physics = _base_physics()
    physics["regularization"]["lower_velocity"] = _quantity(
        0.5, QuantityType.P_WAVE_VELOCITY, "m/s"
    )

    with pytest.raises(ValueError, match="silently inverted as a slowness"):
        TravelTimeInversionSpec.model_validate(
            {"array": {"sensors_path": "a.npy", "shot_receiver_path": "b.npy"}, **physics}
        )


def test_zero_offset_picks_are_dropped_and_counted(tmp_path) -> None:
    """A pick whose shot and receiver are one sensor has no path."""
    pytest.importorskip("pygimli")
    sensors = _sensors()
    pairs = np.vstack([_pairs(), [[0, 0], [3, 3]]])
    times = np.concatenate([_simulate(sensors, _pairs()), [0.010, 0.010]])
    paths = _write(tmp_path, sensors, pairs, times)
    physics = _base_physics()
    physics["quality"] = {"drop_zero_offset": True}
    result = PyGIMLiTravelTimePlugin().execute(
        PluginContext(tmp_path / "artifacts"), _spec(paths, physics)
    )

    assert result.summary["picks_removed"] == 2
    assert result.summary["picks"] == len(_pairs())
    assert result.summary["quality_filtered"] is True


def test_an_impossibly_slow_pick_is_dropped(tmp_path) -> None:
    """Nothing in the ground carries a P wave at 120 m/s, whatever the site."""
    pytest.importorskip("pygimli")
    sensors, pairs = _sensors(), _pairs()
    times = _simulate(sensors, pairs)
    times[3] = 0.100  # 12 m in 100 ms is 120 m/s
    paths = _write(tmp_path, sensors, pairs, times)
    physics = _base_physics()
    physics["quality"] = {
        "minimum_apparent_velocity": _quantity(200.0, QuantityType.P_WAVE_VELOCITY, "m/s")
    }
    result = PyGIMLiTravelTimePlugin().execute(
        PluginContext(tmp_path / "artifacts"), _spec(paths, physics)
    )

    assert result.summary["picks_removed"] == 1


def test_a_relative_uncertainty_is_refused_at_the_boundary(tmp_path) -> None:
    """pyGIMLi reads `err` as absolute seconds; a relative error is a thousandfold."""
    dataset = DatasetSpec(
        name="synthetic",
        coordinate_convention=CoordinateConvention(crs="EPSG:26914"),
        physical_quantity=QuantityType.TRAVELTIME,
        units="s",
    )

    with pytest.raises(ValueError, match="dimensionless uncertainty"):
        DataChannelSpec(
            channel_id="traveltime",
            dataset=dataset,
            observations_path=str(tmp_path / "t.csv"),
            data_uncertainty=QuantitySpec(
                value=0.03, quantity_type=QuantityType.DIMENSIONLESS, unit="dimensionless"
            ),
        )


def test_validation_catches_a_one_based_sensor_index(tmp_path) -> None:
    """Every field format numbers traces from 1 and this one does not."""
    sensors, pairs = _sensors(), _pairs() + 1
    paths = _write(tmp_path, sensors, pairs, np.full(len(pairs), 0.02))
    report = PyGIMLiTravelTimePlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(paths, _base_physics())
    )

    assert not report.valid
    assert any("0-based" in issue.remediation for issue in report.issues)


def test_validation_catches_a_traveltime_count_that_is_not_the_pick_count(tmp_path) -> None:
    sensors, pairs = _sensors(), _pairs()
    paths = _write(tmp_path, sensors, pairs, np.full(len(pairs) - 3, 0.02))
    report = PyGIMLiTravelTimePlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(paths, _base_physics())
    )

    assert not report.valid
    assert any("one traveltime per shot-receiver pair" in i.remediation for i in report.issues)


def test_validation_catches_a_non_positive_traveltime(tmp_path) -> None:
    sensors, pairs = _sensors(), _pairs()
    times = np.full(len(pairs), 0.02)
    times[0] = 0.0
    paths = _write(tmp_path, sensors, pairs, times)
    report = PyGIMLiTravelTimePlugin().validate(
        PluginContext(tmp_path / "artifacts"), _spec(paths, _base_physics())
    )

    assert not report.valid
    assert any("zero-offset" in issue.remediation for issue in report.issues)


def test_the_plugin_declares_its_conventions_rather_than_asserting_them() -> None:
    checks = PyGIMLiTravelTimePlugin().conventions()

    assert len(checks) == 2
    for check in checks:
        assert check.catches and check.against
