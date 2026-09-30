"""The pre-flight that stops a run whose engine does not mean what the plugin assumes."""

import numpy as np
import pytest

from ofag.core.constants import QuantityType
from ofag.core.conventions import (
    UNVERIFIED,
    ConventionCheck,
    ConventionResult,
    engine_fingerprint,
    forget,
    run_checks,
)
from ofag.core.schemas import CoordinateConvention, DatasetSpec


def _check(name: str, passed: bool) -> ConventionCheck:
    return ConventionCheck(
        name=name,
        catches="a made-up error, for the mechanism's own tests",
        against="a constant",
        run=lambda: ConventionResult(passed=passed, detail=f"{name} returned {passed}"),
    )


class TestTheMechanism:
    def setup_method(self) -> None:
        forget()

    def test_a_passing_plugin_passes(self) -> None:
        outcome = run_checks("p", "fp", (_check("a", True), _check("b", True)))

        assert outcome.passed
        assert outcome.failures == ()
        assert outcome.unverified_reason is None

    def test_one_failure_fails_the_whole_outcome(self) -> None:
        outcome = run_checks("p", "fp", (_check("a", True), _check("b", False)))

        assert not outcome.passed
        assert [check.name for check, _ in outcome.failures] == ["b"]

    def test_a_check_that_raises_has_not_passed(self) -> None:
        """A convention check that cannot run is not a convention check that passed, and the
        difference matters: the first version of this let an exception through and the run
        went ahead."""

        def explode() -> ConventionResult:
            raise RuntimeError("the engine moved")

        outcome = run_checks(
            "p",
            "fp",
            (ConventionCheck(name="a", catches="x", against="y", run=explode),),
        )

        assert not outcome.passed
        assert "the engine moved" in outcome.failures[0][1].detail

    def test_declaring_nothing_is_reported_rather_than_silent(self) -> None:
        outcome = run_checks("p", "fp", UNVERIFIED)

        assert outcome.unverified_reason is not None
        assert outcome.results == ()

    def test_the_result_is_cached_per_engine_version(self) -> None:
        """It runs before every inversion, so it is paid once -- and again when the engine
        changes, which is the event that would silently move a convention under us."""
        calls = []

        def counted() -> ConventionResult:
            calls.append(1)
            return ConventionResult(passed=True, detail="ran")

        check = ConventionCheck(name="a", catches="x", against="y", run=counted)

        run_checks("p", "simpeg==1.0", (check,))
        run_checks("p", "simpeg==1.0", (check,))
        assert len(calls) == 1

        run_checks("p", "simpeg==1.1", (check,))
        assert len(calls) == 2

    def test_the_fingerprint_names_the_versions_it_depends_on(self) -> None:
        fingerprint = engine_fingerprint("numpy", "a-package-that-is-not-installed")

        assert "numpy==" in fingerprint
        assert "a-package-that-is-not-installed==absent" in fingerprint


class TestItActuallyStopsARun:
    def setup_method(self) -> None:
        forget()

    @staticmethod
    def _registry_and_spec(tmp_path, checks):
        """A plugin with no physics of its own, so what is under test is the pre-flight and
        not any one method's configuration."""
        from ofag.core.schemas import (
            CapabilityManifest,
            ResourceEstimate,
            RunResult,
            RunSpec,
            ValidationReport,
        )
        from ofag.plugins.registry import PluginRegistry
        from ofag.services.run_service import RunService

        class Fake:
            plugin_id = "test.conventions.probe"
            plugin_version = "0.1.0"

            def physics_model(self):
                return None

            def manifest(self):
                return CapabilityManifest(
                    plugin_id=self.plugin_id,
                    plugin_version=self.plugin_version,
                    supported_quantities=(QuantityType.GRAVITY_ACCELERATION,),
                    supported_meshes=("Tensor3D",),
                    supports_parallel=False,
                    supports_restart=False,
                    limitations=(),
                )

            def conventions(self):
                return checks

            def validate(self, context, spec):
                return ValidationReport(valid=True, issues=())

            def estimate_resources(self, context, spec):
                return ResourceEstimate(cpu_cores=1, memory_mb=1, estimated_seconds=1)

            def execute(self, context, spec):
                return RunResult(run_id=spec.run_id, summary={}, artifacts=())

        registry = PluginRegistry()
        registry.register(Fake())
        spec = RunSpec(
            plugin_id=Fake.plugin_id,
            engine="simpeg",
            dataset=DatasetSpec(
                name="probe",
                coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
                physical_quantity=QuantityType.GRAVITY_ACCELERATION,
                units="mGal",
            ),
        )
        return RunService(artifact_root=tmp_path / "runs", registry=registry), spec

    def test_validate_refuses_a_spec_whose_conventions_fail(self, tmp_path) -> None:
        """The property the whole mechanism is for: a plugin that is otherwise entirely valid
        does not get to run."""
        runs, spec = self._registry_and_spec(
            tmp_path, (_check("a gravity high is more mass", False),)
        )

        report = runs.validate(spec)

        assert not report.valid
        failure = next(issue for issue in report.issues if issue.field == "conventions")
        assert "a gravity high is more mass" in failure.message
        assert "Do not run an inversion until it passes" in failure.remediation

    def test_a_passing_plugin_is_not_held_up(self, tmp_path) -> None:
        runs, spec = self._registry_and_spec(tmp_path, (_check("fine", True),))

        report = runs.validate(spec)

        assert report.valid
        assert not any(issue.field.startswith("conventions") for issue in report.issues)

    def test_an_unverified_plugin_is_reported_but_not_blocked(self, tmp_path) -> None:
        """Blocking would mean no ERT or seismic run could start, and a rule that stops the
        work gets deleted."""
        runs, spec = self._registry_and_spec(tmp_path, UNVERIFIED)

        report = runs.validate(spec)

        assert report.valid
        assert any(issue.field == "conventions.unverified" for issue in report.issues)


class TestTheCheckWouldHaveCaughtIt:
    """The layered magnetotelluric check, against the bug it was written for."""

    def setup_method(self) -> None:
        forget()

    def test_the_real_plugin_passes(self) -> None:
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_mt1d import SimPEGMT1DPlugin

        outcome = run_checks("mt1d", engine_fingerprint("simpeg"), SimPEGMT1DPlugin().conventions())

        assert outcome.passed, [result.detail for _, result in outcome.failures]

    def test_feeding_the_simulation_surface_first_fails_the_check(self) -> None:
        """The bug, put back. A halfspace still reads 100 ohm.m at -135 degrees -- which is
        why a symmetric case is not enough -- and the layered case comes out at 10 ohm.m
        where the recursion says 693."""
        pytest.importorskip("simpeg")
        from simpeg import maps
        from simpeg.electromagnetics import natural_source as nsem

        from ofag.engines.simpeg import conventions

        def upside_down(
            thicknesses: list[float], resistivities: list[float], frequency: float
        ) -> complex:
            location = np.array([[0.0, 0.0, 0.0]])
            source = nsem.sources.Planewave(
                [
                    nsem.receivers.Impedance(
                        locations_e=location,
                        locations_h=location,
                        orientation="xy",
                        component=component,
                    )
                    for component in ("real", "imag")
                ],
                frequency=float(frequency),
            )
            simulation = nsem.simulation_1d.Simulation1DRecursive(
                survey=nsem.Survey([source]),
                thicknesses=np.asarray(thicknesses, dtype=float),
                sigmaMap=maps.ExpMap(nP=len(resistivities)),
            )
            values = simulation.dpred(np.log(1.0 / np.asarray(resistivities, dtype=float)))
            return complex(values[0] + 1j * values[1])

        order = conventions.layered_mt_layer_order(upside_down).run()
        halfspace = conventions.layered_mt_halfspace(upside_down).run()

        assert not order.passed, "the asymmetric case catches it"
        assert halfspace.passed, "and the symmetric one does not, which is the lesson"
        assert "693" in order.detail and "10." in order.detail
