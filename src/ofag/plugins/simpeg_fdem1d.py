"""Layered conductivity beneath each sounding of a frequency-domain airborne survey."""

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from ofag.core.constants import QuantityType
from ofag.core.conventions import ConventionCheck
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    FDEM1DInversionSpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.plugins.protocol import PluginContext

__all__ = ["SimPEGFDEM1DPlugin"]

#: SimPEG names the two coil geometries by the orientation of each coil, not by the name
#: the airborne industry uses for the pair.
_ORIENTATION = {"horizontal_coplanar": "z", "vertical_coaxial": "x"}


class SimPEGFDEM1DPlugin:
    """Invert a frequency-domain airborne survey, one layered sounding at a time."""

    plugin_id = "simpeg.aem.fdem1d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return FDEM1DInversionSpec

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.DIMENSIONLESS,),
            supported_meshes=("Layered1D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Each sounding is inverted independently against its own layered earth; "
                "there is no lateral constraint between them.",
                "The response is the secondary field in parts per million, which is what a "
                "RESOLVE-style delivery carries.",
                "Flight height is per sounding and is taken from the survey, not fitted.",
                "RunSpec.mesh must be unset: the discretisation is the layer array.",
            ),
        )

    def conventions(self) -> tuple[ConventionCheck, ...]:
        from ofag.engines.simpeg import conventions

        return (
            conventions.layered_fdem_layer_order(),
            conventions.fdem_halfspace_against_analytic(),
            conventions.fdem_coaxial_signs_against_coplanar(),
        )

    @staticmethod
    def _configuration(spec: RunSpec) -> FDEM1DInversionSpec | None:
        return spec.physics_as(FDEM1DInversionSpec)

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message=f"{self.plugin_id} requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        if spec.mesh is not None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="a layered inversion declares its discretisation in the physics "
                    "payload, so RunSpec.mesh must be unset",
                    remediation="remove the mesh block",
                )
            )
        config = self._configuration(spec)
        if config is None:
            issues.append(
                ValidationIssue(
                    field="physics",
                    message=f"{self.plugin_id} requires an FDEM1DInversionSpec payload",
                    remediation="supply the physics block this plugin declares",
                )
            )
            return ValidationReport(valid=False, issues=tuple(issues))

        for sounding in config.soundings:
            path = Path(sounding.observations_path)
            if not path.is_file():
                issues.append(
                    ValidationIssue(
                        field="physics.soundings",
                        message=f"sounding {sounding.sounding_id} has no file at {path}",
                        remediation="import the survey before inverting it",
                    )
                )
                break
            values = self._observations(path)
            expected = 2 * len(config.system.coil_pairs)
            if values.size != expected:
                issues.append(
                    ValidationIssue(
                        field="physics.soundings",
                        message=(
                            f"sounding {sounding.sounding_id} carries {values.size} values for "
                            f"{len(config.system.coil_pairs)} coil pairs; {expected} are needed, "
                            "in-phase and quadrature for each"
                        ),
                        remediation="write one in-phase and one quadrature per declared pair",
                    )
                )
                break
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = self._configuration(spec)
        if config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        soundings = len(config.soundings)
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=512,
            estimated_seconds=max(1, soundings // 20),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        from simpeg import (  # type: ignore[import-untyped]
            data,
            data_misfit,
            directives,
            inverse_problem,
            inversion,
            maps,
            optimization,
            regularization,
        )

        config = self._configuration(spec)
        if config is None:
            raise ValueError(f"{self.plugin_id} requires an FDEM1DInversionSpec payload")

        thicknesses = np.asarray(
            canonicalize_quantity(
                config.earth.layer_thicknesses.value,
                config.earth.layer_thicknesses.unit,
                QuantityType.LENGTH,
            ),
            dtype=float,
        )
        layers = thicknesses.size + 1
        initial = float(
            np.atleast_1d(
                canonicalize_quantity(
                    config.model.initial_conductivity.value,
                    config.model.initial_conductivity.unit,
                    QuantityType.CONDUCTIVITY,
                )
            )[0]
        )
        bounds = tuple(
            float(
                np.atleast_1d(
                    canonicalize_quantity(item.value, item.unit, QuantityType.CONDUCTIVITY)
                )[0]
            )
            for item in (config.model.lower_bound, config.model.upper_bound)
        )

        recovered: list[np.ndarray] = []
        stations: list[np.ndarray] = []
        identifiers: list[str] = []
        misfits: list[float] = []
        sign = self._response_sign(config)
        # One event per sounding.
        total = len(config.soundings)
        report_every = max(1, total // 100)
        for index, sounding in enumerate(config.soundings):
            observed = self._observations(Path(sounding.observations_path)) * sign
            uncertainty = np.broadcast_to(
                np.abs(
                    np.asarray(
                        canonicalize_quantity(
                            sounding.data_uncertainty.value,
                            sounding.data_uncertainty.unit,
                            QuantityType.DIMENSIONLESS,
                        ),
                        dtype=float,
                    )
                ),
                observed.shape,
            ).copy()
            uncertainty[uncertainty <= 0.0] = np.abs(observed[uncertainty <= 0.0]) * 0.05 + 1.0

            simulation = self._simulation(config, sounding.flight_height_m, thicknesses, layers)
            observations = data.Data(
                simulation.survey, dobs=observed, standard_deviation=uncertainty
            )
            misfit = data_misfit.L2DataMisfit(simulation=simulation, data=observations)
            model_map = maps.ExpMap(nP=layers)
            simulation.sigmaMap = model_map
            smallness = regularization.WeightedLeastSquares(
                mesh=_layer_mesh(layers),
                alpha_s=config.regularization.alpha_s,
                # alpha_x, not alpha_z.
                alpha_x=(
                    1.0 if config.regularization.alpha_z is None else config.regularization.alpha_z
                ),
                reference_model=np.full(layers, np.log(initial)),
            )
            problem = inverse_problem.BaseInvProblem(
                misfit,
                smallness,
                optimization.ProjectedGNCG(
                    maxIter=config.optimizer.max_iterations,
                    lower=np.log(bounds[0]),
                    upper=np.log(bounds[1]),
                    maxIterCG=config.optimizer.cg_max_iterations,
                ),
            )
            # A target misfit only when one was asked for.
            schedule = [
                directives.BetaEstimate_ByEig(beta0_ratio=config.beta.beta0_ratio),
                directives.BetaSchedule(
                    coolingFactor=config.beta.cooling_factor,
                    coolingRate=config.beta.cooling_rate,
                ),
            ]
            if config.directives.target_chi_factor is not None:
                schedule.append(
                    directives.TargetMisfit(chifact=config.directives.target_chi_factor)
                )
            solved = inversion.BaseInversion(problem, directiveList=schedule).run(
                np.full(layers, np.log(initial))
            )

            recovered.append(np.exp(np.asarray(solved, dtype=float)))
            stations.append(
                np.asarray(
                    canonicalize_quantity(
                        sounding.station_location.value,
                        sounding.station_location.unit,
                        QuantityType.LENGTH,
                    ),
                    dtype=float,
                )
            )
            identifiers.append(sounding.sounding_id)
            residual = (simulation.dpred(solved) - observed) / uncertainty
            misfits.append(float(np.mean(residual**2)))
            if index % report_every == 0 or index == total - 1:
                context.emit(
                    RunEvent(
                        run_id=spec.run_id,
                        event_type="iteration",
                        iteration=index + 1,
                        stage=sounding.sounding_id,
                        stage_index=index,
                        stage_total=total,
                        message=(
                            f"{index + 1} of {total} soundings, chi-squared "
                            f"{float(np.median(misfits)):.3f} so far"
                        ),
                    )
                )

        tops = np.concatenate([[0.0], np.cumsum(thicknesses)])
        # Under this run's own directory.
        run_dir = context.artifact_root / str(spec.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        section = run_dir / "stitched_conductivity_section.npz"
        np.savez_compressed(
            section,
            sounding_ids=np.asarray(identifiers),
            receiver_locations_m=np.vstack(stations),
            layer_top_depth_m=tops,
            conductivity_s_m=np.vstack(recovered),
            chi_squared=np.asarray(misfits),
        )
        chi = np.asarray(misfits)
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "fdem1d",
                "sounding_count": len(identifiers),
                "model_layers": layers,
                "frequency_count": len(config.system.coil_pairs),
                "chi_squared_median": float(np.median(chi)),
                "chi_squared_worst": float(np.max(chi)),
                "soundings_fitting": int((chi <= 2.0).sum()),
            },
            artifacts=(
                ArtifactManifest(
                    artifact_type="stitched_conductivity_section",
                    physical_quantity=QuantityType.CONDUCTIVITY,
                    units="S/m",
                    source_run_id=spec.run_id,
                    relative_path=section.relative_to(context.artifact_root).as_posix(),
                ),
            ),
        )

    def _simulation(
        self,
        config: FDEM1DInversionSpec,
        height: float,
        thicknesses: np.ndarray,
        layers: int,
    ) -> Any:
        from simpeg import maps
        from simpeg.electromagnetics import frequency_domain as fdem  # type: ignore[import-untyped]

        sources = []
        for pair in config.system.coil_pairs:
            axis = _ORIENTATION[pair.orientation]
            receivers = [
                fdem.receivers.PointMagneticFieldSecondary(
                    np.array([[pair.separation_m, 0.0, height]]),
                    orientation=axis,
                    component=component,
                    data_type="ppm",
                )
                for component in ("real", "imag")
            ]
            sources.append(
                fdem.sources.MagDipole(
                    receivers,
                    frequency=pair.frequency_hz,
                    location=np.array([0.0, 0.0, height]),
                    orientation=axis,
                )
            )
        return fdem.Simulation1DLayered(
            survey=fdem.Survey(sources),
            thicknesses=thicknesses,
            sigmaMap=maps.ExpMap(nP=layers),
        )

    @staticmethod
    def _response_sign(config: FDEM1DInversionSpec) -> np.ndarray:
        """One multiplier per datum, reconciling the delivery with the engine."""
        return np.repeat(
            np.array([float(pair.response_sign) for pair in config.system.coil_pairs]), 2
        )

    @staticmethod
    def _observations(path: Path) -> np.ndarray:
        """In-phase then quadrature for each coil pair, in the spec's order."""
        table = np.loadtxt(path, delimiter=",", skiprows=1)
        return np.atleast_1d(np.asarray(table, dtype=float)).ravel()


def _layer_mesh(layers: int) -> Any:
    from discretize import TensorMesh  # type: ignore[import-untyped]

    return TensorMesh([np.ones(layers)], origin="0")
