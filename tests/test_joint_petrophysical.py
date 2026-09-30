"""A joint inversion told what the rocks are, in both properties at once."""

import json

import numpy as np
import pytest
from pydantic import ValidationError

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    CoordinateConvention,
    CrossGradientCouplingSpec,
    DataChannelSpec,
    DatasetSpec,
    GravityOptimizerSpec,
    GravityRegularizationKind,
    GravityRegularizationSpec,
    GravMagJointInversionSpec,
    JointGravityPropertySpec,
    JointMagneticsPropertySpec,
    JointPetrophysicalClassSpec,
    JointPetrophysicalSpec,
    MagneticsInducingFieldSpec,
    PetrophysicalClassSpec,
    QuantitySpec,
    RunSpec,
    TensorMeshSpec,
)
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravmag_joint import SimPEGGravMagJointPlugin


def _density(value: float) -> QuantitySpec:
    return QuantitySpec(value=value, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3")


def _susceptibility(value: float) -> QuantitySpec:
    return QuantitySpec(
        value=value, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
    )


def _rock(
    name: str,
    density: float,
    density_spread: float,
    susceptibility: float,
    susceptibility_spread: float,
    proportion: float | None = None,
) -> JointPetrophysicalClassSpec:
    return JointPetrophysicalClassSpec(
        name=name,
        source="test fixture",
        proportion=proportion,
        density_contrast=_density(density),
        density_standard_deviation=_density(density_spread),
        susceptibility=_susceptibility(susceptibility),
        susceptibility_standard_deviation=_susceptibility(susceptibility_spread),
    )


HOST = _rock("host", -0.10, 0.03, 0.001, 0.0005)
INTRUSION = _rock("intrusion", 0.20, 0.05, 0.040, 0.0100)


class TestTheDeclaration:
    def test_two_rocks_in_two_properties_are_accepted(self) -> None:
        spec = JointPetrophysicalSpec(classes=(HOST, INTRUSION))

        assert [item.name for item in spec.classes] == ["host", "intrusion"]
        assert spec.alpha_pgi == 1.0

    def test_a_density_in_the_susceptibility_slot_is_refused(self) -> None:
        """The commonest way two properties get crossed is by position."""
        with pytest.raises(ValidationError, match="susceptibility must be a"):
            JointPetrophysicalClassSpec(
                name="muddle",
                source="test fixture",
                density_contrast=_density(0.1),
                density_standard_deviation=_density(0.01),
                susceptibility=_density(0.1),
                susceptibility_standard_deviation=_susceptibility(0.001),
            )

    def test_a_zero_spread_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="must be positive"):
            _rock("hard", 0.1, 0.01, 0.01, 0.0)

    def test_one_rock_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="at least two rock classes"):
            JointPetrophysicalSpec(classes=(HOST,))

    def test_proportions_must_sum_to_one(self) -> None:
        with pytest.raises(ValidationError, match="must sum to 1"):
            JointPetrophysicalSpec(
                classes=(
                    _rock("a", -0.1, 0.03, 0.001, 0.0005, proportion=0.3),
                    _rock("b", 0.2, 0.05, 0.040, 0.0100, proportion=0.3),
                )
            )

    def test_classes_declared_on_one_property_alone_are_refused(self) -> None:
        """A susceptibility class on its own is not a rock, and accepting it would let a spec
        look as though it had asked for a joint mixture."""
        single = PetrophysicalClassSpec(
            name="magnetite",
            value=_susceptibility(0.05),
            standard_deviation=_susceptibility(0.01),
            source="test fixture",
        )
        other = PetrophysicalClassSpec(
            name="host",
            value=_susceptibility(0.001),
            standard_deviation=_susceptibility(0.0005),
            source="test fixture",
        )
        with pytest.raises(ValidationError, match="rather than on one property"):
            GravMagJointInversionSpec(
                magnetics=JointMagneticsPropertySpec(
                    regularization=GravityRegularizationSpec(
                        kind=GravityRegularizationKind.PETROPHYSICAL,
                        petrophysical_classes=(other, single),
                    )
                )
            )


class TestTheMixture:
    def test_one_mixture_spans_both_properties(self) -> None:
        pytest.importorskip("simpeg")
        from discretize import TensorMesh

        from ofag.engines.simpeg.petrophysics import declared_mixture

        mesh = TensorMesh([6, 6, 4])
        active_cells = np.ones(mesh.nC, dtype=bool)
        means = np.array([[-0.10, 0.001], [0.20, 0.040]])
        spreads = np.array([[0.03, 0.0005], [0.05, 0.0100]])

        mixture = declared_mixture(mesh, active_cells, means, spreads, np.array([0.7, 0.3]))

        assert mixture.means_ == pytest.approx(means)
        # Diagonal: within a class the two properties are taken to be independent,
        # because a correlation is a measurement nobody made.
        assert mixture.covariances_.shape == (2, 2, 2)
        assert np.sqrt(np.diagonal(mixture.covariances_, axis1=1, axis2=2)) == pytest.approx(
            spreads
        )
        assert mixture.covariances_[:, 0, 1] == pytest.approx(0.0)


def test_a_joint_petrophysical_inversion_runs_and_reports_its_shared_term(tmp_path) -> None:
    pytest.importorskip("simpeg")
    gravity_observations = tmp_path / "gravity.csv"
    gravity_observations.write_text(
        "x_m,y_m,z_m,gravity_mgal\n"
        "-30.0,-30.0,5.0,0.030\n"
        "30.0,-30.0,5.0,0.042\n"
        "-30.0,30.0,5.0,0.036\n"
        "30.0,30.0,5.0,0.048\n",
        encoding="utf-8",
    )
    magnetic_observations = tmp_path / "magnetics.csv"
    magnetic_observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        "-30.0,-30.0,5.0,2.0\n"
        "30.0,-30.0,5.0,2.5\n"
        "-30.0,30.0,5.0,1.8\n"
        "30.0,30.0,5.0,2.2\n",
        encoding="utf-8",
    )
    convention = CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC")
    gravity_dataset = DatasetSpec(
        name="joint-gravity",
        coordinate_convention=convention,
        physical_quantity=QuantityType.GRAVITY_ACCELERATION,
        units="mGal",
    )
    magnetic_dataset = DatasetSpec(
        name="joint-tmi",
        coordinate_convention=convention,
        physical_quantity=QuantityType.MAGNETIC_ANOMALY,
        units="nT",
    )
    spec = RunSpec(
        plugin_id="simpeg.joint.gravmag.cross_gradient",
        engine="simpeg",
        dataset=gravity_dataset,
        datasets=(
            DataChannelSpec(
                channel_id="gravity",
                dataset=gravity_dataset,
                observations_path=str(gravity_observations),
                data_uncertainty=QuantitySpec(
                    value=1e-3, quantity_type=QuantityType.GRAVITY_ACCELERATION, unit="mGal"
                ),
            ),
            DataChannelSpec(
                channel_id="tmi",
                dataset=magnetic_dataset,
                observations_path=str(magnetic_observations),
                data_uncertainty=QuantitySpec(
                    value=0.1, quantity_type=QuantityType.MAGNETIC_ANOMALY, unit="nT"
                ),
            ),
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[30.0, 30.0, 30.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(4, 4, 3),
            origin=(-60.0, -60.0, -90.0),
        ),
        gravmag_joint_inversion=GravMagJointInversionSpec(
            gravity=JointGravityPropertySpec(),
            magnetics=JointMagneticsPropertySpec(
                inducing_field=MagneticsInducingFieldSpec(
                    inclination=QuantitySpec(
                        value=60.0, quantity_type=QuantityType.ANGLE, unit="degree"
                    ),
                    declination=QuantitySpec(
                        value=15.0, quantity_type=QuantityType.ANGLE, unit="degree"
                    ),
                ),
            ),
            petrophysical=JointPetrophysicalSpec(classes=(HOST, INTRUSION)),
            coupling=CrossGradientCouplingSpec(weight=0.0),
            optimizer=GravityOptimizerSpec(max_iterations=2, cg_max_iterations=8),
        ),
    )
    plugin = SimPEGGravMagJointPlugin()
    context = PluginContext(tmp_path / "artifacts")
    assert plugin.validate(context, spec).valid

    result = plugin.execute(context, spec)

    assert result.summary["solver"] == "joint_gravity_magnetics_cross_gradient"
    # The term the two properties share, reported beside the cross-gradient it replaces,
    # because both answer "what did the coupling cost".
    assert result.summary["phi_petrophysical"] >= 0.0

    # The smoothness stays separable even though the smallness does not: only the rocks
    # are shared.
    components = json.loads(
        (context.run_dir(spec.run_id) / "objective_components.json").read_text(encoding="utf-8")
    )
    assert components["phi_gravity_regularization"] >= 0.0
    assert components["phi_magnetics_regularization"] >= 0.0
    assert components["phi_petrophysical"] == pytest.approx(result.summary["phi_petrophysical"])


def test_a_joint_petrophysical_inversion_refuses_disagreeing_smoothness(tmp_path) -> None:
    """SimPEG's PGI gives every property the same smoothness alphas, so a spec asking for
    different ones would be silently granted neither."""
    pytest.importorskip("simpeg")

    config = GravMagJointInversionSpec(
        gravity=JointGravityPropertySpec(
            regularization=GravityRegularizationSpec(alpha_x=1.0),
        ),
        magnetics=JointMagneticsPropertySpec(
            regularization=GravityRegularizationSpec(alpha_x=4.0),
        ),
        petrophysical=JointPetrophysicalSpec(classes=(HOST, INTRUSION)),
        coupling=CrossGradientCouplingSpec(weight=0.0),
    )
    with pytest.raises(ValueError, match="must declare the same alpha_x"):
        SimPEGGravMagJointPlugin._build_petrophysical_regularization(
            None, None, None, np.ones(8, dtype=bool), 8, np.zeros(16), config, None
        )
