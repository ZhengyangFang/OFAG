"""SimPEG-backed single-sounding 1D TDEM inversion."""

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
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    TDEMInversionSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.engines.simpeg import conventions
from ofag.plugins.protocol import PluginContext
from ofag.plugins.simpeg_gravity import chi_squared


class SimPEGTDEM1DPlugin:
    """Invert a step-off circular-loop TDEM sounding for layered conductivity."""

    plugin_id = "simpeg.aem.tdem1d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return TDEMInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> TDEMInversionSpec | None:
        """Read this plugin's configuration from whichever form the run uses."""
        return spec.physics_as(TDEMInversionSpec) or spec.tdem_inversion

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.MAGNETIC_FLUX_DENSITY,),
            supported_meshes=("Layered1D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Supports one circular-loop sounding with B or dB/dt data and step-off or "
                "piecewise-linear waveforms.",
                "Voltage receivers and non-layered 1D earth models are not yet supported.",
                "Install with `uv sync --extra simpeg`; SimPEG is an optional backend dependency.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        config = self._configuration(spec)
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
                    message="simpeg.aem.tdem1d requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        expected_quantity = (
            self._receiver_quantity(config.system.receiver_quantity)
            if config is not None
            else QuantityType.MAGNETIC_FLUX_DENSITY
        )
        if spec.dataset.physical_quantity is not expected_quantity:
            issues.append(
                ValidationIssue(
                    field="dataset.physical_quantity",
                    message=f"TDEM 1D requires {expected_quantity.value} observations",
                    remediation="declare the receiver response with explicit SI-compatible units",
                )
            )
        if config is None:
            issues.append(
                ValidationIssue(
                    field="physics",
                    message="a TDEMInversionSpec is required",
                    remediation=(
                        "provide system, earth, model and inversion settings in physics, "
                        "or in tdem_inversion under schema 1.0"
                    ),
                )
            )
        observations_path = self._string_parameter(spec, "observations_path")
        if observations_path is None:
            issues.append(
                ValidationIssue(
                    field="parameters.observations_path",
                    message="a CSV with time_s,magnetic_flux_density_t is required",
                    remediation="supply a UTF-8 SI CSV path relative to the workspace",
                )
            )
        elif not Path(observations_path).is_file():
            issues.append(
                ValidationIssue(
                    field="parameters.observations_path",
                    message=f"observation CSV does not exist: {observations_path}",
                    remediation="generate or import the sounding before validating the run",
                )
            )
        else:
            path = Path(observations_path)
            try:
                observations = self._load_observations(path, expected_quantity)
                if config is not None:
                    self._validate_observation_times(observations, config)
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        field="parameters.observations_path",
                        message=str(error),
                        remediation=(
                            "provide finite, increasing SI time channels matching "
                            "tdem_inversion.system"
                        ),
                    )
                )
        uncertainty = spec.parameters.get("data_uncertainty")
        if not isinstance(uncertainty, QuantitySpec):
            issues.append(
                ValidationIssue(
                    field="parameters.data_uncertainty",
                    message="data_uncertainty must be an explicit QuantitySpec",
                    remediation="use magnetic_flux_density in tesla",
                )
            )
        elif uncertainty.quantity_type is not expected_quantity:
            issues.append(
                ValidationIssue(
                    field="parameters.data_uncertainty",
                    message=f"data_uncertainty must be {expected_quantity.value}",
                    remediation=(
                        "use positive scalar or channel-wise values in tesla-compatible units"
                    ),
                )
            )
        else:
            try:
                channel_count = 1
                if observations_path is not None and Path(observations_path).is_file():
                    channel_count = self._load_observations(
                        Path(observations_path), expected_quantity
                    ).size
                self._uncertainty_values(uncertainty, channel_count, expected_quantity)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        field="parameters.data_uncertainty",
                        message=(
                            "data_uncertainty must be positive and match the observation channels"
                        ),
                        remediation=(
                            "use positive scalar or channel-wise magnetic-flux-density uncertainty"
                        ),
                    )
                )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (conventions.layered_tem_layer_order(),)

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = self._configuration(spec)
        if config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        layers = self._vector_quantity(config.earth.layer_thicknesses, QuantityType.LENGTH).size + 1
        channels = self._vector_quantity(config.system.times, QuantityType.TIME).size
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(256, int(layers * channels * 8 // (1024 * 1024))),
            estimated_seconds=max(1, layers * channels // 10),
        )

    def execute(
        self,
        context: PluginContext,
        spec: RunSpec,
    ) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = self._configuration(spec)
        assert config is not None
        times = self._vector_quantity(config.system.times, QuantityType.TIME)
        response_quantity = self._receiver_quantity(config.system.receiver_quantity)
        response_column = self._observation_column(response_quantity)
        observations = self._load_observations(
            Path(self._required_string_parameter(spec, "observations_path")), response_quantity
        )
        uncertainty_t = self._uncertainty_values(
            self._required_quantity_parameter(spec, "data_uncertainty"),
            times.size,
            response_quantity,
        )
        thicknesses = self._vector_quantity(config.earth.layer_thicknesses, QuantityType.LENGTH)
        source_location = self._vector_quantity(config.system.source_location, QuantityType.LENGTH)
        receiver_location = self._vector_quantity(
            config.system.receiver_location, QuantityType.LENGTH
        )
        source_radius = self._scalar_quantity(config.system.source_radius, QuantityType.LENGTH)
        source_current = self._scalar_quantity(
            config.system.source_current, QuantityType.ELECTRIC_CURRENT
        )
        layer_count = thicknesses.size + 1
        initial_conductivity = self._scalar_quantity(
            config.model.initial_conductivity, QuantityType.CONDUCTIVITY
        )
        lower_bound = self._scalar_quantity(config.model.lower_bound, QuantityType.CONDUCTIVITY)
        upper_bound = self._scalar_quantity(config.model.upper_bound, QuantityType.CONDUCTIVITY)
        reference_conductivity = self._scalar_quantity(
            config.model.reference_conductivity or config.model.initial_conductivity,
            QuantityType.CONDUCTIVITY,
        )

        from discretize import TensorMesh  # type: ignore[import-untyped]
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
        from simpeg.electromagnetics import time_domain as tdem  # type: ignore[import-untyped]

        receiver_class = (
            tdem.receivers.PointMagneticFluxDensity
            if response_quantity is QuantityType.MAGNETIC_FLUX_DENSITY
            else tdem.receivers.PointMagneticFluxTimeDerivative
        )
        receiver = receiver_class(
            receiver_location.reshape(1, 3), times, orientation=config.system.receiver_orientation
        )
        source = tdem.sources.CircularLoop(
            receiver_list=[receiver],
            location=source_location,
            orientation=config.system.source_orientation,
            radius=source_radius,
            current=source_current,
            n_turns=config.system.source_turns,
            waveform=self._build_waveform(tdem, config),
        )
        survey = tdem.Survey([source])
        log_conductivity_map = maps.ExpMap(nP=layer_count)
        simulation = tdem.Simulation1DLayered(
            survey=survey,
            thicknesses=thicknesses,
            sigmaMap=log_conductivity_map,
        )
        observed_data = data.Data(
            survey,
            dobs=observations[response_column],
            standard_deviation=uncertainty_t,
        )
        dmisfit = data_misfit.L2DataMisfit(data=observed_data, simulation=simulation)
        regularization_mesh = TensorMesh([np.r_[thicknesses, thicknesses[-1]]])
        reference_log_conductivity = np.full(layer_count, np.log(reference_conductivity))
        regularizer = regularization.WeightedLeastSquares(
            regularization_mesh,
            alpha_s=config.regularization.alpha_s,
            # The spec calls the smoothness weight alpha_z because depth is what it
            # smooths over, and this mesh is one-dimensional, so its only axis is x.
            alpha_x=(
                1.0 if config.regularization.alpha_z is None else config.regularization.alpha_z
            ),
            reference_model=reference_log_conductivity,
            reference_model_in_smooth=config.model.reference_model_in_smooth,
        )
        optimizer = optimization.ProjectedGNCG(
            maxIter=config.optimizer.max_iterations,
            maxIterLS=config.optimizer.max_line_search_iterations,
            cg_maxiter=min(config.optimizer.cg_max_iterations, layer_count),
            cg_rtol=config.optimizer.cg_relative_tolerance,
            cg_atol=config.optimizer.cg_absolute_tolerance,
            tolF=config.optimizer.tolerance_f,
            tolX=config.optimizer.tolerance_x,
            tolG=config.optimizer.tolerance_g,
            lower=np.log(lower_bound),
            upper=np.log(upper_bound),
        )
        initial_model = np.full(layer_count, np.log(initial_conductivity))
        run_dir = context.run_dir(spec.run_id)

        def write_progress(
            iteration: int, phi_total: float, phi_data: float, phi_model: float
        ) -> None:
            context.emit(
                RunEvent(
                    run_id=spec.run_id,
                    event_type="iteration",
                    iteration=iteration,
                    phi_total=phi_total,
                    phi_data=phi_data,
                    phi_model=phi_model,
                    message="iteration completed",
                )
            )

        context.emit(
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=0, message="started")
        )
        engine_log = StringIO()
        simpeg_logger = logging.getLogger("SimPEG")
        previous_logger_state = simpeg_logger.disabled
        simpeg_logger.disabled = True
        try:
            with redirect_stdout(engine_log), redirect_stderr(engine_log):
                fixed_beta = config.beta.fixed_beta if config.beta.estimation == "fixed" else 1.0
                inverse_problem_instance = inverse_problem.BaseInvProblem(
                    dmisfit, regularizer, optimizer, beta=fixed_beta
                )
                directive_list: list[Any] = []
                if config.beta.estimation == "by_eig":
                    directive_list.extend(
                        [
                            directives.BetaEstimate_ByEig(
                                beta0_ratio=config.beta.beta0_ratio,
                                n_pw_iter=config.beta.n_power_iterations,
                                random_seed=spec.seed,
                            ),
                            directives.BetaSchedule(
                                coolingFactor=config.beta.cooling_factor,
                                coolingRate=config.beta.cooling_rate,
                            ),
                        ]
                    )
                if config.directives.target_chi_factor is not None:
                    directive_list.append(
                        directives.TargetMisfit(chifact=config.directives.target_chi_factor)
                    )
                metrics_directive: Any | None = None
                if config.directives.save_iteration_metrics:
                    # SimPEG is an untyped import, so its directive base is `Any`.
                    class ProgressMetrics(directives.SaveOutputEveryIteration):  # type: ignore[misc]
                        def endIter(self) -> None:  # noqa: N802 - SimPEG callback name
                            super().endIter()
                            write_progress(
                                int(self.opt.iter),
                                float(self.phi[-1]),
                                float(self.phi_d[-1]),
                                float(self.phi_m[-1]),
                            )

                    metrics_directive = ProgressMetrics(on_disk=False)
                    directive_list.append(metrics_directive)
                inverse = inversion.BaseInversion(
                    inverse_problem_instance, directiveList=directive_list
                )
                recovered_log_conductivity = np.asarray(inverse.run(initial_model), dtype=float)
                predicted_t = np.asarray(simulation.dpred(recovered_log_conductivity), dtype=float)
        finally:
            simpeg_logger.disabled = previous_logger_state
        recovered_conductivity = np.exp(recovered_log_conductivity)
        residual_t = predicted_t - observations[response_column]
        normalized_residual = residual_t / uncertainty_t
        phi_data = float(0.5 * np.dot(normalized_residual, normalized_residual))
        phi_model = float(regularizer(recovered_log_conductivity))

        conductivity_path = run_dir / "recovered_conductivity_s_m.npy"
        log_conductivity_path = run_dir / "recovered_log_conductivity.npy"
        layer_depth_path = run_dir / "layer_top_depth_m.npy"
        response_suffix = self._response_suffix(response_quantity)
        observation_path = run_dir / f"observed_{response_suffix}.npy"
        prediction_path = run_dir / f"predicted_{response_suffix}.npy"
        residual_path = run_dir / f"residual_{response_suffix}.npy"
        normalized_residual_path = run_dir / "normalized_residual.npy"
        log_path = run_dir / "simpeg.log"
        np.save(conductivity_path, recovered_conductivity)
        np.save(log_conductivity_path, recovered_log_conductivity)
        np.save(layer_depth_path, np.r_[0.0, np.cumsum(thicknesses)])
        np.save(observation_path, observations[response_column])
        np.save(prediction_path, predicted_t)
        np.save(residual_path, residual_t)
        np.save(normalized_residual_path, normalized_residual)
        log_path.write_text(engine_log.getvalue(), encoding="utf-8")
        artifacts: list[ArtifactManifest] = [
            self._artifact(
                spec,
                context,
                conductivity_path,
                "recovered_model",
                QuantityType.CONDUCTIVITY,
                "S/m",
            ),
            self._artifact(
                spec,
                context,
                log_conductivity_path,
                "recovered_log_model",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec, context, layer_depth_path, "layer_top_depth", QuantityType.LENGTH, "m"
            ),
            self._artifact(
                spec,
                context,
                observation_path,
                "observed_data",
                response_quantity,
                self._response_unit(response_quantity),
            ),
            self._artifact(
                spec,
                context,
                prediction_path,
                "predicted_data",
                response_quantity,
                self._response_unit(response_quantity),
            ),
            self._artifact(
                spec,
                context,
                residual_path,
                "residual_data",
                response_quantity,
                self._response_unit(response_quantity),
            ),
            self._artifact(
                spec,
                context,
                normalized_residual_path,
                "normalized_residual",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec, context, log_path, "engine_log", QuantityType.DIMENSIONLESS, "dimensionless"
            ),
        ]
        if metrics_directive is not None:
            metrics_path = run_dir / "iteration_metrics.csv"
            metrics = np.column_stack(
                [
                    np.arange(len(metrics_directive.beta)),
                    metrics_directive.beta,
                    metrics_directive.phi_d,
                    metrics_directive.phi_m,
                    metrics_directive.phi,
                ]
            )
            np.savetxt(
                metrics_path,
                metrics,
                delimiter=",",
                header="iteration,beta,phi_data,phi_model,phi_total",
                comments="",
            )
            artifacts.append(
                self._artifact(
                    spec,
                    context,
                    metrics_path,
                    "iteration_metrics",
                    QuantityType.DIMENSIONLESS,
                    "dimensionless",
                )
            )
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=config.optimizer.max_iterations,
                phi_total=phi_data + phi_model,
                phi_data=phi_data,
                phi_model=phi_model,
                message="completed",
            )
        )
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "tdem1d_layered",
                "observation_count": int(times.size),
                "model_layers": int(layer_count),
                "phi_data": phi_data,
                "chi_squared": chi_squared(phi_data, int(times.size)),
                "phi_model": phi_model,
                "data_unit": self._response_unit(response_quantity),
                "model_unit": "S/m",
            },
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _string_parameter(spec: RunSpec, name: str) -> str | None:
        value = spec.parameters.get(name)
        return value if isinstance(value, str) and value.strip() else None

    def _required_string_parameter(self, spec: RunSpec, name: str) -> str:
        value = self._string_parameter(spec, name)
        if value is None:
            raise ValueError(f"parameters.{name} is required")
        return value

    @staticmethod
    def _required_quantity_parameter(spec: RunSpec, name: str) -> QuantitySpec:
        value = spec.parameters.get(name)
        if not isinstance(value, QuantitySpec):
            raise ValueError(f"parameters.{name} must be a QuantitySpec")
        return value

    @staticmethod
    def _scalar_quantity(value: QuantitySpec, quantity_type: QuantityType) -> float:
        if value.quantity_type is not quantity_type or isinstance(value.value, list):
            raise ValueError(f"expected scalar {quantity_type.value} quantity")
        return float(canonicalize_quantity(value.value, value.unit, quantity_type))

    @staticmethod
    def _vector_quantity(value: QuantitySpec, quantity_type: QuantityType) -> np.ndarray:
        if value.quantity_type is not quantity_type or not isinstance(value.value, list):
            raise ValueError(f"expected vector {quantity_type.value} quantity")
        return np.asarray(
            canonicalize_quantity(value.value, value.unit, quantity_type), dtype=float
        )

    @staticmethod
    def _uncertainty_values(
        value: QuantitySpec, channel_count: int, quantity_type: QuantityType
    ) -> np.ndarray:
        if value.quantity_type is not quantity_type:
            raise ValueError(f"data_uncertainty must be {quantity_type.value}")
        converted = canonicalize_quantity(value.value, value.unit, quantity_type)
        if isinstance(converted, float):
            values = np.full(channel_count, converted)
        else:
            values = np.asarray(converted, dtype=float).reshape(-1)
            if values.size != channel_count:
                raise ValueError("data_uncertainty channel count does not match observations")
        if not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError("data_uncertainty must contain positive finite values")
        return values

    @staticmethod
    def _validate_observation_times(observations: np.ndarray, config: TDEMInversionSpec) -> None:
        configured_times = SimPEGTDEM1DPlugin._vector_quantity(
            config.system.times, QuantityType.TIME
        )
        if observations.size != configured_times.size or not np.allclose(
            observations["time_s"], configured_times, rtol=1e-10, atol=1e-15
        ):
            raise ValueError(
                "observation time_s channels must exactly match tdem_inversion.system.times"
            )

    @staticmethod
    def _load_observations(path: Path, quantity_type: QuantityType) -> np.ndarray:
        try:
            table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to read observation CSV: {error}") from error
        response_column = SimPEGTDEM1DPlugin._observation_column(quantity_type)
        required = {"time_s", response_column}
        names = set(table.dtype.names or ())
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"observation CSV is missing columns: {', '.join(missing)}")
        table = np.atleast_1d(table)
        if (
            table.size == 0
            or not np.isfinite(table["time_s"]).all()
            or not np.isfinite(table[response_column]).all()
            or np.any(table["time_s"] <= 0)
            or np.any(np.diff(table["time_s"]) <= 0)
        ):
            raise ValueError(
                "observation CSV must contain finite rows with increasing positive time_s"
            )
        return table

    @staticmethod
    def _receiver_quantity(receiver_quantity: str) -> QuantityType:
        return QuantityType(receiver_quantity)

    @staticmethod
    def _observation_column(quantity_type: QuantityType) -> str:
        return {
            QuantityType.MAGNETIC_FLUX_DENSITY: "magnetic_flux_density_t",
            QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE: (
                "magnetic_flux_density_time_derivative_t_s"
            ),
        }[quantity_type]

    @staticmethod
    def _response_suffix(quantity_type: QuantityType) -> str:
        return {
            QuantityType.MAGNETIC_FLUX_DENSITY: "magnetic_flux_density_t",
            QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE: (
                "magnetic_flux_density_time_derivative_t_s"
            ),
        }[quantity_type]

    @staticmethod
    def _response_unit(quantity_type: QuantityType) -> str:
        return {
            QuantityType.MAGNETIC_FLUX_DENSITY: "T",
            QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE: "T/s",
        }[quantity_type]

    @staticmethod
    def _build_waveform(tdem: Any, config: Any) -> Any:
        if config.system.waveform == "step_off":
            return tdem.sources.StepOffWaveform()
        assert config.system.waveform_times is not None
        assert config.system.waveform_current_fractions is not None
        return tdem.sources.PiecewiseLinearWaveform(
            SimPEGTDEM1DPlugin._vector_quantity(config.system.waveform_times, QuantityType.TIME),
            np.asarray(config.system.waveform_current_fractions, dtype=float),
        )

    def _artifact(
        self,
        spec: RunSpec,
        context: PluginContext,
        path: Path,
        artifact_type: str,
        quantity: QuantityType,
        unit: str,
    ) -> ArtifactManifest:
        return ArtifactManifest(
            artifact_type=artifact_type,
            physical_quantity=quantity,
            units=unit,
            source_run_id=spec.run_id,
            relative_path=path.relative_to(context.artifact_root).as_posix(),
        )
