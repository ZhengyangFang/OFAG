"""Two-dimensional natural-source inversion along one profile."""

import json
import logging
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from ofag.core.constants import QuantityType
from ofag.core.conventions import ConventionCheck, ConventionResult
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    MT2DInversionSpec,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.plugins.protocol import PluginContext, configuration_field

FREQUENCY_COLUMN = "frequency_hz"
REAL_COLUMN = "impedance_real_ohm"
IMAGINARY_COLUMN = "impedance_imag_ohm"
UNCERTAINTY_COLUMN = "uncertainty_ohm"

#: Air is given a small conductivity rather than none, because zero makes the system
#: singular.
DEFAULT_AIR_CONDUCTIVITY_S_M = 1e-8

#: The resistivity the padding reach is computed at when the caller states no other.
DEFAULT_PADDING_RESISTIVITY_OHM_M = 1_000.0


def skin_depth_m(resistivity_ohm_m: float, frequency_hz: float) -> float:
    """The usual 503 sqrt(rho / f), which is what sets every mesh dimension here."""
    return 503.0 * float(np.sqrt(resistivity_ohm_m / frequency_hz))


class SimPEGNSEM2DPlugin:
    """One two-dimensional conductivity section from a profile of sites."""

    plugin_id = "simpeg.nsem.mt2d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return MT2DInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> MT2DInversionSpec | None:
        return spec.physics_as(MT2DInversionSpec)

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.MAGNETOTELLURIC_IMPEDANCE,),
            supported_meshes=("Tensor2D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "One profile, flat topography: the surface is a plane at z = 0.",
                "The strike direction is the caller's; nothing here estimates it.",
                "Static shift and anisotropy are not modelled.",
                "Tipper is not fitted.",
                "Install with `uv sync --extra simpeg`; SimPEG is an optional backend dependency.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if find_spec("simpeg") is None:
            issues.append(
                ValidationIssue(
                    field="environment",
                    message="SimPEG is not installed",
                    remediation="run `uv sync --extra simpeg` before submitting this plugin",
                )
            )
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message=f"{self.plugin_id} requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        config = self._configuration(spec)
        if config is None:
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "physics"),
                    message="a 2D natural-source inversion requires its mesh, model and sites",
                    remediation="provide mesh, model and sites",
                )
            )
            return ValidationReport(valid=not issues, issues=tuple(issues))
        for site in config.sites:
            try:
                self._load_observations(Path(site.observations_path))
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        field=f"physics.sites.{site.site_id}.observations_path",
                        message=str(error),
                        remediation=(
                            "provide a CSV with ascending positive frequency_hz and a "
                            "complex impedance in ohms"
                        ),
                    )
                )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (
            ConventionCheck(
                name="the 2D simulation contains the layered one",
                catches=(
                    "a mesh with no air above the surface, or one smaller than a skin depth, "
                    "either of which returns a confident wrong answer rather than a noisy one"
                ),
                against="the layered simulation, over ground that does not vary along the profile",
                run=self._check_against_layered,
            ),
        )

    @classmethod
    def _check_against_layered(cls) -> ConventionResult:
        from simpeg import maps  # type: ignore[import-untyped]
        from simpeg.electromagnetics import natural_source as nsem  # type: ignore[import-untyped]

        from ofag.core.schemas import MT2DInversionSpec
        from ofag.engines.simpeg.conventions import MU0, mt_analytic_impedance

        frequency = 1.0
        resistivity = 100.0
        spec = MT2DInversionSpec.model_validate(
            {
                "mesh": {
                    "core_cell": {"value": 200.0, "quantity_type": "length", "unit": "m"},
                    "core_depth": {"value": 2000.0, "quantity_type": "length", "unit": "m"},
                    "core_margin": {"value": 1000.0, "quantity_type": "length", "unit": "m"},
                    "padding_skin_depths": 3.0,
                },
                "model": {
                    "initial_conductivity": {
                        "value": 0.01,
                        "quantity_type": "conductivity",
                        "unit": "S/m",
                    },
                    "lower_bound": {
                        "value": 1e-4,
                        "quantity_type": "conductivity",
                        "unit": "S/m",
                    },
                    "upper_bound": {"value": 1.0, "quantity_type": "conductivity", "unit": "S/m"},
                },
                "sites": [{"site_id": "probe", "observations_path": __file__, "distance_m": 0.0}],
            }
        )
        band = np.array([frequency])
        mesh, active = cls._build_mesh(spec, band)
        conductivity_map = cls._conductivity_map(
            maps, mesh, active, DEFAULT_AIR_CONDUCTIVITY_S_M, 1.0 / resistivity
        )
        observations = {
            ("probe", "tm"): (band, np.zeros(1, dtype=complex), np.ones(1)),
        }
        simulation, _, _ = cls._simulation(
            nsem, mesh, conductivity_map, list(spec.sites), observations
        )
        values = simulation.dpred(np.full(int(active.sum()), np.log(1.0 / resistivity)))
        actual = complex(values[0] + 1j * values[1])
        expected = mt_analytic_impedance(frequency, [1000.0], [resistivity, resistivity])
        scale = 2.0 * np.pi * frequency * MU0
        got, want = abs(actual) ** 2 / scale, abs(expected) ** 2 / scale
        return ConventionResult(
            passed=bool(abs(got / want - 1.0) < 0.1),
            detail=(
                f"a {resistivity:.0f} ohm.m halfspace at {frequency:.0f} Hz: the layered "
                f"solution says {want:.1f} ohm.m, the 2D mesh says {got:.1f}"
            ),
        )

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = self._configuration(spec)
        if config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=512, estimated_seconds=60)
        frequencies: set[float] = set()
        for site in config.sites:
            try:
                band, _, _ = self._load_observations(Path(site.observations_path))
            except ValueError:
                continue
            frequencies.update(float(f) for f in band)
        # One sparse factorisation per frequency per iteration, and the mesh is the same
        # for all of them, so the cost is frequencies times iterations.
        solves = max(1, len(frequencies)) * config.optimizer.max_iterations
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=2_048,
            estimated_seconds=max(60, 4 * solves),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = self._configuration(spec)
        assert config is not None

        from simpeg import data as simpeg_data
        from simpeg import (
            data_misfit,
            directives,
            inverse_problem,
            inversion,
            maps,
            objective_function,
            optimization,
            regularization,
        )
        from simpeg.electromagnetics import (
            natural_source as nsem,
        )

        run_dir = context.run_dir(spec.run_id)
        observations: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]] = {
            (site.site_id, str(site.mode)): self._load_observations(Path(site.observations_path))
            for site in config.sites
        }
        band = np.unique(
            np.concatenate([frequencies for frequencies, _, _ in observations.values()])
        )
        mesh, active = self._build_mesh(config, band)
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=0,
                message=(
                    f"mesh {mesh.shape_cells[0]} x {mesh.shape_cells[1]} = {mesh.n_cells:,} cells, "
                    f"{sum(mesh.h[0]) / 1e3:.0f} x {sum(mesh.h[1]) / 1e3:.0f} km, "
                    f"{int(active.sum()):,} below the surface"
                ),
            )
        )

        start = float(self._conductivity(config.model.initial_conductivity))
        lower = float(self._conductivity(config.model.lower_bound))
        upper = float(self._conductivity(config.model.upper_bound))
        reference = (
            start
            if config.model.reference_conductivity is None
            else float(self._conductivity(config.model.reference_conductivity))
        )
        air = (
            DEFAULT_AIR_CONDUCTIVITY_S_M
            if config.mesh.air_conductivity is None
            else float(self._conductivity(config.mesh.air_conductivity))
        )

        # The model lives on the core cells.
        conductivity_map = self._conductivity_map(maps, mesh, active, air, reference)

        misfits: list[Any] = []
        owners: list[np.ndarray] = []
        rows: list[dict[str, Any]] = []
        index_of: dict[tuple[str, str], int] = {
            (site.site_id, str(site.mode)): n for n, site in enumerate(config.sites)
        }
        for site in config.sites:
            frequencies, _, _ = observations[(site.site_id, str(site.mode))]
            rows.append(
                {
                    "site_id": site.site_id,
                    "mode": site.mode,
                    "distance_m": site.distance_m,
                    "frequency_count": int(frequencies.size),
                    "chi_squared": float("nan"),
                }
            )

        engine_log = StringIO()
        simpeg_logger = logging.getLogger("simpeg")
        previous = simpeg_logger.disabled
        simpeg_logger.disabled = True
        try:
            with redirect_stdout(engine_log), redirect_stderr(engine_log):
                # One simulation per mode, not per site.
                for mode in ("te", "tm"):
                    group = [site for site in config.sites if site.mode == mode]
                    if not group:
                        continue
                    simulation, survey, owner = self._simulation(
                        nsem, mesh, conductivity_map, group, observations
                    )
                    observed, deviation = self._assemble(group, observations)
                    misfits.append(
                        data_misfit.L2DataMisfit(
                            simulation=simulation,
                            data=simpeg_data.Data(
                                survey, dobs=observed, standard_deviation=deviation
                            ),
                        )
                    )
                    owners.append(np.asarray([index_of[key] for key in owner], dtype=int))

                total = misfits[0]
                for extra in misfits[1:]:
                    total = total + extra
                if not isinstance(total, objective_function.ComboObjectiveFunction):
                    total = objective_function.ComboObjectiveFunction(misfits)

                smallness = regularization.WeightedLeastSquares(
                    mesh=mesh,
                    active_cells=active,
                    alpha_s=config.regularization.alpha_s,
                    # Never None on either axis (F021).
                    alpha_x=config.regularization.alpha_y,
                    alpha_y=config.regularization.alpha_z,
                    reference_model=np.full(int(active.sum()), np.log(reference)),
                )
                optimizer = optimization.ProjectedGNCG(
                    maxIter=config.optimizer.max_iterations,
                    lower=np.log(lower),
                    upper=np.log(upper),
                    maxIterLS=config.optimizer.max_line_search_iterations,
                    cg_maxiter=config.optimizer.cg_max_iterations,
                    cg_rtol=config.optimizer.cg_relative_tolerance,
                )
                problem = inverse_problem.BaseInvProblem(total, smallness, optimizer)
                steps: list[Any] = [
                    directives.BetaEstimate_ByEig(
                        beta0_ratio=config.beta.beta0_ratio, random_seed=spec.seed
                    ),
                    directives.BetaSchedule(
                        coolingFactor=config.beta.cooling_factor,
                        coolingRate=config.beta.cooling_rate,
                    ),
                ]
                if config.directives.target_chi_factor is not None:
                    steps.append(
                        directives.TargetMisfit(chifact=config.directives.target_chi_factor)
                    )
                recovered = inversion.BaseInversion(problem, directiveList=steps).run(
                    np.full(int(active.sum()), np.log(start))
                )

                squared: dict[int, list[float]] = {n: [] for n in range(len(rows))}
                for misfit, belongs_to in zip(misfits, owners, strict=True):
                    predicted = misfit.simulation.dpred(recovered)
                    residual = (predicted - misfit.data.dobs) / misfit.data.standard_deviation
                    for value, site_index in zip(residual**2, belongs_to, strict=True):
                        squared[int(site_index)].append(float(value))
                for index, row in enumerate(rows):
                    row["chi_squared"] = (
                        float(np.mean(squared[index])) if squared[index] else float("nan")
                    )
                    context.emit(
                        RunEvent(
                            run_id=spec.run_id,
                            event_type="iteration",
                            iteration=index + 1,
                            message=f"{row['site_id']} {row['mode']} fitted",
                        )
                    )
        finally:
            simpeg_logger.disabled = previous

        section = np.full(mesh.n_cells, air)
        section[active] = np.exp(recovered)
        return self._write(spec, context, run_dir, mesh, active, section, rows, engine_log)

    # -- the pieces ----------------------------------------------------------

    @staticmethod
    def _build_mesh(config: MT2DInversionSpec, frequencies: np.ndarray) -> tuple[Any, np.ndarray]:
        """A tensor mesh with air above, and padding measured in skin depths."""
        from discretize import TensorMesh  # type: ignore[import-untyped]

        cell = float(
            canonicalize_quantity(
                config.mesh.core_cell.value, config.mesh.core_cell.unit, QuantityType.LENGTH
            )
        )
        depth = float(
            canonicalize_quantity(
                config.mesh.core_depth.value, config.mesh.core_depth.unit, QuantityType.LENGTH
            )
        )
        margin = float(
            canonicalize_quantity(
                config.mesh.core_margin.value, config.mesh.core_margin.unit, QuantityType.LENGTH
            )
        )
        resistivity = (
            DEFAULT_PADDING_RESISTIVITY_OHM_M
            if config.mesh.padding_resistivity is None
            else 1.0
            / float(
                canonicalize_quantity(
                    config.mesh.padding_resistivity.value,
                    config.mesh.padding_resistivity.unit,
                    QuantityType.CONDUCTIVITY,
                )
            )
        )
        reach = config.mesh.padding_skin_depths * skin_depth_m(
            resistivity, float(np.min(frequencies))
        )

        distances = np.array([site.distance_m for site in config.sites], dtype=float)
        width = float(distances.max() - distances.min()) + 2.0 * margin
        across = max(1, int(np.ceil(width / cell)))
        down = max(1, int(np.ceil(depth / cell)))

        factor = config.mesh.padding_factor
        count, size, grown = 0, cell, 0.0
        while grown < reach and count < 60:
            size *= factor
            grown += size
            count += 1

        mesh = TensorMesh(
            [
                [(cell, count, -factor), (cell, across), (cell, count, factor)],
                [(cell, count, -factor), (cell, down), (cell, count, factor)],
            ]
        )
        # The surface is at z = 0: the padding below and the core are the earth, and
        # everything above them is air.
        earth = float(np.sum(mesh.h[1][: count + down]))
        centre = 0.5 * float(distances.max() + distances.min())
        mesh.origin = np.r_[centre - 0.5 * float(np.sum(mesh.h[0])), -earth]

        # The model is the core, not everything below the surface.
        centres = mesh.cell_centers
        active = (
            (centres[:, 1] < 0.0)
            & (centres[:, 1] > -depth)
            & (centres[:, 0] > distances.min() - margin)
            & (centres[:, 0] < distances.max() + margin)
        )
        return mesh, np.asarray(active)

    @staticmethod
    def _conductivity_map(
        maps: Any, mesh: Any, active: np.ndarray, air: float, background: float
    ) -> Any:
        """Put the model on the core cells and fix everything else."""
        fixed = np.where(mesh.cell_centers[:, 1] < 0.0, background, air)
        return maps.InjectActiveCells(mesh, active, fixed[~active]) * maps.ExpMap(
            nP=int(active.sum())
        )

    @staticmethod
    def _frequency_groups(
        group: list[Any],
        observations: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> list[tuple[float, list[Any]]]:
        """Which sites carry each frequency, in ascending order."""
        bands: dict[float, list[Any]] = {}
        for site in group:
            frequencies, _, _ = observations[(site.site_id, str(site.mode))]
            for frequency in frequencies:
                bands.setdefault(float(frequency), []).append(site)
        return [(frequency, bands[frequency]) for frequency in sorted(bands)]

    @classmethod
    def _simulation(
        cls,
        nsem: Any,
        mesh: Any,
        conductivity_map: Any,
        group: list[Any],
        observations: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> tuple[Any, Any, list[tuple[str, str]]]:
        """One simulation for a whole mode, with a source per frequency."""
        mode = group[0].mode
        orientation = "xy" if mode == "te" else "yx"
        sources = []
        owner: list[tuple[str, str]] = []
        for frequency, sites in cls._frequency_groups(group, observations):
            locations = np.array(
                [[site.distance_m, site.elevation_m] for site in sites], dtype=float
            )
            receivers = [
                nsem.receivers.Impedance(
                    locations_e=locations,
                    locations_h=locations,
                    orientation=orientation,
                    component=component,
                )
                for component in ("real", "imag")
            ]
            sources.append(nsem.sources.Planewave(receivers, frequency=frequency))
            for _ in ("real", "imag"):
                owner.extend((site.site_id, str(site.mode)) for site in sites)
        simulation_class = (
            nsem.simulation.Simulation2DElectricField
            if mode == "te"
            else nsem.simulation.Simulation2DMagneticField
        )
        simulation = simulation_class(
            mesh=mesh, survey=nsem.Survey(sources), sigmaMap=conductivity_map
        )
        return simulation, simulation.survey, owner

    @classmethod
    def _assemble(
        cls,
        group: list[Any],
        observations: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]],
    ) -> tuple[np.ndarray, np.ndarray]:
        """The observed vector and its deviations, in `dpred`'s own order."""
        observed: list[float] = []
        deviation: list[float] = []
        for frequency, sites in cls._frequency_groups(group, observations):
            for component in ("real", "imag"):
                for site in sites:
                    key = (site.site_id, str(site.mode))
                    frequencies, impedance, uncertainty = observations[key]
                    at = int(np.argmin(np.abs(frequencies - frequency)))
                    value = impedance[at]
                    observed.append(float(value.real if component == "real" else value.imag))
                    deviation.append(float(uncertainty[at]))
        return np.asarray(observed), np.asarray(deviation)

    @staticmethod
    def _conductivity(value: QuantitySpec) -> float:
        canonical = canonicalize_quantity(value.value, value.unit, QuantityType.CONDUCTIVITY)
        return float(canonical)

    @staticmethod
    def _load_observations(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        try:
            table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to read {path}: {error}") from error
        names = set(table.dtype.names or ())
        required = {FREQUENCY_COLUMN, REAL_COLUMN, IMAGINARY_COLUMN, UNCERTAINTY_COLUMN}
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
        table = np.atleast_1d(table)
        frequencies = np.asarray(table[FREQUENCY_COLUMN], dtype=float)
        impedance = np.asarray(table[REAL_COLUMN], dtype=float) + 1j * np.asarray(
            table[IMAGINARY_COLUMN], dtype=float
        )
        uncertainty = np.asarray(table[UNCERTAINTY_COLUMN], dtype=float)
        if frequencies.size == 0 or not np.isfinite(frequencies).all() or (frequencies <= 0).any():
            raise ValueError(f"{path} must carry finite positive frequencies")
        if (np.diff(frequencies) <= 0).any():
            raise ValueError(f"{path} frequencies must ascend, and these do not")
        if not np.isfinite(impedance).all() or (uncertainty <= 0).any():
            raise ValueError(f"{path} must carry finite impedances and positive uncertainties")
        return frequencies, impedance, uncertainty

    def _write(
        self,
        spec: RunSpec,
        context: PluginContext,
        run_dir: Path,
        mesh: Any,
        active: np.ndarray,
        section: np.ndarray,
        rows: list[dict[str, Any]],
        engine_log: StringIO,
    ) -> RunResult:
        model_path = run_dir / "conductivity_section.npz"
        summary_path = run_dir / "site_summary.csv"
        log_path = run_dir / "simpeg.log"
        np.savez_compressed(
            model_path,
            conductivity_s_m=section,
            active_cells=active,
            cell_centers_m=mesh.cell_centers,
            cell_widths_m=np.column_stack([mesh.h_gridded[:, 0], mesh.h_gridded[:, 1]]),
            shape_cells=np.asarray(mesh.shape_cells),
        )
        summary_path.write_text(
            "\n".join(
                [",".join(rows[0])]
                + [",".join(str(value) for value in row.values()) for row in rows]
            )
            + "\n",
            encoding="utf-8",
        )
        log_path.write_text(engine_log.getvalue(), encoding="utf-8")
        (run_dir / "site_models.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
        chi = np.array([row["chi_squared"] for row in rows])
        artifacts = [
            self._artifact(spec, context, model_path, "model", QuantityType.CONDUCTIVITY),
            self._artifact(spec, context, summary_path, "site_summary", QuantityType.DIMENSIONLESS),
            self._artifact(spec, context, log_path, "engine_log", QuantityType.DIMENSIONLESS),
        ]
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "mt2d",
                "site_count": len(rows),
                "cell_count": int(mesh.n_cells),
                "active_cells": int(active.sum()),
                "chi_squared_median": float(np.median(chi)),
                "chi_squared_worst": float(np.nanmax(chi)),
                "sites_fitting": int((chi <= 2.0).sum()),
                "model_unit": "S/m",
            },
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _artifact(
        spec: RunSpec,
        context: PluginContext,
        path: Path,
        artifact_type: str,
        quantity: QuantityType,
    ) -> ArtifactManifest:
        from ofag.core.constants import CANONICAL_UNITS

        return ArtifactManifest(
            artifact_type=artifact_type,
            physical_quantity=quantity,
            units=CANONICAL_UNITS[quantity],
            source_run_id=spec.run_id,
            relative_path=str(path.relative_to(context.artifact_root).as_posix()),
        )
