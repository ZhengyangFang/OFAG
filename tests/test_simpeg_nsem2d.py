"""The 2D natural-source plugin, against the layered solution it must contain."""

import numpy as np
import pytest

MU0 = 4.0e-7 * np.pi


def _length(value: float) -> dict:
    return {"value": value, "quantity_type": "length", "unit": "m"}


def _conductivity(ohm_m: float) -> dict:
    return {"value": 1.0 / ohm_m, "quantity_type": "conductivity", "unit": "S/m"}


def _observations(path, frequencies, impedance, relative=0.05):
    lines = ["frequency_hz,impedance_real_ohm,impedance_imag_ohm,uncertainty_ohm"]
    lines += [
        f"{f:.9e},{z.real:.9e},{z.imag:.9e},{relative * abs(z):.9e}"
        for f, z in zip(frequencies, impedance, strict=True)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _layered_impedance(frequencies, thicknesses, resistivities):
    """From the layered plugin, which is fed bottom-first on purpose (F023)."""
    from simpeg import maps
    from simpeg.electromagnetics import natural_source as nsem

    from ofag.plugins.simpeg_mt1d import SimPEGMT1DPlugin

    simulation, _ = SimPEGMT1DPlugin._simulation(
        nsem,
        maps,
        np.asarray(thicknesses, dtype=float),
        np.asarray(frequencies, dtype=float),
        len(resistivities),
    )
    values = simulation.dpred(np.log(1.0 / np.asarray(resistivities, dtype=float)))
    return values[0::2] + 1j * values[1::2]


def _spec(tmp_path, sites, core_cell=100.0, core_depth=3000.0, skin_depths=5.0, iterations=1):
    from ofag.core.schemas import MT2DInversionSpec

    return MT2DInversionSpec.model_validate(
        {
            "mesh": {
                "core_cell": _length(core_cell),
                "core_depth": _length(core_depth),
                "core_margin": _length(2_000.0),
                "padding_skin_depths": skin_depths,
                "padding_resistivity": _conductivity(1_000.0),
            },
            "model": {
                "initial_conductivity": _conductivity(100.0),
                "lower_bound": _conductivity(10_000.0),
                "upper_bound": _conductivity(1.0),
            },
            "optimizer": {"max_iterations": iterations},
            "sites": sites,
        }
    )


def _forward(spec, model_resistivity_ohm_m):
    """The plugin's own mesh and simulation, forward modelled on a halfspace."""
    from simpeg import maps
    from simpeg.electromagnetics import natural_source as nsem

    from ofag.plugins.simpeg_nsem2d import (
        DEFAULT_AIR_CONDUCTIVITY_S_M,
        SimPEGNSEM2DPlugin,
    )

    frequencies = np.array([0.01, 0.1, 1.0, 10.0])
    mesh, active = SimPEGNSEM2DPlugin._build_mesh(spec, frequencies)
    conductivity_map = SimPEGNSEM2DPlugin._conductivity_map(
        maps, mesh, active, DEFAULT_AIR_CONDUCTIVITY_S_M, 1.0 / model_resistivity_ohm_m
    )
    observations = {
        (site.site_id, site.mode): (
            frequencies,
            np.zeros(frequencies.size, complex),
            np.ones(frequencies.size),
        )
        for site in spec.sites
    }
    simulation, _, _ = SimPEGNSEM2DPlugin._simulation(
        nsem, mesh, conductivity_map, list(spec.sites), observations
    )
    model = np.full(int(active.sum()), np.log(1.0 / model_resistivity_ohm_m))
    values = simulation.dpred(model)
    return frequencies, values[0::2] + 1j * values[1::2], mesh, active


def _apparent_resistivity(impedance, frequencies):
    return np.abs(impedance) ** 2 / (2 * np.pi * np.asarray(frequencies) * MU0)


class TestTheMesh:
    def test_the_surface_is_at_zero_with_air_above_it(self, tmp_path) -> None:
        """Without air the electric field has nowhere to diffuse upward into and the answer
        is wrong by a factor of several, quietly."""
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin

        spec = _spec(
            tmp_path,
            [{"site_id": "A", "observations_path": str(tmp_path / "a.csv"), "distance_m": 0.0}],
        )
        mesh, active = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([0.01, 10.0]))

        top = mesh.cell_centers[:, 1].max()
        assert top > 0.0, "there is mesh above the surface"
        assert not active[mesh.cell_centers[:, 1] > 0].any(), "and none of it is model"
        assert active.any(), "and there is a model below it"

    def test_the_padding_is_in_the_mesh_and_not_in_the_model(self, tmp_path) -> None:
        """SimPEG weights the smoothness by cell volume, so a padding cell 998 km wide
        outweighs the entire core."""
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin

        spec = _spec(
            tmp_path,
            [{"site_id": "A", "observations_path": str(tmp_path / "a.csv"), "distance_m": 0.0}],
        )
        mesh, active = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([0.001, 100.0]))

        widths = mesh.h_gridded[active]
        assert widths[:, 0].max() <= 200.0 + 1e-6, "every model cell is a core cell"
        assert mesh.h_gridded[:, 0].max() > 1e5, "and the mesh still reaches out"
        assert int(active.sum()) < mesh.n_cells // 4

    def test_the_padding_reaches_several_skin_depths(self, tmp_path) -> None:
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin, skin_depth_m

        spec = _spec(
            tmp_path,
            [{"site_id": "A", "observations_path": str(tmp_path / "a.csv"), "distance_m": 0.0}],
        )
        mesh, _ = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([0.01, 10.0]))

        reach = 5.0 * skin_depth_m(1_000.0, 0.01)
        assert sum(mesh.h[0]) > 2 * reach
        assert sum(mesh.h[1]) > 2 * reach

    def test_a_lower_frequency_asks_for_a_larger_mesh(self, tmp_path) -> None:
        """The domain is a property of the data, not a number someone typed."""
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin

        spec = _spec(
            tmp_path,
            [{"site_id": "A", "observations_path": str(tmp_path / "a.csv"), "distance_m": 0.0}],
        )
        high, _ = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([1.0]))
        low, _ = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([0.001]))

        assert sum(low.h[0]) > 3 * sum(high.h[0])


class TestAgainstTheLayeredSolution:
    def test_a_halfspace_matches_the_layered_simulation(self, tmp_path) -> None:
        pytest.importorskip("simpeg")
        spec = _spec(
            tmp_path,
            [
                {
                    "site_id": "A",
                    "observations_path": str(tmp_path / "a.csv"),
                    "distance_m": 0.0,
                    "mode": "tm",
                }
            ],
        )

        frequencies, impedance, _, _ = _forward(spec, 100.0)

        recovered = _apparent_resistivity(impedance, frequencies)
        assert recovered == pytest.approx(np.full(4, 100.0), rel=0.05)

    def test_both_modes_agree_over_a_layered_earth(self, tmp_path) -> None:
        """TE and TM are different simulations and a layered earth has no strike, so they
        have to give the same answer."""
        pytest.importorskip("simpeg")
        answers = {}
        for mode in ("te", "tm"):
            spec = _spec(
                tmp_path,
                [
                    {
                        "site_id": "A",
                        "observations_path": str(tmp_path / "a.csv"),
                        "distance_m": 0.0,
                        "mode": mode,
                    }
                ],
            )
            frequencies, impedance, _, _ = _forward(spec, 100.0)
            answers[mode] = _apparent_resistivity(impedance, frequencies)

        assert answers["te"] == pytest.approx(answers["tm"], rel=0.06)


class TestTheInversion:
    def test_it_runs_and_reports_a_misfit_per_site(self, tmp_path) -> None:
        """A short run on data made from a layered earth."""
        pytest.importorskip("simpeg")
        from ofag.core.schemas import RunSpec
        from ofag.plugins.protocol import PluginContext
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin

        frequencies = np.array([0.1, 1.0])
        impedance = _layered_impedance(frequencies, [500.0], [50.0, 500.0])
        path = _observations(tmp_path / "a.csv", frequencies, impedance)

        sites = [
            {"site_id": "A", "observations_path": str(path), "distance_m": -500.0, "mode": "tm"},
            {"site_id": "B", "observations_path": str(path), "distance_m": 500.0, "mode": "tm"},
        ]
        physics = _spec(tmp_path, sites, core_cell=250.0, core_depth=2000.0, skin_depths=3.0)

        spec = RunSpec(
            schema_version="1.1",
            plugin_id=SimPEGNSEM2DPlugin.plugin_id,
            plugin_version=SimPEGNSEM2DPlugin.plugin_version,
            engine="simpeg",
            dataset={
                "name": "synthetic-2d",
                "coordinate_convention": {"crs": "LOCAL_CARTESIAN_METRIC"},
                "physical_quantity": "magnetotelluric_impedance",
                "units": "ohm",
            },
            physics=physics.model_dump(mode="json"),
        )
        plugin = SimPEGNSEM2DPlugin()
        context = PluginContext(tmp_path / "artifacts")
        assert plugin.validate(context, spec).valid

        result = plugin.execute(context, spec)

        assert result.summary["site_count"] == 2
        assert result.summary["active_cells"] > 0
        assert np.isfinite(result.summary["chi_squared_median"])
        assert {item.artifact_type for item in result.artifacts} >= {
            "model",
            "site_summary",
            "engine_log",
        }

    def test_the_air_is_not_part_of_the_model(self, tmp_path) -> None:
        """An inversion allowed to change the air would spend its freedom there, where no
        datum can contradict it."""
        pytest.importorskip("simpeg")
        from ofag.plugins.simpeg_nsem2d import SimPEGNSEM2DPlugin

        spec = _spec(
            tmp_path,
            [{"site_id": "A", "observations_path": str(tmp_path / "a.csv"), "distance_m": 0.0}],
        )
        mesh, active = SimPEGNSEM2DPlugin._build_mesh(spec, np.array([0.01, 10.0]))

        assert int(active.sum()) < mesh.n_cells
        assert int((~active).sum()) > 0
