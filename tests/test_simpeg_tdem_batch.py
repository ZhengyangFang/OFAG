import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    LayeredEarthSpec,
    QuantitySpec,
    RunSpec,
    TDEMBatchInversionSpec,
    TDEMBatchSoundingSpec,
    TDEMBetaSpec,
    TDEMModelSpec,
    TDEMOptimizerSpec,
    TDEMSystemSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_tdem_batch import SimPEGTDEMBatchPlugin


def test_simpeg_tdem_batch_stitches_independent_soundings(tmp_path) -> None:
    pytest.importorskip("simpeg")
    times = [1e-5, 2.5118864315e-5, 6.3095734448e-5, 1.5848931925e-4, 3.9810717055e-4, 1e-3]
    response = [
        6.65728853e-11,
        2.75417785e-11,
        9.06325616e-12,
        2.18525817e-12,
        4.21439370e-13,
        7.70720620e-14,
    ]

    def write_sounding(name: str) -> str:
        path = tmp_path / f"{name}.csv"
        path.write_text(
            "time_s,magnetic_flux_density_t\n"
            + "".join(
                f"{time:.12e},{value:.12e}\n" for time, value in zip(times, response, strict=True)
            ),
            encoding="utf-8",
        )
        return str(path)

    sounding_a_path = write_sounding("sounding_a")
    sounding_b_path = write_sounding("sounding_b")
    manifest_path = tmp_path / "batch_manifest.json"
    manifest_path.write_text('{"soundings":["A","B"]}\n', encoding="utf-8")

    def length(value: float | list[float]) -> QuantitySpec:
        return QuantitySpec(value=value, quantity_type=QuantityType.LENGTH, unit="m")

    def sounding(sounding_id: str, path: str, x: float) -> TDEMBatchSoundingSpec:
        # A central-loop sounding: the loop and its receiver share an origin, and that
        # origin is the same for every station in the survey.
        return TDEMBatchSoundingSpec(
            sounding_id=sounding_id,
            observations_path=path,
            station_location=length([x, 0.0, 20.0]),
            system=TDEMSystemSpec(
                times=QuantitySpec(value=times, quantity_type=QuantityType.TIME, unit="s"),
                source_location=length([0.0, 0.0, 20.0]),
                receiver_location=length([0.0, 0.0, 20.0]),
                source_radius=length(6.0),
                source_current=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.ELECTRIC_CURRENT, unit="A"
                ),
            ),
            data_uncertainty=QuantitySpec(
                value=5e-12,
                quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY,
                unit="T",
            ),
        )

    spec = RunSpec(
        plugin_id="simpeg.aem.batch_tdem1d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="small-tdem-batch",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_FLUX_DENSITY,
            units="T",
        ),
        tdem_batch_inversion=TDEMBatchInversionSpec(
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
            soundings=(
                sounding("A", sounding_a_path, 0.0),
                sounding("B", sounding_b_path, 100.0),
            ),
        ),
        parameters={"batch_manifest_path": str(manifest_path)},
    )
    plugin = SimPEGTDEMBatchPlugin()
    assert plugin.validate(PluginContext(tmp_path / "artifacts"), spec).valid

    result = plugin.execute(PluginContext(tmp_path / "artifacts"), spec)

    assert result.summary["sounding_count"] == 2
    assert result.summary["model_layers"] == 4
    artifact_types = {artifact.artifact_type for artifact in result.artifacts}
    assert {"stitched_conductivity_section", "sounding_summary", "batch_manifest"} <= artifact_types
    section_path = tmp_path / "artifacts" / result.artifacts[-3].relative_path
    section = np.load(section_path)
    assert section["conductivity_s_m"].shape == (2, 4)
    assert np.allclose(section["receiver_locations_m"][:, 0], [0.0, 100.0])


def test_a_station_location_is_three_lengths() -> None:
    """The one field that says where a stitched column is, so it is checked."""
    from pydantic import ValidationError

    def build(**extra) -> TDEMBatchSoundingSpec:
        return TDEMBatchSoundingSpec(
            sounding_id="A",
            observations_path="a.csv",
            system=TDEMSystemSpec(
                times=QuantitySpec(value=[1e-4], quantity_type=QuantityType.TIME, unit="s"),
                source_location=QuantitySpec(
                    value=[0.0, 0.0, 0.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                receiver_location=QuantitySpec(
                    value=[0.0, 0.0, 0.0], quantity_type=QuantityType.LENGTH, unit="m"
                ),
                source_radius=QuantitySpec(value=6.0, quantity_type=QuantityType.LENGTH, unit="m"),
                source_current=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.ELECTRIC_CURRENT, unit="A"
                ),
            ),
            data_uncertainty=QuantitySpec(
                value=1e-12, quantity_type=QuantityType.MAGNETIC_FLUX_DENSITY, unit="T"
            ),
            **extra,
        )

    # Absent is allowed: a batch of repeats at one station has nothing to say.
    assert build().station_location is None

    with pytest.raises(ValidationError, match="three coordinates"):
        build(
            station_location=QuantitySpec(
                value=[10.0, 20.0], quantity_type=QuantityType.LENGTH, unit="m"
            )
        )
    with pytest.raises(ValidationError, match="must be a length"):
        build(
            station_location=QuantitySpec(
                value=[10.0, 20.0, 0.0], quantity_type=QuantityType.TIME, unit="s"
            )
        )
