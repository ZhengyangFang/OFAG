"""A gravity high means more mass, through every layer of the gravity stack."""

from uuid import uuid4

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    DatasetSpec,
    GravityInversionSpec,
    GravityModelSpec,
    GravityOptimizerSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
)
from ofag.engines.simpeg.units import gravity_anomaly_from_simpeg, gravity_anomaly_to_simpeg
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin

GRAVITATIONAL_CONSTANT = 6.674e-11  # m^3 / (kg s^2)
MGAL_PER_M_S2 = 1e5


def point_mass_anomaly_mgal(
    mass_kg: float, easting: np.ndarray, northing: np.ndarray, height_above_m: np.ndarray
) -> np.ndarray:
    """The vertical attraction of a point mass, as a Bouguer anomaly would read it."""
    distance = np.sqrt(easting**2 + northing**2 + height_above_m**2)
    return GRAVITATIONAL_CONSTANT * mass_kg * height_above_m / distance**3 * MGAL_PER_M_S2


def test_the_conversion_only_flips_the_sign() -> None:
    values = np.asarray([-2.0, 0.0, 3.5])

    assert gravity_anomaly_to_simpeg(values) == pytest.approx(-values)
    assert gravity_anomaly_from_simpeg(gravity_anomaly_to_simpeg(values)) == pytest.approx(values)


def test_simpeg_reports_a_buried_mass_as_negative_and_ofag_as_positive() -> None:
    """The measurement behind `GRAVITY_ANOMALY_SIGN`, checked against arithmetic."""
    pytest.importorskip("simpeg")
    from discretize import TensorMesh
    from simpeg import maps
    from simpeg.potential_fields import gravity

    cell, count = 50.0, 24
    mesh = TensorMesh(
        [[cell] * count] * 3, origin=[-cell * count / 2, -cell * count / 2, -cell * count]
    )
    centres = np.asarray(mesh.cell_centers)
    block = (
        (np.abs(centres[:, 0]) < 100.0)
        & (np.abs(centres[:, 1]) < 100.0)
        & (centres[:, 2] > -1100.0)
        & (centres[:, 2] < -900.0)
    )
    contrast = np.where(block, 1.0, 0.0)  # g/cm^3
    station = np.asarray([[0.0, 0.0, 0.0]])
    simulation = gravity.simulation.Simulation3DIntegral(
        mesh=mesh,
        survey=gravity.survey.Survey(
            gravity.sources.SourceField(
                receiver_list=[gravity.receivers.Point(station, components="gz")]
            )
        ),
        rhoMap=maps.IdentityMap(nP=mesh.nC),
        engine="choclo",
        store_sensitivities="forward_only",
    )
    simpeg_gz = float(np.asarray(simulation.dpred(contrast))[0])

    volume = float(contrast.sum()) * cell**3
    expected = float(
        point_mass_anomaly_mgal(
            volume * 1000.0, np.asarray([0.0]), np.asarray([0.0]), np.asarray([1000.0])
        )[0]
    )

    assert expected > 0.0
    assert simpeg_gz < 0.0
    assert float(np.asarray(gravity_anomaly_from_simpeg(simpeg_gz))) == pytest.approx(
        expected, rel=0.02
    )


def test_an_inversion_puts_extra_mass_under_a_gravity_high(tmp_path) -> None:
    """End to end: an anomaly that is positive everywhere has to recover density."""
    pytest.importorskip("simpeg")
    cell, depth = 100.0, 250.0
    offsets = np.asarray([-150.0, -50.0, 50.0, 150.0])
    easting, northing = (grid.ravel() for grid in np.meshgrid(offsets, offsets))
    anomaly = point_mass_anomaly_mgal(
        3.0e10, easting, northing, np.full(easting.size, depth + cell)
    )
    assert (anomaly > 0).all()

    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,gravity_mgal\n"
        + "\n".join(
            f"{x},{y},{cell},{g}" for x, y, g in zip(easting, northing, anomaly, strict=True)
        ),
        encoding="utf-8",
    )
    spec = RunSpec(
        run_id=uuid4(),
        plugin_id="simpeg.pf.gravity3d",
        plugin_version="0.1.0",
        engine="simpeg",
        dataset=DatasetSpec(
            name="point-mass",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[cell, cell, cell], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(6, 6, 4),
            origin=(-300.0, -300.0, -400.0),
        ),
        gravity_inversion=GravityInversionSpec(
            model=GravityModelSpec(
                lower_bound=QuantitySpec(
                    value=-1.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
                ),
                upper_bound=QuantitySpec(
                    value=1.0, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
                ),
            ),
            optimizer=GravityOptimizerSpec(max_iterations=6),
        ),
        parameters={
            "observations_path": str(observations),
            "data_uncertainty": QuantitySpec(
                value=1e-3, quantity_type=QuantityType.GRAVITY_ACCELERATION, unit="mGal"
            ),
        },
    )
    plugin = SimPEGGravity3DPlugin()
    context = PluginContext(tmp_path / "artifacts")
    assert plugin.validate(context, spec).valid

    result = plugin.execute(context, spec)
    recovered = np.load(
        context.run_dir(spec.run_id) / "recovered_density_g_cc.npy", allow_pickle=False
    )
    predicted = np.load(
        context.run_dir(spec.run_id) / "predicted_gravity_mgal.npy", allow_pickle=False
    )

    assert result.summary["engine"] == "simpeg"
    assert recovered.mean() > 0.0, "a gravity high was explained by removing mass"
    assert (predicted > 0).all(), "the predicted anomaly disagrees in sign with the observed"
