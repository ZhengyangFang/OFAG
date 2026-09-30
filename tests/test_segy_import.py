"""Reading a SEG-Y survey's geometry, in units somebody stated."""

from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ofag.api.app import create_app
from ofag.services.run_service import RunService
from ofag.services.segy_import import (
    STANDARD_HEADER_BYTES,
    SegyImportRequest,
    SegyImportService,
)

needs_segyio = pytest.mark.skipif(
    find_spec("segyio") is None, reason="the seismic extra is not installed"
)

CONVENTION = {"crs": "EPSG:28351"}
SAMPLE_INTERVAL_US = 2000
SAMPLES = 64


def _land_line(
    path: Path,
    *,
    shots: int = 4,
    receivers: int = 12,
    scalar: int = 1,
    stored_unit_divisor: float = 1.0,
    mixed_scalars: bool = False,
    auxiliary_traces: int = 0,
) -> Path:
    """A shot-gather land line, written the way a contractor's file is."""
    import segyio

    trace_count = shots * receivers + auxiliary_traces
    spec = segyio.spec()
    spec.format = 5  # IEEE float
    spec.samples = list(range(SAMPLES))
    spec.tracecount = trace_count

    with segyio.create(str(path), spec) as handle:
        handle.bin[segyio.BinField.Interval] = SAMPLE_INTERVAL_US
        index = 0
        for _ in range(auxiliary_traces):
            handle.header[index] = {
                segyio.TraceField.SourceGroupScalar: scalar,
                segyio.TraceField.TraceIdentificationCode: 6,  # sweep
                segyio.TraceField.TRACE_SEQUENCE_LINE: index + 1,
            }
            handle.trace[index] = np.zeros(SAMPLES, dtype=np.float32)
            index += 1
        for shot in range(shots):
            source_x = 400_000.0 + shot * 50.0
            source_y = 7_500_000.0
            for receiver in range(receivers):
                receiver_x = 400_000.0 + receiver * 10.0
                receiver_y = 7_500_000.0
                handle.header[index] = {
                    segyio.TraceField.SourceX: int(source_x * stored_unit_divisor),
                    segyio.TraceField.SourceY: int(source_y * stored_unit_divisor),
                    segyio.TraceField.GroupX: int(receiver_x * stored_unit_divisor),
                    segyio.TraceField.GroupY: int(receiver_y * stored_unit_divisor),
                    segyio.TraceField.SourceGroupScalar: (
                        (scalar if index % 2 == 0 else scalar + 1) if mixed_scalars else scalar
                    ),
                    segyio.TraceField.TRACE_SEQUENCE_LINE: index + 1,
                }
                handle.trace[index] = np.zeros(SAMPLES, dtype=np.float32)
                index += 1
    return path


def _request(path: Path, **overrides: object) -> dict[str, object]:
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
def test_a_land_line_reports_its_geometry_in_canonical_metres(tmp_path: Path) -> None:
    path = _land_line(tmp_path / "line1.sgy")
    service = SegyImportService(import_root=tmp_path / "imports")

    imported = service.import_file(SegyImportRequest.model_validate(_request(path)))

    assert imported.trace_count == 48
    assert imported.sample_count == SAMPLES
    assert imported.sample_interval_s == pytest.approx(0.002)
    assert imported.record_length_s == pytest.approx(0.002 * (SAMPLES - 1))
    assert imported.shot_count == 4
    assert imported.receiver_count == 12
    assert imported.coordinate_scalar_applied == pytest.approx(1.0)
    assert imported.coordinate_scalar_source == "header"
    # Sources step 50 m, receivers 10 m over 12 stations: the extent is the union, and
    # the offsets are what say the two fields were not swapped.
    assert imported.bounds_m[0] == pytest.approx(400_000.0)
    assert imported.bounds_m[1] == pytest.approx(400_150.0)
    assert imported.offset_min_m == pytest.approx(0.0)
    assert imported.offset_max_m == pytest.approx(150.0)

    geometry = np.load(imported.geometry_path, allow_pickle=False)
    assert geometry.shape == (48, 4)


@needs_segyio
def test_a_negative_coordinate_scalar_divides_rather_than_multiplies(tmp_path: Path) -> None:
    """The SEG-Y sign rule, which read backwards scales a survey by ten thousand."""
    path = _land_line(tmp_path / "hundredths.sgy", scalar=-100, stored_unit_divisor=100.0)
    client = _client(tmp_path)

    response = client.post("/datasets/segy", json=_request(path))

    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["coordinate_scalar_applied"] == pytest.approx(0.01)
    assert imported["bounds_m"][0] == pytest.approx(400_000.0)
    assert imported["bounds_m"][1] == pytest.approx(400_150.0)
    assert imported["offset_max_m"] == pytest.approx(150.0)


@needs_segyio
def test_a_declared_scalar_overrides_a_header_that_is_wrong(tmp_path: Path) -> None:
    """Files whose scalar is simply absent or wrong are common."""
    path = _land_line(tmp_path / "unset.sgy", scalar=1, stored_unit_divisor=100.0)
    client = _client(tmp_path)

    response = client.post("/datasets/segy", json=_request(path, coordinate_scalar=0.01))

    assert response.status_code == 200, response.text
    imported = response.json()
    assert imported["coordinate_scalar_source"] == "declared"
    assert imported["bounds_m"][1] == pytest.approx(400_150.0)


@needs_segyio
def test_traces_that_disagree_about_the_scalar_are_refused(tmp_path: Path) -> None:
    """Averaging them would put the coordinates in two different units at once."""
    path = _land_line(tmp_path / "mixed.sgy", scalar=1, mixed_scalars=True)

    response = _client(tmp_path).post("/datasets/segy", json=_request(path))

    assert response.status_code == 422
    assert "different coordinate scalars" in response.json()["detail"]


@needs_segyio
def test_the_coordinate_unit_is_converted_not_assumed(tmp_path: Path) -> None:
    """SEG-Y's own unit flag is optional and widely unset, so it is declared."""
    path = _land_line(tmp_path / "feet.sgy")
    client = _client(tmp_path)

    metres = client.post("/datasets/segy", json=_request(path)).json()
    feet = client.post("/datasets/segy", json=_request(path, coordinate_unit="ft")).json()

    assert feet["offset_max_m"] == pytest.approx(metres["offset_max_m"] * 0.3048)


@needs_segyio
def test_header_positions_may_be_declared_where_a_vendor_put_them(tmp_path: Path) -> None:
    """Reading the standard bytes of a file that uses CDP_X would give zeros."""
    path = _land_line(tmp_path / "line1.sgy")
    client = _client(tmp_path)

    swapped = client.post(
        "/datasets/segy",
        json=_request(
            path,
            source_x_byte=STANDARD_HEADER_BYTES["receiver_x"],
            source_y_byte=STANDARD_HEADER_BYTES["receiver_y"],
            receiver_x_byte=STANDARD_HEADER_BYTES["source_x"],
            receiver_y_byte=STANDARD_HEADER_BYTES["source_y"],
        ),
    ).json()

    # Swapping the two fields leaves the extent alone and the offsets alone, which is
    # exactly why an extent is not enough to prove a geometry read.
    assert swapped["offset_max_m"] == pytest.approx(150.0)
    assert swapped["shot_count"] == 12
    assert swapped["receiver_count"] == 4


@needs_segyio
def test_a_scan_may_be_capped_and_says_that_it_was(tmp_path: Path) -> None:
    """A very large survey is a minute of header reading; the cap is reported."""
    path = _land_line(tmp_path / "line1.sgy")

    response = _client(tmp_path).post("/datasets/segy", json=_request(path, max_traces_scanned=10))

    assert response.status_code == 200
    imported = response.json()
    assert imported["trace_count"] == 48
    assert imported["scanned_trace_count"] == 10
    assert imported["truncated"] is True


@needs_segyio
def test_a_missing_file_is_reported_rather_than_raised(tmp_path: Path) -> None:
    response = _client(tmp_path).post("/datasets/segy", json=_request(tmp_path / "absent.sgy"))

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


@needs_segyio
def test_a_scalar_of_zero_is_refused_before_it_collapses_the_survey(tmp_path: Path) -> None:
    path = _land_line(tmp_path / "line1.sgy")

    response = _client(tmp_path).post("/datasets/segy", json=_request(path, coordinate_scalar=0.0))

    assert response.status_code == 422


@needs_segyio
def test_a_geometry_the_mapped_bytes_cannot_describe_is_named(tmp_path: Path) -> None:
    """Found on a real file: PoroTomo's DAS SEG-Y leaves the source bytes at zero."""
    import segyio

    path = tmp_path / "das.sgy"
    spec = segyio.spec()
    spec.format = 5
    spec.samples = list(range(SAMPLES))
    spec.tracecount = 8
    with segyio.create(str(path), spec) as handle:
        handle.bin[segyio.BinField.Interval] = SAMPLE_INTERVAL_US
        for index in range(8):
            handle.header[index] = {
                segyio.TraceField.SourceX: 0,
                segyio.TraceField.SourceY: 0,
                segyio.TraceField.GroupX: 32796154,
                segyio.TraceField.GroupY: 440755494,
                segyio.TraceField.SourceGroupScalar: -100,
            }
            handle.trace[index] = np.zeros(SAMPLES, dtype=np.float32)

    imported = _client(tmp_path).post("/datasets/segy", json=_request(path)).json()

    assert imported["coordinate_scalar_applied"] == pytest.approx(0.01)
    assert imported["geometry_warning"] is not None
    assert "source coordinate is zero" in imported["geometry_warning"]


@needs_segyio
def test_a_line_whose_geometry_reads_cleanly_carries_no_warning(tmp_path: Path) -> None:
    path = _land_line(tmp_path / "line.sgy")

    imported = _client(tmp_path).post("/datasets/segy", json=_request(path)).json()

    assert imported["geometry_warning"] is None


@needs_segyio
def test_one_position_shared_by_every_trace_is_named_as_such(tmp_path: Path) -> None:
    """Sources and receivers both populated, but nothing moves between traces."""
    import segyio

    path = tmp_path / "static.sgy"
    spec = segyio.spec()
    spec.format = 5
    spec.samples = list(range(SAMPLES))
    spec.tracecount = 6
    with segyio.create(str(path), spec) as handle:
        handle.bin[segyio.BinField.Interval] = SAMPLE_INTERVAL_US
        for index in range(6):
            handle.header[index] = {
                segyio.TraceField.SourceX: 400_000,
                segyio.TraceField.SourceY: 7_500_000,
                segyio.TraceField.GroupX: 400_100,
                segyio.TraceField.GroupY: 7_500_000,
                segyio.TraceField.SourceGroupScalar: 1,
            }
            handle.trace[index] = np.zeros(SAMPLES, dtype=np.float32)

    imported = _client(tmp_path).post("/datasets/segy", json=_request(path)).json()

    assert "do not distinguish the channels" in (imported["geometry_warning"] or "")


@needs_segyio
def test_the_auxiliary_traces_of_a_land_record_are_not_stations(tmp_path: Path) -> None:
    """A real Soda Lake vibroseis record carries one, and it read as a station."""
    path = _land_line(tmp_path / "aux.sgy", auxiliary_traces=2)
    service = SegyImportService(import_root=tmp_path / "imports")

    imported = service.import_file(SegyImportRequest.model_validate(_request(path)))

    assert imported.trace_count == 50
    assert imported.unpositioned_trace_count == 2
    assert imported.receiver_count == 12
    assert imported.shot_count == 4
    assert imported.bounds_m[0] == pytest.approx(400_000.0)
    assert imported.offset_max_m == pytest.approx(150.0)
    assert imported.geometry_warning is None


@needs_segyio
def test_the_saved_geometry_keeps_a_row_for_every_trace(tmp_path: Path) -> None:
    """Row index is trace index, which is how a trace is read back out."""
    path = _land_line(tmp_path / "aux.sgy", auxiliary_traces=2)
    service = SegyImportService(import_root=tmp_path / "imports")

    imported = service.import_file(SegyImportRequest.model_validate(_request(path)))

    geometry = np.load(imported.geometry_path, allow_pickle=False)
    assert geometry.shape == (50, 4)
    assert not geometry[:2].any()


@needs_segyio
def test_a_file_of_nothing_but_unpositioned_traces_is_described_not_emptied(
    tmp_path: Path,
) -> None:
    """Dropping every trace would leave nothing to look at and no reason why."""
    path = _land_line(tmp_path / "all-aux.sgy", shots=0, receivers=0, auxiliary_traces=4)
    service = SegyImportService(import_root=tmp_path / "imports")

    imported = service.import_file(SegyImportRequest.model_validate(_request(path)))

    assert imported.unpositioned_trace_count == 0
    assert imported.geometry_warning == (
        "every mapped coordinate is zero, so these bytes hold no geometry"
    )


@needs_segyio
def test_the_import_echoes_back_the_mapping_it_read_with(tmp_path: Path) -> None:
    """The selection step reads the file again, and must read it the same way."""
    path = _land_line(tmp_path / "line.sgy", stored_unit_divisor=10.0)

    imported = (
        _client(tmp_path)
        .post("/datasets/segy", json=_request(path, coordinate_unit="dm", receiver_x_byte=81))
        .json()
    )

    assert imported["coordinate_unit"] == "dm"
    assert imported["source_x_byte"] == STANDARD_HEADER_BYTES["source_x"]
    assert imported["receiver_x_byte"] == 81
    # Decimetres of the same integers: the extent is a tenth of the metres one.
    assert imported["bounds_m"][1] - imported["bounds_m"][0] == pytest.approx(150.0)
