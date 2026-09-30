"""Declaring rock classes to an inversion, and the ways that goes wrong."""

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    GravityRegularizationKind,
    GravityRegularizationSpec,
    PetrophysicalClassSpec,
    QuantitySpec,
)

pytest.importorskip("simpeg")
pytest.importorskip("sklearn")


def _class(
    name: str,
    value: float,
    spread: float,
    proportion: float | None = None,
    quantity: QuantityType = QuantityType.DENSITY_CONTRAST,
    unit: str = "g/cm^3",
) -> PetrophysicalClassSpec:
    return PetrophysicalClassSpec(
        name=name,
        value=QuantitySpec(value=value, quantity_type=quantity, unit=unit),
        standard_deviation=QuantitySpec(value=spread, quantity_type=quantity, unit=unit),
        source="test fixture",
        proportion=proportion,
    )


BASIN = _class("basin fill", -0.25, 0.05)
GRANITE = _class("granite", -0.078, 0.03)


def _spec(**overrides: object) -> GravityRegularizationSpec:
    fields: dict[str, object] = {
        "kind": GravityRegularizationKind.PETROPHYSICAL,
        "petrophysical_classes": (BASIN, GRANITE),
    }
    fields.update(overrides)
    return GravityRegularizationSpec(**fields)  # type: ignore[arg-type]


class TestTheDeclaration:
    def test_two_classes_with_no_proportions_are_accepted(self) -> None:
        spec = _spec()
        assert spec.alpha_pgi == 1.0
        assert [item.name for item in spec.petrophysical_classes] == ["basin fill", "granite"]

    def test_one_class_is_refused_because_that_is_a_reference_model(self) -> None:
        with pytest.raises(ValueError, match="at least two rock classes"):
            _spec(petrophysical_classes=(BASIN,))

    def test_classes_without_the_kind_are_refused(self) -> None:
        """Otherwise a spec carries classes it will never use, and a reader has no way to
        tell a disabled PGI from a forgotten one."""
        with pytest.raises(ValueError, match="apply only to 'petrophysical'"):
            _spec(kind=GravityRegularizationKind.L2)

    def test_two_classes_with_the_same_name_are_refused(self) -> None:
        with pytest.raises(ValueError, match="names must be distinct"):
            _spec(petrophysical_classes=(BASIN, _class("basin fill", -0.1, 0.02)))

    def test_mixing_a_density_class_with_a_susceptibility_one_is_refused(self) -> None:
        magnetic = _class(
            "magnetite", 0.05, 0.01, quantity=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
        )
        with pytest.raises(ValueError, match="all measure the same quantity"):
            _spec(petrophysical_classes=(BASIN, magnetic))

    def test_a_spread_of_zero_is_refused(self) -> None:
        """A class with no spread is a hard constraint wearing a prior's clothes."""
        with pytest.raises(ValueError, match="standard_deviation must be positive"):
            _class("basement", -0.02, 0.0)

    def test_a_spread_in_another_quantity_than_its_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match="same quantity as its value"):
            PetrophysicalClassSpec(
                name="granite",
                value=QuantitySpec(
                    value=-0.078, quantity_type=QuantityType.DENSITY_CONTRAST, unit="g/cm^3"
                ),
                standard_deviation=QuantitySpec(
                    value=0.03, quantity_type=QuantityType.SUSCEPTIBILITY, unit="dimensionless"
                ),
                source="test fixture",
            )

    def test_proportions_are_all_or_none(self) -> None:
        """Half a mixture's shares stated is not a mixture, and completing it would be the
        framework inventing the number that was left out."""
        with pytest.raises(ValueError, match="either every petrophysical class"):
            _spec(petrophysical_classes=(BASIN, _class("granite", -0.078, 0.03, proportion=0.6)))

    def test_proportions_that_do_not_sum_to_one_are_refused(self) -> None:
        with pytest.raises(ValueError, match="must sum to 1"):
            _spec(
                petrophysical_classes=(
                    _class("basin fill", -0.25, 0.05, proportion=0.4),
                    _class("granite", -0.078, 0.03, proportion=0.4),
                )
            )


class TestTheMixture:
    """`declared_mixture` has to fit before it can overwrite, and the order in which SimPEG's
    own helpers are called decides whether it is the declared mixture or another one."""

    @staticmethod
    def _mesh_and_cells() -> tuple[object, np.ndarray]:
        from discretize import TensorMesh

        mesh = TensorMesh([8, 8, 6])
        active_cells = np.ones(mesh.nC, dtype=bool)
        active_cells[:10] = False
        return mesh, active_cells

    def test_the_mixture_holds_what_was_declared_and_not_what_was_fitted(self) -> None:
        from ofag.engines.simpeg.petrophysics import declared_mixture

        mesh, active_cells = self._mesh_and_cells()
        means = np.array([-0.25, -0.078, 0.0])
        spreads = np.array([0.05, 0.03, 0.02])
        proportions = np.array([0.3, 0.2, 0.5])

        mixture = declared_mixture(mesh, active_cells, means, spreads, proportions)

        assert mixture.means_.ravel() == pytest.approx(means)
        assert np.sqrt(mixture.covariances_.ravel()) == pytest.approx(spreads)
        assert mixture.weights_.ravel() == pytest.approx(proportions)

    def test_each_class_precision_matches_its_own_spread(self) -> None:
        """The failure this guards against is silent."""
        from ofag.engines.simpeg.petrophysics import declared_mixture

        mesh, active_cells = self._mesh_and_cells()
        spreads = np.array([0.05, 0.03, 0.02])
        mixture = declared_mixture(
            mesh,
            active_cells,
            np.array([-0.25, -0.078, 0.0]),
            spreads,
            np.array([0.3, 0.2, 0.5]),
        )

        assert mixture.precisions_.ravel() == pytest.approx(1.0 / spreads**2)

    def test_the_objective_is_smallest_at_a_declared_class_value(self) -> None:
        from simpeg import maps, regularization

        from ofag.engines.simpeg.petrophysics import declared_mixture

        mesh, active_cells = self._mesh_and_cells()
        active_count = int(active_cells.sum())
        mixture = declared_mixture(
            mesh,
            active_cells,
            np.array([-0.25, -0.078, 0.0]),
            np.array([0.05, 0.03, 0.02]),
            np.array([0.3, 0.2, 0.5]),
        )
        term = regularization.PGI(
            mesh,
            mixture,
            wiresmap=maps.Wires(("model", active_count)),
            maplist=[maps.IdentityMap(nP=active_count)],
            active_cells=active_cells,
            alpha_x=0.0,
            alpha_y=0.0,
            alpha_z=0.0,
        )

        at_a_class = term(np.full(active_count, -0.25))
        off_it = term(np.full(active_count, -0.16))

        assert at_a_class == pytest.approx(0.0, abs=1e-9)
        assert off_it > 1.0

    def test_a_mesh_with_fewer_cells_than_classes_is_refused(self) -> None:
        from discretize import TensorMesh

        from ofag.engines.simpeg.petrophysics import declared_mixture

        mesh = TensorMesh([2, 1, 1])
        with pytest.raises(ValueError, match="at least 3 active cells"):
            declared_mixture(
                mesh,
                np.ones(mesh.nC, dtype=bool),
                np.array([-0.25, -0.078, 0.0]),
                np.array([0.05, 0.03, 0.02]),
                np.array([0.3, 0.2, 0.5]),
            )


def test_petrophysical_regularization_works_for_magnetics_too(tmp_path) -> None:
    """The same regularization, on the other property."""
    from ofag.core.schemas import (
        CoordinateConvention,
        DatasetSpec,
        GravityOptimizerSpec,
        MagneticsInducingFieldSpec,
        MagneticsInversionSpec,
        MagneticsModelSpec,
        RunSpec,
        TensorMeshSpec,
    )
    from ofag.plugins.protocol import PluginContext
    from ofag.plugins.simpeg_magnetics import SimPEGMagnetics3DPlugin

    observations = tmp_path / "observations.csv"
    observations.write_text(
        "x_m,y_m,z_m,tmi_nt\n"
        + "\n".join(
            f"{x},{y},10.0,{5.0 + x * y / 40_000:.4f}"
            for x in (-60.0, -20.0, 20.0, 60.0)
            for y in (-60.0, -20.0, 20.0, 60.0)
        ),
        encoding="utf-8",
    )

    spec = RunSpec(
        plugin_id="simpeg.pf.magnetics3d",
        engine="simpeg",
        dataset=DatasetSpec(
            name="magnetics-pgi",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.MAGNETIC_ANOMALY,
            units="nT",
        ),
        mesh=TensorMeshSpec(
            cell_size=QuantitySpec(
                value=[40.0, 40.0, 40.0], quantity_type=QuantityType.LENGTH, unit="m"
            ),
            shape=(5, 5, 3),
            origin=(-100.0, -100.0, -120.0),
        ),
        magnetics_inversion=MagneticsInversionSpec(
            inducing_field=MagneticsInducingFieldSpec(
                inclination=QuantitySpec(
                    value=60.0, quantity_type=QuantityType.ANGLE, unit="degree"
                ),
                declination=QuantitySpec(
                    value=15.0, quantity_type=QuantityType.ANGLE, unit="degree"
                ),
            ),
            model=MagneticsModelSpec(),
            regularization=GravityRegularizationSpec(
                kind=GravityRegularizationKind.PETROPHYSICAL,
                petrophysical_classes=(
                    _class(
                        "host",
                        0.0,
                        0.002,
                        quantity=QuantityType.SUSCEPTIBILITY,
                        unit="dimensionless",
                    ),
                    _class(
                        "magnetite",
                        0.05,
                        0.01,
                        quantity=QuantityType.SUSCEPTIBILITY,
                        unit="dimensionless",
                    ),
                ),
            ),
            optimizer=GravityOptimizerSpec(max_iterations=4),
        ),
        parameters={
            "observations_path": str(observations),
            "data_uncertainty": QuantitySpec(
                value=0.5, quantity_type=QuantityType.MAGNETIC_ANOMALY, unit="nT"
            ),
        },
    )
    plugin = SimPEGMagnetics3DPlugin()
    context = PluginContext(tmp_path / "artifacts")
    assert plugin.validate(context, spec).valid

    result = plugin.execute(context, spec)
    recovered = np.load(
        context.run_dir(spec.run_id) / "recovered_susceptibility.npy", allow_pickle=False
    )

    assert result.summary["engine"] == "simpeg"
    assert np.isfinite(recovered).all()


def test_a_density_class_is_refused_for_a_magnetic_inversion() -> None:
    """The check that makes the branch above worth having."""
    from ofag.core.schemas import GravityInversionSpec, MagneticsInversionSpec
    from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin

    classes = (BASIN, GRANITE)
    regularization = GravityRegularizationSpec(
        kind=GravityRegularizationKind.PETROPHYSICAL, petrophysical_classes=classes
    )
    # The same spec is fine for gravity, which is what makes the mistake easy.
    assert GravityInversionSpec(regularization=regularization).regularization is regularization

    with pytest.raises(ValueError, match="but this inversion recovers"):
        SimPEGGravity3DPlugin._build_regularization(
            None,
            None,
            np.ones(4, dtype=bool),
            np.zeros(4),
            MagneticsInversionSpec(regularization=regularization),
        )
