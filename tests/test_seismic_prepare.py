"""Turning a SEG-Y line into what a 2D elastic inversion consumes."""

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ofag.api.app import create_app
from ofag.services.run_service import RunService

needs_segyio = pytest.mark.skipif(
    find_spec("segyio") is None, reason="the seismic extra is not installed"
)

CONVENTION = {"crs": "EPSG:28351"}
SAMPLES = 128


def _line(
    path: Path,
    *,
    shots: int = 6,
    receivers: int = 20,
    rolling: bool = False,
    offline_m: float = 0.0,
    auxiliary_traces: int = 0,
    components: int = 1,
    interleaved: bool = False,
    first_shot: int = 0,
    parallel_line_offset_m: float | None = None,
    source_offline_m: float = 0.0,
) -> Path:
    """A land line, optionally crooked, rolling, 3C, or led by aux channels."""
    import segyio

    spec = segyio.spec()
    spec.format = 5
    spec.samples = list(range(SAMPLES))
    lines = 1 if parallel_line_offset_m is None else 2
    spec.tracecount = shots * receivers * components * lines + auxiliary_traces
    rng = np.random.default_rng(0)

    with segyio.create(str(path), spec) as handle:
        handle.bin[segyio.BinField.Interval] = 2000
        index = 0
        for _ in range(auxiliary_traces):
            handle.header[index] = {
                segyio.TraceField.SourceGroupScalar: 1,
                segyio.TraceField.TraceIdentificationCode: 6,
                segyio.TraceField.TRACE_SEQUENCE_LINE: index + 1,
            }
            handle.trace[index] = np.zeros(SAMPLES, dtype=np.float32)
            index += 1
        for shot in range(first_shot, first_shot + shots):
            source_x = 400_000.0 + shot * 40.0
            pairs = (
                [(channel, part) for channel in range(receivers) for part in range(components)]
                if interleaved
                else [(channel, part) for part in range(components) for channel in range(receivers)]
            )
            for channel, part in pairs:
                first = shot * 10.0 if rolling else 0.0
                receiver_x = 400_000.0 + first + channel * 10.0
                for line in range(lines):
                    aside = 0.0 if line == 0 else float(parallel_line_offset_m or 0.0)
                    handle.header[index] = {
                        segyio.TraceField.SourceX: int(source_x),
                        segyio.TraceField.SourceY: int(7_500_000.0 + source_offline_m),
                        segyio.TraceField.GroupX: int(receiver_x),
                        segyio.TraceField.GroupY: int(
                            7_500_000.0 + aside + (offline_m if channel % 2 else 0.0)
                        ),
                        segyio.TraceField.SourceGroupScalar: 1,
                        segyio.TraceField.TRACE_SEQUENCE_LINE: index + 1,
                    }
                    # A distinct amplitude per trace, so a wrongly selected one shows up
                    # as the wrong number rather than as plausible noise.
                    handle.trace[index] = np.full(
                        SAMPLES,
                        float(shot * 1000 + channel + part * 100_000 + line * 10_000_000),
                        dtype=np.float32,
                    ) + rng.normal(0, 1e-3, SAMPLES).astype(np.float32)
                    index += 1
    return path


def _extract(path: Path, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "source_path": str(path),
        "name": "Line 1",
        "coordinate_convention": CONVENTION,
        "coordinate_unit": "m",
    }
    payload.update(overrides)
    return payload


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))


@needs_segyio
def test_a_selection_writes_the_three_arrays_a_run_consumes(tmp_path: Path) -> None:
    path = _line(tmp_path / "line.sgy")

    response = _client(tmp_path).post(
        "/datasets/segy/extract",
        json=_extract(path, max_shots=3, receiver_stride=2, sample_count=64),
    )

    assert response.status_code == 200, response.text
    prepared = response.json()
    assert prepared["shot_count"] == 3
    assert prepared["shots_available"] == 6
    assert prepared["receiver_count"] == 10
    assert prepared["channels_available"] == 20
    assert prepared["sample_count"] == 64
    assert prepared["samples_available"] == SAMPLES
    assert prepared["line_length_m"] == pytest.approx(180.0)

    observations = np.load(prepared["observations_path"], allow_pickle=False)
    assert observations.shape == (3, 10, 64)
    sources = np.load(prepared["sources_path"], allow_pickle=False)
    receivers = np.load(prepared["receivers_path"], allow_pickle=False)
    assert sources.shape == (3, 2)
    assert receivers.shape == (10, 2)
    # Distances are measured along the line from its own start, which is what a
    # section's x axis is, rather than raw eastings of four hundred thousand.
    assert receivers[:, 0].min() == pytest.approx(0.0)
    assert receivers[:, 0].max() == pytest.approx(180.0)


@needs_segyio
def test_shots_are_selected_along_the_line_not_by_file_order(tmp_path: Path) -> None:
    """A shot number is not a position, and a stride should walk the line."""
    path = _line(tmp_path / "line.sgy", shots=6)

    prepared = (
        _client(tmp_path)
        .post("/datasets/segy/extract", json=_extract(path, shot_stride=2, max_shots=3))
        .json()
    )

    sources = np.load(prepared["sources_path"], allow_pickle=False)
    # Shots sit every 40 m; every second one is every 80 m.
    assert np.diff(sources[:, 0]) == pytest.approx([80.0, 80.0])


@needs_segyio
def test_a_rolling_spread_is_reduced_to_the_ground_every_shot_recorded(
    tmp_path: Path,
) -> None:
    """Not interpolated onto a common spread, which would invent channels."""
    path = _line(tmp_path / "rolling.sgy", rolling=True, shots=6, receivers=20)

    prepared = (
        _client(tmp_path).post("/datasets/segy/extract", json=_extract(path, max_shots=3)).json()
    )

    # Shots step 40 m and the spread rolls 10 m a shot, over 20 stations at 10 m: three
    # shots share the 190 m from 20 m to 210 m.
    assert prepared["channels_available"] == 20
    assert prepared["channels_shared"] == 18
    assert prepared["receiver_count"] == 18
    assert prepared["line_length_m"] == pytest.approx(170.0)


@needs_segyio
def test_shots_with_no_ground_in_common_are_refused(tmp_path: Path) -> None:
    """A spread that rolls clear of itself leaves nothing to invert on."""
    path = _line(tmp_path / "rolling.sgy", rolling=True, shots=30, receivers=8)

    response = _client(tmp_path).post("/datasets/segy/extract", json=_extract(path, max_shots=30))

    assert response.status_code == 422
    assert "no spread they all recorded" in response.json()["detail"]


@needs_segyio
def test_how_far_the_line_strays_from_straight_is_reported(tmp_path: Path) -> None:
    """A crooked line is a fact about the survey."""
    straight = _line(tmp_path / "straight.sgy")
    crooked = _line(tmp_path / "crooked.sgy", offline_m=12.0)
    client = _client(tmp_path)

    flat = client.post("/datasets/segy/extract", json=_extract(straight)).json()
    bent = client.post("/datasets/segy/extract", json=_extract(crooked)).json()

    assert flat["maximum_offline_deviation_m"] == pytest.approx(0.0, abs=0.5)
    assert bent["maximum_offline_deviation_m"] > 4.0


@needs_segyio
def test_a_window_past_the_end_of_the_record_is_refused(tmp_path: Path) -> None:
    path = _line(tmp_path / "line.sgy")

    response = _client(tmp_path).post(
        "/datasets/segy/extract", json=_extract(path, first_sample=100, sample_count=100)
    )

    assert response.status_code == 422
    assert "runs past" in response.json()["detail"]


def test_a_starting_model_is_stated_rather_than_derived(tmp_path: Path) -> None:
    """A model estimated from the arrivals it is meant to explain is circular."""
    response = _client(tmp_path).post(
        "/datasets/seismic/starting-model",
        json={
            "shape": [40, 90],
            "cell_size": {"value": 5.0, "quantity_type": "length", "unit": "m"},
            "surface_p_velocity": {
                "value": 1200.0,
                "quantity_type": "p_wave_velocity",
                "unit": "m/s",
            },
            "p_velocity_gradient_per_m": 4.0,
            "vp_over_vs": 2.0,
            "density": {"value": 1900.0, "quantity_type": "bulk_density", "unit": "kg/m^3"},
        },
    )

    assert response.status_code == 200, response.text
    model = response.json()
    assert model["p_velocity_min_m_s"] == pytest.approx(1200.0)
    # Thirty-nine cells of five metres below the top, at four metres per second per
    # metre.
    assert model["p_velocity_max_m_s"] == pytest.approx(1200.0 + 39 * 5.0 * 4.0)
    assert model["s_velocity_min_m_s"] == pytest.approx(600.0)

    vp = np.load(model["initial_vp_path"], allow_pickle=False)
    vs = np.load(model["initial_vs_path"], allow_pickle=False)
    assert vp.shape == (40, 90)
    # Constant along the line, increasing with depth: a gradient, not a guess at
    # structure.
    assert np.allclose(vp[:, 0], vp[:, -1])
    assert np.all(np.diff(vp[:, 0]) > 0)
    assert np.allclose(vp / vs, 2.0)


def test_a_poisson_ratio_below_zero_is_refused() -> None:
    """vp/vs under sqrt(2) is not ground, and the solver is unstable there."""
    from pydantic import ValidationError

    from ofag.services.seismic_prepare import StartingModelRequest

    with pytest.raises(ValidationError):
        StartingModelRequest.model_validate(
            {
                "shape": [40, 90],
                "cell_size": {"value": 5.0, "quantity_type": "length", "unit": "m"},
                "surface_p_velocity": {
                    "value": 1200.0,
                    "quantity_type": "p_wave_velocity",
                    "unit": "m/s",
                },
                "vp_over_vs": 1.2,
                "density": {"value": 1900.0, "quantity_type": "bulk_density", "unit": "kg/m^3"},
            }
        )


@needs_segyio
def test_the_prepared_arrays_validate_as_an_inversion(tmp_path: Path) -> None:
    """The point of the whole chain: a SEG-Y file becomes a runnable spec."""
    pytest.importorskip("deepwave")
    path = _line(tmp_path / "line.sgy", shots=4, receivers=16)
    client = _client(tmp_path)

    prepared = client.post(
        "/datasets/segy/extract",
        json=_extract(path, max_shots=2, sample_count=96, station_depth_m=5.0),
    ).json()
    model = client.post(
        "/datasets/seismic/starting-model",
        json={
            "shape": [40, 60],
            "cell_size": {"value": 5.0, "quantity_type": "length", "unit": "m"},
            "surface_p_velocity": {
                "value": 1400.0,
                "quantity_type": "p_wave_velocity",
                "unit": "m/s",
            },
            "p_velocity_gradient_per_m": 2.0,
            "density": {"value": 1900.0, "quantity_type": "bulk_density", "unit": "kg/m^3"},
        },
    ).json()

    spec = {
        "schema_version": "1.1",
        "plugin_id": "deepwave.fwi.elastic2d",
        "engine": "deepwave",
        "dataset": {
            "name": "line",
            "coordinate_convention": CONVENTION,
            "physical_quantity": "particle_velocity",
            "units": "m/s",
        },
        "physics": {
            "grid": {
                "shape": [40, 60],
                "cell_size": {"value": 5.0, "quantity_type": "length", "unit": "m"},
            },
            "geometry": {
                "sources_path": prepared["sources_path"],
                "receivers_path": prepared["receivers_path"],
                "observations_path": prepared["observations_path"],
                # Below the Courant limit for 5 m cells at these velocities; the
                # validator reports the ceiling when it is exceeded.
                "time_step": {"value": 0.001, "quantity_type": "time", "unit": "s"},
                "pml_cells": 15,
            },
            "wavelet": {
                "peak_frequency": {"value": 8.0, "quantity_type": "frequency", "unit": "Hz"}
            },
            "stages": [{"iterations": 1}],
            "initial_vp_path": model["initial_vp_path"],
            "initial_vs_path": model["initial_vs_path"],
            "density_path": model["density_path"],
        },
    }

    report = client.post("/runs/validate", json=spec)

    assert report.status_code == 200, report.text
    assert report.json()["valid"] is True, report.json()["issues"]


@needs_segyio
def test_an_auxiliary_trace_does_not_join_the_first_shot(tmp_path: Path) -> None:
    """It has no source position, so it belongs to no shot -- not to shot zero."""
    plain = _line(tmp_path / "plain.sgy")
    with_aux = _line(tmp_path / "aux.sgy", auxiliary_traces=3)
    client = _client(tmp_path)

    without = client.post("/datasets/segy/extract", json=_extract(plain)).json()
    withaux = client.post("/datasets/segy/extract", json=_extract(with_aux)).json()

    assert withaux["shot_count"] == without["shot_count"]
    assert withaux["receiver_count"] == without["receiver_count"]
    assert np.array_equal(
        np.load(withaux["observations_path"]), np.load(without["observations_path"])
    )


@needs_segyio
def test_the_line_direction_is_not_fitted_through_the_map_origin(tmp_path: Path) -> None:
    """The failure an aux trace causes that nothing downstream would show."""
    plain = _line(tmp_path / "plain.sgy")
    with_aux = _line(tmp_path / "aux.sgy", auxiliary_traces=1)
    client = _client(tmp_path)

    without = client.post("/datasets/segy/extract", json=_extract(plain)).json()
    withaux = client.post("/datasets/segy/extract", json=_extract(with_aux)).json()

    assert withaux["line_length_m"] == pytest.approx(without["line_length_m"])
    assert withaux["maximum_offline_deviation_m"] == pytest.approx(
        without["maximum_offline_deviation_m"]
    )
    assert np.allclose(np.load(withaux["receivers_path"]), np.load(without["receivers_path"]))


@needs_segyio
def test_an_undeclared_multicomponent_record_is_refused(tmp_path: Path) -> None:
    """Soda Lake is 3C, and nothing in a SEG-Y header says so."""
    path = _line(tmp_path / "3c.sgy", components=3)

    response = _client(tmp_path).post("/datasets/segy/extract", json=_extract(path, max_shots=2))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "multi-component" in detail
    assert "up to 3" in detail


@needs_segyio
def test_a_declared_component_is_taken_whichever_way_the_file_is_laid_out(
    tmp_path: Path,
) -> None:
    """Blocked and interleaved are both written, and neither is declarable."""
    blocked = _line(tmp_path / "blocked.sgy", components=3)
    interleaved = _line(tmp_path / "interleaved.sgy", components=3, interleaved=True)
    plain = _line(tmp_path / "plain.sgy")
    client = _client(tmp_path)

    selected = [
        client.post(
            "/datasets/segy/extract",
            json=_extract(path, max_shots=2, components=3, component_index=1),
        ).json()
        for path in (blocked, interleaved)
    ]
    single = client.post("/datasets/segy/extract", json=_extract(plain, max_shots=2)).json()

    for prepared in selected:
        assert prepared["receiver_count"] == single["receiver_count"]
        assert prepared["line_length_m"] == pytest.approx(single["line_length_m"])
    first, second = (np.load(prepared["observations_path"]) for prepared in selected)
    assert np.allclose(first, second, atol=1e-2)
    # Component 1 carries an offset of 100000 in the fixture, so the wrong component is
    # off by that rather than off by noise.
    assert np.allclose(first, np.load(single["observations_path"]) + 100_000, atol=1e-2)


@needs_segyio
def test_a_component_that_is_not_everywhere_is_refused(tmp_path: Path) -> None:
    """Declaring three when the stations hold one is not a selection error."""
    path = _line(tmp_path / "plain.sgy")

    response = _client(tmp_path).post(
        "/datasets/segy/extract", json=_extract(path, max_shots=2, components=3)
    )

    assert response.status_code == 422
    assert "hold 1 traces each" in response.json()["detail"]


@needs_segyio
def test_a_component_index_outside_the_record_is_refused_before_any_reading(
    tmp_path: Path,
) -> None:
    path = _line(tmp_path / "3c.sgy", components=3)

    response = _client(tmp_path).post(
        "/datasets/segy/extract", json=_extract(path, components=3, component_index=3)
    )

    assert response.status_code == 422


@needs_segyio
def test_the_channels_available_to_a_2d_run_are_stations_not_traces(tmp_path: Path) -> None:
    """A 3C record offers 20 channels, not 60."""
    path = _line(tmp_path / "3c.sgy", receivers=20, components=3)

    prepared = (
        _client(tmp_path)
        .post("/datasets/segy/extract", json=_extract(path, max_shots=2, components=3))
        .json()
    )

    assert prepared["channels_available"] == 20


@needs_segyio
def test_the_preparation_records_what_it_did_beside_what_it_produced(tmp_path: Path) -> None:
    """A path holds no record of how its contents were made."""
    import hashlib
    import json

    path = _line(tmp_path / "line.sgy")

    prepared = (
        _client(tmp_path)
        .post(
            "/datasets/segy/extract",
            json=_extract(
                path,
                max_shots=2,
                preprocessing={
                    "remove_mean": True,
                    "bandpass": {
                        "low_pass": {"value": 40.0, "quantity_type": "frequency", "unit": "Hz"}
                    },
                },
            ),
        )
        .json()
    )

    assert prepared["preprocessing_applied"] == [
        "removed each trace's mean",
        "kept below 40 Hz, zero-phase",
    ]
    receipt = json.loads(Path(prepared["preparation_path"]).read_text(encoding="utf-8"))
    assert receipt["request"]["preprocessing"]["remove_mean"] is True
    assert receipt["request"]["max_shots"] == 2
    assert receipt["observations_shape"] == [2, 20, SAMPLES]

    observations = np.load(prepared["observations_path"], allow_pickle=False)
    digest = hashlib.sha256(np.ascontiguousarray(observations).tobytes()).hexdigest()
    assert digest == prepared["observations_sha256"] == receipt["observations_sha256"]


@needs_segyio
def test_declaring_no_preprocessing_leaves_the_traces_as_recorded(tmp_path: Path) -> None:
    path = _line(tmp_path / "line.sgy")

    prepared = (
        _client(tmp_path).post("/datasets/segy/extract", json=_extract(path, max_shots=1)).json()
    )

    assert prepared["preprocessing_applied"] == []
    # The fixture writes shot*1000 + channel plus a little noise, so an untouched trace
    # still averages to its own number.
    observations = np.load(prepared["observations_path"], allow_pickle=False)
    assert observations[0, 5].mean() == pytest.approx(5.0, abs=1e-3)


@needs_segyio
def test_the_mute_is_measured_from_the_offset_the_run_will_model(tmp_path: Path) -> None:
    """Along the line, because that is the geometry the 2D solver propagates in."""
    path = _line(tmp_path / "line.sgy", receivers=20)

    prepared = (
        _client(tmp_path)
        .post(
            "/datasets/segy/extract",
            json=_extract(
                path,
                max_shots=1,
                preprocessing={
                    "top_mute": {
                        "velocity": {
                            "value": 1000.0,
                            "quantity_type": "p_wave_velocity",
                            "unit": "m/s",
                        },
                        "delay": {"value": 0.0, "quantity_type": "time", "unit": "s"},
                        "taper": {"value": 0.0, "quantity_type": "time", "unit": "s"},
                    }
                },
            ),
        )
        .json()
    )

    observations = np.load(prepared["observations_path"], allow_pickle=False)
    receivers = np.load(prepared["receivers_path"], allow_pickle=False)
    sources = np.load(prepared["sources_path"], allow_pickle=False)
    # Channels sit every 10 m, so the mute time grows by 10 ms across the spread and the
    # number of zeroed samples grows with it.
    zeroed = (observations[0] == 0).sum(axis=-1)
    expected = np.ceil(np.abs(receivers[:, 0] - sources[0, 0]) / 1000.0 / 0.002)
    assert np.allclose(zeroed, expected, atol=1)


@needs_segyio
def test_shots_split_across_files_are_read_as_one_line(tmp_path: Path) -> None:
    """Soda Lake publishes one vibrator point per file, which is not unusual."""
    first = _line(tmp_path / "a.sgy", shots=2, first_shot=0)
    second = _line(tmp_path / "b.sgy", shots=2, first_shot=2)
    together = _line(tmp_path / "whole.sgy", shots=4)
    client = _client(tmp_path)

    split = client.post(
        "/datasets/segy/extract",
        json=_extract(first, additional_source_paths=[str(second)], max_shots=4),
    ).json()
    whole = client.post("/datasets/segy/extract", json=_extract(together, max_shots=4)).json()

    assert split["source_filenames"] == ["a.sgy", "b.sgy"]
    assert split["shot_count"] == whole["shot_count"] == 4
    assert np.allclose(np.load(split["sources_path"]), np.load(whole["sources_path"]))
    assert np.allclose(
        np.load(split["observations_path"]), np.load(whole["observations_path"]), atol=1e-2
    )


@needs_segyio
def test_files_that_are_not_records_of_one_line_are_refused(tmp_path: Path) -> None:
    import segyio

    short = tmp_path / "short.sgy"
    spec = segyio.spec()
    spec.format = 5
    spec.samples = list(range(SAMPLES // 2))
    spec.tracecount = 4
    with segyio.create(str(short), spec) as handle:
        handle.bin[segyio.BinField.Interval] = 2000
        for index in range(4):
            handle.header[index] = {
                segyio.TraceField.SourceX: 400_000,
                segyio.TraceField.SourceY: 7_500_000,
                segyio.TraceField.GroupX: 400_100 + index * 10,
                segyio.TraceField.GroupY: 7_500_000,
                segyio.TraceField.SourceGroupScalar: 1,
            }
            handle.trace[index] = np.zeros(SAMPLES // 2, dtype=np.float32)

    response = _client(tmp_path).post(
        "/datasets/segy/extract",
        json=_extract(_line(tmp_path / "a.sgy"), additional_source_paths=[str(short)]),
    )

    assert response.status_code == 422
    assert "not records of one line" in response.json()["detail"]


@needs_segyio
def test_a_stated_azimuth_is_used_instead_of_one_fitted_to_the_stations(
    tmp_path: Path,
) -> None:
    """Fitting a principal direction through a patch returns a useless axis."""
    path = _line(tmp_path / "patch.sgy", shots=2, receivers=20, parallel_line_offset_m=400.0)
    client = _client(tmp_path)

    fitted = client.post("/datasets/segy/extract", json=_extract(path, max_shots=2)).json()
    stated = client.post(
        "/datasets/segy/extract",
        json=_extract(
            path,
            max_shots=2,
            line_azimuth={"value": 90.0, "quantity_type": "angle", "unit": "deg"},
        ),
    ).json()

    # The lines run due east, so that is the answer; the fit is dragged off it by the
    # four hundred metres between them.
    assert stated["line_azimuth_degrees"] == pytest.approx(90.0, abs=0.1)
    assert abs(fitted["line_azimuth_degrees"] - 90.0) > 1.0


@needs_segyio
def test_a_corridor_takes_one_line_out_of_a_patch(tmp_path: Path) -> None:
    path = _line(tmp_path / "patch.sgy", shots=2, receivers=20, parallel_line_offset_m=400.0)

    prepared = (
        _client(tmp_path)
        .post(
            "/datasets/segy/extract",
            json=_extract(
                path,
                max_shots=2,
                line_azimuth={"value": 90.0, "quantity_type": "angle", "unit": "deg"},
                corridor_half_width={"value": 50.0, "quantity_type": "length", "unit": "m"},
            ),
        )
        .json()
    )

    assert prepared["receiver_count"] == 20
    assert prepared["maximum_offline_deviation_m"] < 50.0
    # Without the corridor both lines are read as one spread of forty.
    assert prepared["channels_available"] == 20


@needs_segyio
def test_a_corridor_that_holds_no_station_is_refused_rather_than_emptied(
    tmp_path: Path,
) -> None:
    # Sources on their own line a kilometre off the receivers, which is how a 3D patch
    # is laid out and why the corridor can miss everything.
    path = _line(tmp_path / "patch.sgy", shots=2, receivers=20, source_offline_m=1000.0)

    response = _client(tmp_path).post(
        "/datasets/segy/extract",
        json=_extract(
            path,
            max_shots=2,
            line_azimuth={"value": 90.0, "quantity_type": "angle", "unit": "deg"},
            corridor_half_width={"value": 5.0, "quantity_type": "length", "unit": "m"},
        ),
    )

    assert response.status_code == 422
    assert "within 5 m of the line" in response.json()["detail"]
