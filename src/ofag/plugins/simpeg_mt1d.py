"""Layered magnetotelluric inversion, one model per site."""

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
from ofag.core.conventions import ConventionCheck
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    MT1DBatchInversionSpec,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.engines.simpeg import conventions
from ofag.plugins.protocol import PluginContext, configuration_field

#: The columns a magnetotelluric observation file carries, written by
#: `ofag.services.mt_import` and read here.
FREQUENCY_COLUMN = "frequency_hz"
REAL_COLUMN = "impedance_real_ohm"
IMAGINARY_COLUMN = "impedance_imag_ohm"
UNCERTAINTY_COLUMN = "uncertainty_ohm"

#: For the convention check's own arithmetic, which borrows nothing.
MU0 = 4.0e-7 * np.pi


class SimPEGMT1DPlugin:
    """One layered conductivity model per magnetotelluric site."""

    plugin_id = "simpeg.nsem.mt1d_batch"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return MT1DBatchInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> MT1DBatchInversionSpec | None:
        return spec.physics_as(MT1DBatchInversionSpec)

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.MAGNETOTELLURIC_IMPEDANCE,),
            supported_meshes=("Layered1D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Fits the off-diagonal impedance of each site against a layered earth.",
                "Sites are independent: the stitched section is a picture, not a 2D solve.",
                "Static shift, tipper and anisotropy are not modelled.",
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
                    message="a magnetotelluric batch requires its inversion controls",
                    remediation="provide the earth, the model bounds and the sites",
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

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = self._configuration(spec)
        sites = len(config.sites) if config else 0
        # Layered, so each site is seconds and nothing is held but its own curve: the
        # cost is the site count and not the model size.
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=256,
            estimated_seconds=max(1, sites * 3),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = self._configuration(spec)
        assert config is not None

        from simpeg import data as simpeg_data  # type: ignore[import-untyped]
        from simpeg import (
            data_misfit,
            directives,
            inverse_problem,
            inversion,
            maps,
            optimization,
            regularization,
        )
        from simpeg.electromagnetics import (  # type: ignore[import-untyped]
            natural_source as nsem,
        )

        run_dir = context.run_dir(spec.run_id)
        thicknesses = np.asarray(
            canonicalize_quantity(
                config.earth.layer_thicknesses.value,
                config.earth.layer_thicknesses.unit,
                QuantityType.LENGTH,
            ),
            dtype=float,
        )
        layers = thicknesses.size + 1
        start = float(self._conductivity(config.model.initial_conductivity))
        lower = float(self._conductivity(config.model.lower_bound))
        upper = float(self._conductivity(config.model.upper_bound))

        engine_log = StringIO()
        simpeg_logger = logging.getLogger("simpeg")
        previous = simpeg_logger.disabled
        simpeg_logger.disabled = True
        rows: list[dict[str, Any]] = []
        models = np.empty((len(config.sites), layers))
        try:
            with redirect_stdout(engine_log), redirect_stderr(engine_log):
                for index, site in enumerate(config.sites):
                    frequencies, impedance, uncertainty = self._load_observations(
                        Path(site.observations_path)
                    )
                    simulation, survey = self._simulation(
                        nsem, maps, thicknesses, frequencies, layers
                    )
                    observed = np.empty(frequencies.size * 2)
                    observed[0::2] = impedance.real
                    observed[1::2] = impedance.imag
                    deviation = np.repeat(uncertainty, 2)
                    misfit = data_misfit.L2DataMisfit(
                        simulation=simulation,
                        data=simpeg_data.Data(survey, dobs=observed, standard_deviation=deviation),
                    )
                    smallness = regularization.WeightedLeastSquares(
                        mesh=self._regularization_mesh(thicknesses),
                        alpha_s=config.regularization.alpha_s,
                        # Never None.
                        alpha_x=(
                            1.0
                            if config.regularization.alpha_z is None
                            else config.regularization.alpha_z
                        ),
                        reference_model=np.full(layers, np.log(start)),
                    )
                    optimizer = optimization.ProjectedGNCG(
                        maxIter=config.optimizer.max_iterations,
                        lower=np.log(lower),
                        upper=np.log(upper),
                        maxIterCG=config.optimizer.cg_max_iterations,
                        tolCG=config.optimizer.cg_relative_tolerance,
                    )
                    problem = inverse_problem.BaseInvProblem(misfit, smallness, optimizer)
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
                        np.full(layers, np.log(start))
                    )
                    predicted = simulation.dpred(recovered)
                    residual = (predicted - observed) / deviation
                    models[index] = np.exp(recovered)
                    rows.append(
                        {
                            "site_id": site.site_id,
                            "easting_m": site.easting_m,
                            "northing_m": site.northing_m,
                            "elevation_m": site.elevation_m,
                            "frequency_count": int(frequencies.size),
                            "chi_squared": float(np.mean(residual**2)),
                        }
                    )
                    context.emit(
                        RunEvent(
                            run_id=spec.run_id,
                            event_type="iteration",
                            iteration=index + 1,
                            message=f"{site.site_id} fitted",
                        )
                    )
        finally:
            simpeg_logger.disabled = previous

        return self._write(spec, context, run_dir, config, thicknesses, models, rows, engine_log)

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (
            conventions.layered_mt_layer_order(self._predict_for_conventions),
            conventions.layered_mt_halfspace(self._predict_for_conventions),
        )

    @classmethod
    def _predict_for_conventions(
        cls, thicknesses: list[float], resistivities: list[float], frequency: float
    ) -> complex:
        """The plugin's own simulation, for the checks to measure."""
        from simpeg import maps
        from simpeg.electromagnetics import natural_source as nsem

        simulation, _ = cls._simulation(
            nsem,
            maps,
            np.asarray(thicknesses, dtype=float),
            np.asarray([frequency], dtype=float),
            len(resistivities),
        )
        values = simulation.dpred(np.log(1.0 / np.asarray(resistivities, dtype=float)))
        return complex(values[0] + 1j * values[1])

    # -- the pieces ----------------------------------------------------------

    @staticmethod
    def _simulation(
        nsem: Any, maps: Any, thicknesses: np.ndarray, frequencies: np.ndarray, layers: int
    ) -> tuple[Any, Any]:
        """A layered natural-source simulation of the off-diagonal impedance."""
        location = np.array([[0.0, 0.0, 0.0]])
        sources = [
            nsem.sources.Planewave(
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
            for frequency in frequencies
        ]
        turn_over = maps.Projection(layers, np.arange(layers)[::-1])
        simulation = nsem.simulation_1d.Simulation1DRecursive(
            survey=nsem.Survey(sources),
            thicknesses=np.asarray(thicknesses)[::-1],
            sigmaMap=maps.ExpMap(nP=layers) * turn_over,
        )
        return simulation, simulation.survey

    @staticmethod
    def _regularization_mesh(thicknesses: np.ndarray) -> Any:
        """A one-dimensional mesh of the layers, for the smoothness term."""
        from discretize import TensorMesh  # type: ignore[import-untyped]

        widths = np.r_[thicknesses, thicknesses[-1]]
        return TensorMesh([widths], origin="0")

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
        config: MT1DBatchInversionSpec,
        thicknesses: np.ndarray,
        models: np.ndarray,
        rows: list[dict[str, Any]],
        engine_log: StringIO,
    ) -> RunResult:
        section = run_dir / "stitched_conductivity_section.npz"
        summary_path = run_dir / "site_summary.csv"
        log_path = run_dir / "simpeg.log"
        depths = np.r_[0.0, np.cumsum(thicknesses)]
        np.savez_compressed(
            section,
            conductivity_s_m=models,
            layer_thicknesses_m=thicknesses,
            layer_top_depth_m=depths,
            easting_m=np.array([row["easting_m"] for row in rows]),
            northing_m=np.array([row["northing_m"] for row in rows]),
            elevation_m=np.array([row["elevation_m"] for row in rows]),
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
            self._artifact(spec, context, section, "stitched_section", QuantityType.CONDUCTIVITY),
            self._artifact(spec, context, summary_path, "site_summary", QuantityType.DIMENSIONLESS),
            self._artifact(spec, context, log_path, "engine_log", QuantityType.DIMENSIONLESS),
        ]
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "mt1d_batch",
                "site_count": len(rows),
                "layer_count": int(models.shape[1]),
                "chi_squared_median": float(np.median(chi)),
                "chi_squared_worst": float(chi.max()),
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
