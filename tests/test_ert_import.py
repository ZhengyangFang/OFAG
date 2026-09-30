import numpy as np
import pytest

from ofag.core.schemas import CoordinateConvention
from ofag.services.ert_import import (
    SUPPORTED_INSTRUMENTS,
    ERTFieldImportRequest,
    ERTFieldImportService,
)

CONVENTION = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")


def _bert_line(tmp_path, electrode_count: int = 16, spacing: float = 2.0):
    """Write a pyGIMLi/BERT unified file from a forward-modelled homogeneous line."""
    import pygimli as pg
    from pygimli.physics import ert

    positions = np.arange(electrode_count, dtype=float) * spacing
    scheme = ert.createData(elecs=positions, schemeName="dd")
    span = float(positions.max())
    world = pg.meshtools.createWorld(start=[-span, 0], end=[2 * span, -span])
    mesh = pg.meshtools.createMesh(world, quality=32, area=span / 6)
    data = ert.simulate(mesh, res=100.0, scheme=scheme, noiseLevel=0.01, seed=0, verbose=False)
    path = tmp_path / "line.dat"
    data.save(str(path))
    return path, data


def _request(path, **overrides) -> ERTFieldImportRequest:
    fields = {
        "source_path": str(path),
        "instrument": "BERT",
        "coordinate_convention": CONVENTION,
    }
    fields.update(overrides)
    return ERTFieldImportRequest(**fields)


def test_importing_a_field_file_writes_ofag_geometry_and_resistance(tmp_path) -> None:
    pytest.importorskip("PyHydroGeophysX")
    pytest.importorskip("pygimli")
    path, source = _bert_line(tmp_path)
    service = ERTFieldImportService(import_root=tmp_path / "imports")

    dataset = service.import_field_file(_request(path))

    assert dataset.instrument == "BERT"
    assert dataset.electrode_count == 16
    assert dataset.observation_count == source.size()
    assert not dataset.geometry_is_assumed

    electrodes = np.load(dataset.electrodes_path)
    quadrupoles = np.load(dataset.quadrupoles_path)
    assert electrodes.shape == (16, 3)
    assert quadrupoles.shape == (source.size(), 4)

    # The file numbers electrodes from 1 and OFAG indexes from 0.
    expected = np.column_stack([np.asarray(source[token], dtype=np.int64) for token in "abmn"])
    assert np.array_equal(quadrupoles, expected)
    assert quadrupoles.min() == 0
    assert quadrupoles.max() == 15


def test_a_file_carrying_both_quantities_uses_the_resistance_it_states(tmp_path) -> None:
    """pyGIMLi writes r, rhoa, u, i, k and err, so nothing has to be recovered."""
    pytest.importorskip("pygimli")
    path, source = _bert_line(tmp_path)
    service = ERTFieldImportService(import_root=tmp_path / "imports")

    dataset = service.import_field_file(_request(path))

    assert dataset.resistance_provenance == "measured"
    resistance = np.genfromtxt(dataset.observations_path, delimiter=",", names=True)[
        "resistance_ohm"
    ]
    # Exactly the forward model's own resistance, not a value that survived a
    # multiplication and a division by the same factor.
    assert np.allclose(resistance, np.asarray(source["r"], dtype=float), rtol=1e-12)


def test_the_imported_survey_inverts_through_the_ert_plugin(tmp_path) -> None:
    """Import and inversion must agree about geometry, not just about files."""
    pytest.importorskip("PyHydroGeophysX")
    pytest.importorskip("pygimli")
    from ofag.core.constants import QuantityType
    from ofag.core.schemas import DataChannelSpec, DatasetSpec, QuantitySpec, RunSpec
    from ofag.plugins.protocol import PluginContext
    from ofag.plugins.pygimli_ert import PyGIMLiERTPlugin

    path, _ = _bert_line(tmp_path, electrode_count=20)
    dataset = ERTFieldImportService(import_root=tmp_path / "imports").import_field_file(
        _request(path)
    )

    channel = DataChannelSpec(
        channel_id="dc",
        dataset=DatasetSpec(
            name=dataset.source_filename,
            coordinate_convention=CONVENTION,
            physical_quantity=QuantityType.TRANSFER_RESISTANCE,
            units="ohm",
        ),
        observations_path=dataset.observations_path,
        data_uncertainty=QuantitySpec(
            value=0.05, quantity_type=QuantityType.TRANSFER_RESISTANCE, unit="ohm"
        ),
    )
    spec = RunSpec(
        schema_version="1.1",
        plugin_id="pygimli.ert.dcip",
        engine="pygimli",
        dataset=channel.dataset,
        datasets=(channel,),
        physics={
            "array": {
                "electrodes_path": dataset.electrodes_path,
                "quadrupoles_path": dataset.quadrupoles_path,
            },
            "mesh": {"dimension": 2, "quality": 32.0},
            "optimizer": {"max_iterations": 3},
        },
    )
    context = PluginContext(tmp_path / "artifacts")

    assert PyGIMLiERTPlugin().validate(context, spec).valid
    result = PyGIMLiERTPlugin().execute(context, spec)

    # A homogeneous 100 ohm.m half space must come back as one.
    model = np.load(tmp_path / "artifacts" / str(spec.run_id) / "recovered_model.npy")
    assert 60.0 < float(np.median(model)) < 170.0, float(np.median(model))
    assert result.summary["electrodes"] == 20


def test_an_unknown_instrument_is_refused_with_the_supported_list(tmp_path) -> None:
    service = ERTFieldImportService(import_root=tmp_path / "imports")
    source = tmp_path / "line.dat"
    source.write_text("nothing\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown instrument"):
        service.import_field_file(_request(source, instrument="Terrameter"))


def test_a_missing_source_file_is_refused(tmp_path) -> None:
    service = ERTFieldImportService(import_root=tmp_path / "imports")
    with pytest.raises(ValueError, match="does not exist"):
        service.import_field_file(_request(tmp_path / "absent.dat"))


def test_a_parser_failure_names_the_instrument_and_file(tmp_path) -> None:
    pytest.importorskip("PyHydroGeophysX")
    service = ERTFieldImportService(import_root=tmp_path / "imports")
    source = tmp_path / "broken.stg"
    source.write_text("this is not a SuperSting export\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Sting parser could not read broken.stg"):
        service.import_field_file(_request(source, instrument="Sting"))


def test_the_supported_instrument_list_matches_the_dependency() -> None:
    """The workbench offers this list, so it must not drift from the parser."""
    pytest.importorskip("PyHydroGeophysX")
    import typing

    from PyHydroGeophysX.data_processing.ert_data_agent import Instrument

    assert set(SUPPORTED_INSTRUMENTS) == set(typing.get_args(Instrument))


def _unified_file(tmp_path, *, token: str, topography: bool, name: str = "survey.ohm"):
    """A pyGIMLi/BERT unified file written by hand, as a field crew's file is."""
    elevations = [100.0 + 0.8 * index for index in range(8)] if topography else [0.0] * 8
    lines = ["8# Number of sensors", "#x z"]
    lines += [f"{index * 2.0}\t{elevations[index]}" for index in range(8)]
    quads = [(1, 4, 2, 3), (2, 5, 3, 4), (3, 6, 4, 5), (4, 7, 5, 6), (5, 8, 6, 7)]
    values = [1.25, 1.5, 1.75, 2.0, 2.25]
    lines += [f"{len(quads)}# Number of data", f"#a\tb\tm\tn\t{token}"]
    lines += [f"{a}\t{b}\t{m}\t{n}\t{v}" for (a, b, m, n), v in zip(quads, values, strict=True)]
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, values


def test_a_file_that_carries_resistance_is_not_reported_as_derived(tmp_path) -> None:
    """The format declares its columns; the provenance is that declaration."""
    path, values = _unified_file(tmp_path, token="r", topography=False)

    imported = ERTFieldImportService(import_root=tmp_path / "out").import_field_file(_request(path))

    assert imported.reader == "pygimli"
    assert imported.resistance_provenance == "measured"
    assert imported.resistance_min_ohm == pytest.approx(min(values))
    assert imported.resistance_max_ohm == pytest.approx(max(values))


def test_a_file_that_carries_apparent_resistivity_still_says_derived(tmp_path) -> None:
    """The other half, so the first is a distinction and not a new default."""
    path, values = _unified_file(tmp_path, token="rhoa", topography=False)

    imported = ERTFieldImportService(import_root=tmp_path / "out").import_field_file(_request(path))

    assert imported.resistance_provenance == "derived_from_apparent_resistivity"
    # Divided by a geometric factor, so nothing like the file's own numbers.
    assert imported.resistance_max_ohm < min(values)


def test_a_two_column_profile_keeps_its_elevation_out_of_the_northing(tmp_path) -> None:
    """`#x z` is a 2D line with topography, not a line running north-east."""
    path, _ = _unified_file(tmp_path, token="r", topography=True)

    imported = ERTFieldImportService(import_root=tmp_path / "out").import_field_file(_request(path))

    electrodes = np.load(imported.electrodes_path, allow_pickle=False)
    assert np.all(electrodes[:, 1] == 0.0)
    assert electrodes[:, 2].min() == pytest.approx(100.0)
    assert electrodes[:, 2].max() == pytest.approx(105.6)


def test_the_duplicated_column_guard_leaves_a_real_layout_alone() -> None:
    """A tree-trunk survey has a northing that genuinely varies, and one that is genuinely
    constant is still not equal to the elevation."""
    from ofag.services.ert_import import _without_duplicated_elevation

    ring = np.array([[0.1, -0.2, 0.0], [0.2, 0.1, 0.0], [-0.1, 0.2, 0.0]])
    assert np.array_equal(_without_duplicated_elevation(ring), ring)

    flat_line = np.array([[0.0, 7.0, 0.0], [2.0, 7.0, 0.0], [4.0, 7.0, 0.0]])
    assert np.array_equal(_without_duplicated_elevation(flat_line), flat_line)

    duplicated = np.array([[0.0, 100.0, 100.0], [2.0, 101.0, 101.0], [4.0, 102.0, 102.0]])
    corrected = _without_duplicated_elevation(duplicated)
    assert np.all(corrected[:, 1] == 0.0)
    assert np.array_equal(corrected[:, 2], duplicated[:, 2])
