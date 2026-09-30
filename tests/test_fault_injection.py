"""Breaking each convention on purpose, to see whether its check notices."""

import numpy as np
import pytest

pytest.importorskip("pygimli")


def _fails(check, detail_contains: str = "") -> None:
    """Run a check that should now be broken, and say so usefully."""
    result = check.run()

    assert not result.passed, f"{check.name!r} passed with its own fault injected"
    assert result.detail, f"{check.name!r} failed and said nothing"
    if detail_contains:
        assert detail_contains in result.detail


class TestResistivityConventions:
    """`ofag.engines.pygimli.conventions`, injected at `_forward`."""

    def test_the_halfspace_check_catches_an_apparent_resistivity(self, monkeypatch) -> None:
        """The fault it names: the engine returning an apparent resistivity where the plugin
        expects a transfer resistance."""
        from ofag.engines.pygimli import conventions

        honest = conventions._forward
        monkeypatch.setattr(
            conventions,
            "_forward",
            lambda quadrupoles: honest(quadrupoles) * conventions._geometric_factor(quadrupoles),
        )

        _fails(conventions.halfspace_apparent_resistivity())

    def test_the_halfspace_check_passes_when_nothing_is_broken(self) -> None:
        """The other half: a check that fails on a fault and also on the truth is a check
        that fails."""
        from ofag.engines.pygimli import conventions

        assert conventions.halfspace_apparent_resistivity().run().passed

    def test_the_order_check_catches_a_resistance_that_does_not_negate(self, monkeypatch) -> None:
        """A quadrupole whose electrodes were sorted, or a file read as B A M N."""
        from ofag.engines.pygimli import conventions

        honest = conventions._forward
        monkeypatch.setattr(
            conventions, "_forward", lambda quadrupoles: np.abs(honest(quadrupoles))
        )

        _fails(conventions.electrode_order_within_a_pair())


class TestTraveltimeConventions:
    """`ofag.engines.pygimli.traveltime_conventions`, injected at `_forward`."""

    def test_the_direct_wave_check_catches_milliseconds(self, monkeypatch) -> None:
        """A factor of a thousand, which an inversion absorbs into the velocity scale and
        reports a healthy misfit for."""
        from ofag.engines.pygimli import traveltime_conventions as tt

        honest = tt._forward
        monkeypatch.setattr(
            tt, "_forward", lambda mesh, scheme, velocity: honest(mesh, scheme, velocity) * 1e3
        )

        _fails(tt.homogeneous_traveltime_is_offset_over_velocity())

    def test_the_direct_wave_check_catches_a_solver_that_runs_fast(self, monkeypatch) -> None:
        """A shortest-path solver may be slow and not fast: its rays bend only at nodes, so
        every time it returns is too long."""
        from ofag.engines.pygimli import traveltime_conventions as tt

        honest = tt._forward
        monkeypatch.setattr(
            tt, "_forward", lambda mesh, scheme, velocity: honest(mesh, scheme, velocity) * 0.9
        )

        _fails(tt.homogeneous_traveltime_is_offset_over_velocity())

    def test_the_head_wave_check_catches_an_engine_that_never_refracts(self, monkeypatch) -> None:
        """A solver confined to the top layer, or a mesh whose markers never reached the
        forward operator."""
        from ofag.engines.pygimli import traveltime_conventions as tt

        honest = tt._forward
        monkeypatch.setattr(
            tt,
            "_forward",
            lambda mesh, scheme, velocity: honest(
                mesh, scheme, {marker: tt._TOP_VELOCITY for marker in velocity}
            ),
        )

        _fails(tt.two_layer_traveltime_follows_the_refraction_equation())

    def test_the_head_wave_check_passes_on_a_working_engine(self) -> None:
        from ofag.engines.pygimli import traveltime_conventions as tt

        assert tt.two_layer_traveltime_follows_the_refraction_equation().run().passed


class TestPotentialFieldConventions:
    """`ofag.engines.simpeg.conventions`, injected at the flip itself."""

    def test_the_gravity_check_catches_an_unflipped_z_up_field(self, monkeypatch) -> None:
        """Check the gravity sign conversion."""
        pytest.importorskip("simpeg")
        from ofag.engines.simpeg import conventions

        monkeypatch.setattr(
            conventions, "gravity_anomaly_from_simpeg", lambda gz: np.asarray(gz, dtype=float)
        )

        _fails(conventions.gravity_sign())

    def test_the_placement_check_catches_a_transposed_axis(self, monkeypatch) -> None:
        """Easting and northing swapped between the model vector and the mesh, which moves
        the whole model and leaves the misfit plausible."""
        pytest.importorskip("simpeg")
        from ofag.engines.simpeg import conventions

        honest = conventions._gravity_of
        monkeypatch.setattr(conventions, "_gravity_of", lambda east, north: honest(north, east))

        _fails(conventions.potential_field_placement())


def test_every_check_that_was_injected_is_one_the_project_declares() -> None:
    """A fault injected into a check nothing uses measures nothing."""
    from ofag.core.conventions import ConventionCheck
    from ofag.plugins.registry import default_registry

    declared = set()
    for plugin in default_registry().all():
        got = getattr(plugin, "conventions", lambda: ())()
        # Three plugins declare UNVERIFIED instead of checks, which is a sentinel object
        # rather than an empty tuple.
        if isinstance(got, tuple) and all(isinstance(c, ConventionCheck) for c in got):
            declared |= {check.name for check in got}
    injected = {
        "K times R is the halfspace, at every spacing",
        "swapping A and B negates the resistance",
        "a direct wave takes offset over velocity",
        "beyond the crossover the arrival is the head wave",
        "a gravity high is more mass",
        "the gravity anomaly peaks over its source",
    }

    assert injected <= declared, f"not declared by any plugin: {sorted(injected - declared)}"
    # Six of thirteen.
    assert len(declared) == 13
    assert len(injected) == 6
