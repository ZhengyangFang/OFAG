"""SimPEG-backed 3D total-magnetic-intensity inversion adapter."""

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
    ArrayInputSpec,
    ArtifactManifest,
    BetaEstimationKind,
    CapabilityManifest,
    MagneticsInversionSpec,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    TensorMeshSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import (
    canonicalize_quantity,
    convert_from_engine_units,
    convert_to_engine_units,
)
from ofag.engines.simpeg import conventions
from ofag.engines.simpeg.visualization import render_active_model_slice, render_observation_map
from ofag.plugins.protocol import PluginContext, configuration_field
from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin, chi_squared


class SimPEGMagnetics3DPlugin:
    """Least-squares TMI inversion for scalar induced susceptibility."""

    plugin_id = "simpeg.pf.magnetics3d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return MagneticsInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> MagneticsInversionSpec | None:
        """Read this plugin's configuration from whichever form the run uses."""
        return spec.physics_as(MagneticsInversionSpec) or spec.magnetics_inversion

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.MAGNETIC_ANOMALY,),
            supported_meshes=("TensorMesh", "TreeMesh"),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Initial adapter supports total magnetic intensity and scalar induced "
                "susceptibility.",
                "Vector susceptibility, remanence, amplitude data, and tiling are not yet exposed.",
                "Topography is supported through an explicit SI CSV and active cells.",
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
        config = self._configuration(spec)
        if config is None:
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "magnetics_inversion"),
                    message="TMI magnetics requires its inversion controls",
                    remediation=(
                        "provide inducing_field, model, regularization, optimizer, beta, "
                        "and directives"
                    ),
                )
            )
        elif config.simulation.engine == "choclo" and find_spec("choclo") is None:
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "magnetics_inversion", "simulation.engine"),
                    message="Choclo is not installed",
                    remediation="install the optional SimPEG extra with the Choclo dependency",
                )
            )
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message="simpeg.pf.magnetics3d requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        if spec.dataset.physical_quantity is not QuantityType.MAGNETIC_ANOMALY:
            issues.append(
                ValidationIssue(
                    field="dataset.physical_quantity",
                    message="TMI magnetics requires magnetic_anomaly observations",
                    remediation="declare total magnetic intensity observations with explicit units",
                )
            )
        if spec.mesh is None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="TMI magnetics requires a TensorMeshSpec or TreeMeshSpec",
                    remediation="provide a metric tensor or octree mesh specification in metres",
                )
            )
        if isinstance(spec.mesh, TensorMeshSpec) and spec.mesh.dimension != 3:
            issues.append(
                ValidationIssue(
                    field="mesh.shape",
                    message="TMI magnetics is a volume method and requires a 3D mesh",
                    remediation="give the mesh Easting, Northing and Elevation extents",
                )
            )
        observations_path = self._string_parameter(spec, "observations_path")
        if observations_path is None:
            issues.append(
                ValidationIssue(
                    field="parameters.observations_path",
                    message="a CSV with x_m,y_m,z_m,tmi_nt is required",
                    remediation="supply a UTF-8 CSV path relative to the workspace",
                )
            )
        elif not Path(observations_path).is_file():
            issues.append(
                ValidationIssue(
                    field="parameters.observations_path",
                    message=f"observation CSV does not exist: {observations_path}",
                    remediation="generate or fetch the dataset before validating the run",
                )
            )
        else:
            try:
                self._load_observations(Path(observations_path))
            except ValueError as error:
                issues.append(
                    ValidationIssue(
                        field="parameters.observations_path",
                        message=str(error),
                        remediation="provide finite x_m,y_m,z_m,tmi_nt columns",
                    )
                )
        self._validate_topography(spec, issues)
        if config is not None:
            self._validate_array_inputs(
                config, issues, configuration_field(spec, "magnetics_inversion")
            )
        uncertainty = spec.parameters.get("data_uncertainty")
        if not isinstance(uncertainty, QuantitySpec):
            issues.append(
                ValidationIssue(
                    field="parameters.data_uncertainty",
                    message="data_uncertainty must be an explicit QuantitySpec",
                    remediation="use magnetic_anomaly in nT for uncertainty",
                )
            )
        elif uncertainty.quantity_type is not QuantityType.MAGNETIC_ANOMALY:
            issues.append(
                ValidationIssue(
                    field="parameters.data_uncertainty.quantity_type",
                    message="data_uncertainty has an incompatible quantity type",
                    remediation="use magnetic_anomaly for TMI uncertainty",
                )
            )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (conventions.potential_field_placement("magnetics"),)

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        if spec.mesh is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        observation_count = 0
        observations_path = self._string_parameter(spec, "observations_path")
        if observations_path is not None and Path(observations_path).is_file():
            try:
                observation_count = len(self._load_observations(Path(observations_path)))
            except ValueError:
                pass
        cells = SimPEGGravity3DPlugin._estimated_mesh_cells(spec, observation_count)
        sensitivity_mb = max(1, cells * max(1, observation_count) * 8 // (1024 * 1024))
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(256, sensitivity_mb * 3),
            estimated_seconds=max(1, cells * max(1, observation_count) // 50_000),
        )

    def execute(
        self,
        context: PluginContext,
        spec: RunSpec,
    ) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        assert spec.mesh is not None
        config = self._configuration(spec)
        assert config is not None
        observations = self._load_observations(
            Path(self._required_string_parameter(spec, "observations_path"))
        )
        from discretize.utils import active_from_xyz  # type: ignore[import-untyped]
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
        from simpeg.potential_fields import magnetics  # type: ignore[import-untyped]

        topography_path = self._string_parameter(spec, "topography_path")
        topography = (
            SimPEGGravity3DPlugin._load_topography(Path(topography_path))
            if topography_path is not None
            else None
        )
        receiver_locations = np.c_[observations["x_m"], observations["y_m"], observations["z_m"]]
        mesh = SimPEGGravity3DPlugin._build_mesh(spec, receiver_locations, topography)
        active_cells = (
            active_from_xyz(mesh, topography)
            if topography is not None
            else np.ones(mesh.nC, dtype=bool)
        )
        active_count = int(active_cells.sum())
        if active_count == 0:
            raise ValueError("topography leaves no active mesh cells")
        if spec.mesh.active_cells is not None and active_count != spec.mesh.active_cells:
            raise ValueError(
                f"mesh.active_cells expected {spec.mesh.active_cells}, computed {active_count}"
            )

        observed_nt = np.asarray(
            convert_to_engine_units(
                observations["tmi_nt"], QuantityType.MAGNETIC_ANOMALY, "simpeg"
            ),
            dtype=float,
        )
        uncertainty_nt = self._quantity_parameter(
            spec, "data_uncertainty", QuantityType.MAGNETIC_ANOMALY
        )
        uncertainty_simpeg_nt = float(
            convert_to_engine_units(uncertainty_nt, QuantityType.MAGNETIC_ANOMALY, "simpeg")
        )
        if uncertainty_simpeg_nt <= 0:
            raise ValueError("parameters.data_uncertainty must be positive")
        receivers = magnetics.receivers.Point(receiver_locations, components="tmi")
        source = magnetics.sources.UniformBackgroundField(
            [receivers],
            amplitude=float(
                convert_to_engine_units(
                    self._field_quantity(
                        config.inducing_field.amplitude, QuantityType.MAGNETIC_FLUX_DENSITY
                    ),
                    QuantityType.MAGNETIC_FLUX_DENSITY,
                    "simpeg",
                )
            ),
            inclination=float(
                np.degrees(
                    self._field_quantity(config.inducing_field.inclination, QuantityType.ANGLE)
                )
            ),
            declination=float(
                np.degrees(
                    self._field_quantity(config.inducing_field.declination, QuantityType.ANGLE)
                )
            ),
        )
        survey = magnetics.survey.Survey(source)
        simulation_options: dict[str, Any] = {
            "survey": survey,
            "mesh": mesh,
            "chiMap": maps.IdentityMap(nP=active_count),
            "active_cells": active_cells,
            "store_sensitivities": "ram",
            "engine": config.simulation.engine,
            "numba_parallel": config.simulation.numba_parallel,
            "sensitivity_dtype": getattr(np, config.simulation.sensitivity_dtype),
        }
        if config.simulation.engine == "geoana":
            simulation_options["n_processes"] = config.simulation.n_processes
        simulation = magnetics.simulation.Simulation3DIntegral(**simulation_options)
        observed_data = data.Data(
            survey,
            dobs=observed_nt,
            standard_deviation=np.full(observed_nt.size, uncertainty_simpeg_nt),
        )
        dmisfit = data_misfit.L2DataMisfit(data=observed_data, simulation=simulation)
        initial_susceptibility = self._model_quantity(
            config.model.initial_susceptibility, "initial_susceptibility"
        )
        lower_bound = self._model_quantity(config.model.lower_bound, "lower_bound")
        upper_bound = self._model_quantity(config.model.upper_bound, "upper_bound")
        initial_model = SimPEGGravity3DPlugin._model_array_or_constant(
            config.model.initial_model,
            initial_susceptibility,
            active_cells,
            int(mesh.nC),
            QuantityType.SUSCEPTIBILITY,
        )
        reference_model = SimPEGGravity3DPlugin._model_array_or_constant(
            config.model.reference_model,
            initial_susceptibility,
            active_cells,
            int(mesh.nC),
            QuantityType.SUSCEPTIBILITY,
        )
        regularizer = SimPEGGravity3DPlugin._build_regularization(
            regularization, mesh, active_cells, reference_model, config
        )
        optimizer = SimPEGGravity3DPlugin._build_optimizer(
            optimization, config, active_count, lower_bound, upper_bound
        )
        run_dir = context.run_dir(spec.run_id)

        def write_progress(
            iteration: int, phi_total: float, phi_data: float, phi_model: float
        ) -> None:
            """Publish SimPEG's completed iterations to the API monitor."""
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
                fixed_beta = (
                    config.beta.fixed_beta
                    if config.beta.estimation is BetaEstimationKind.FIXED
                    else 1.0
                )
                inverse_problem_instance = inverse_problem.BaseInvProblem(
                    dmisfit, regularizer, optimizer, beta=fixed_beta
                )
                directive_list, metrics_directive = SimPEGGravity3DPlugin._build_directives(
                    directives, config, spec.seed, progress_callback=write_progress
                )
                inverse = inversion.BaseInversion(
                    inverse_problem_instance, directiveList=directive_list
                )
                recovered = np.asarray(inverse.run(initial_model), dtype=float)
                predicted_nt = np.asarray(simulation.dpred(recovered), dtype=float)
        finally:
            simpeg_logger.disabled = previous_logger_state

        predicted_nt = np.asarray(
            convert_from_engine_units(predicted_nt, QuantityType.MAGNETIC_ANOMALY, "simpeg"),
            dtype=float,
        )
        residual_nt = predicted_nt - observations["tmi_nt"]
        normalized_residual = residual_nt / uncertainty_nt
        phi_data = float(0.5 * np.dot(normalized_residual, normalized_residual))
        phi_model = float(regularizer(recovered))
        solver_output = engine_log.getvalue()
        line_search_failed = "The linesearch got broken" in solver_output
        model_path = run_dir / "recovered_susceptibility.npy"
        prediction_path = run_dir / "predicted_tmi_nt.npy"
        residual_path = run_dir / "residual_tmi_nt.npy"
        normalized_residual_path = run_dir / "normalized_residual.npy"
        log_path = run_dir / "simpeg.log"
        observation_figure_path = run_dir / "observed_tmi_map.png"
        prediction_figure_path = run_dir / "predicted_tmi_map.png"
        residual_figure_path = run_dir / "residual_tmi_map.png"
        model_figure_path = run_dir / "recovered_susceptibility_slice.png"
        np.save(model_path, recovered)
        np.save(prediction_path, predicted_nt)
        np.save(residual_path, residual_nt)
        np.save(normalized_residual_path, normalized_residual)
        log_path.write_text(solver_output, encoding="utf-8")
        render_observation_map(
            receiver_locations,
            observations["tmi_nt"],
            observation_figure_path,
            title="Observed total magnetic intensity",
            unit="nT",
        )
        render_observation_map(
            receiver_locations,
            predicted_nt,
            prediction_figure_path,
            title="Predicted total magnetic intensity",
            unit="nT",
        )
        render_observation_map(
            receiver_locations,
            residual_nt,
            residual_figure_path,
            title="TMI residual (predicted − observed)",
            unit="nT",
        )
        render_active_model_slice(
            mesh,
            active_cells,
            recovered,
            model_figure_path,
            title="Recovered susceptibility",
            unit="dimensionless",
        )
        artifacts: list[ArtifactManifest] = [
            self._artifact(
                spec,
                context,
                model_path,
                "recovered_model",
                QuantityType.SUSCEPTIBILITY,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                prediction_path,
                "predicted_data",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                residual_path,
                "residual_data",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
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
            self._artifact(
                spec,
                context,
                observation_figure_path,
                "observation_map",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                prediction_figure_path,
                "prediction_map",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                residual_figure_path,
                "residual_map",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                model_figure_path,
                "model_slice",
                QuantityType.SUSCEPTIBILITY,
                "dimensionless",
            ),
        ]
        mesh_geometry_path = run_dir / "mesh_geometry.npz"
        np.savez_compressed(
            mesh_geometry_path,
            cell_centers_m=np.asarray(mesh.cell_centers, dtype=float),
            cell_volumes_m3=np.asarray(mesh.cell_volumes, dtype=float),
            # Each cell's width along each axis.
            cell_widths_m=np.asarray(mesh.h_gridded, dtype=float),
            active_cells=np.asarray(active_cells, dtype=bool),
        )
        artifacts.append(
            self._artifact(
                spec,
                context,
                mesh_geometry_path,
                "mesh_geometry",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            )
        )
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
        final_iteration = (
            max(0, len(metrics_directive.phi) - 1)
            if metrics_directive is not None
            else config.optimizer.max_iterations
        )
        termination_message = (
            "SimPEG stopped because its line search could not find a further descent step; "
            "the last model and diagnostics were saved."
            if line_search_failed
            else "SimPEG completed normally."
        )
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=final_iteration,
                phi_total=phi_data + phi_model,
                phi_data=phi_data,
                phi_model=phi_model,
                message=termination_message,
            )
        )
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "least_squares_magnetics3d_tmi",
                "mesh_kind": type(mesh).__name__,
                "observation_count": int(observed_nt.size),
                "mesh_cells": int(mesh.nC),
                "model_cells": active_count,
                "phi_data": phi_data,
                "chi_squared": chi_squared(phi_data, int(observed_nt.size)),
                "phi_model": phi_model,
                "data_unit": "nT",
                "model_unit": "dimensionless",
                "converged": not line_search_failed,
                "termination_message": termination_message,
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
    def _quantity_parameter(spec: RunSpec, name: str, quantity_type: QuantityType) -> float:
        value = spec.parameters.get(name)
        if not isinstance(value, QuantitySpec) or value.quantity_type is not quantity_type:
            raise ValueError(f"parameters.{name} must be a {quantity_type.value} QuantitySpec")
        if isinstance(value.value, list):
            raise ValueError(f"parameters.{name} must be a scalar quantity")
        return float(canonicalize_quantity(value.value, value.unit, quantity_type))

    @staticmethod
    def _field_quantity(value: QuantitySpec, quantity_type: QuantityType) -> float:
        if isinstance(value.value, list):
            raise ValueError("magnetic inducing-field values must be scalar")
        return float(canonicalize_quantity(value.value, value.unit, quantity_type))

    @staticmethod
    def _model_quantity(value: QuantitySpec, name: str) -> float:
        if isinstance(value.value, list):
            raise ValueError(f"magnetics_inversion.model.{name} must be scalar")
        return float(canonicalize_quantity(value.value, value.unit, QuantityType.SUSCEPTIBILITY))

    def _validate_topography(self, spec: RunSpec, issues: list[ValidationIssue]) -> None:
        topography_path = self._string_parameter(spec, "topography_path")
        if topography_path is None:
            return
        path = Path(topography_path)
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    field="parameters.topography_path",
                    message=f"topography CSV does not exist: {topography_path}",
                    remediation="prepare or import the topography before validating the run",
                )
            )
            return
        try:
            SimPEGGravity3DPlugin._load_topography(path)
        except ValueError as error:
            issues.append(
                ValidationIssue(
                    field="parameters.topography_path",
                    message=str(error),
                    remediation="provide finite x_m,y_m,z_m topography columns",
                )
            )

    @staticmethod
    def _validate_array_inputs(
        config: MagneticsInversionSpec, issues: list[ValidationIssue], field: str
    ) -> None:
        inputs: list[tuple[str, ArrayInputSpec]] = []
        if config.model.initial_model is not None:
            inputs.append((f"{field}.model.initial_model", config.model.initial_model))
        if config.model.reference_model is not None:
            inputs.append((f"{field}.model.reference_model", config.model.reference_model))
        inputs.extend(
            (f"{field}.regularization.cell_weights.{name}", item)
            for name, item in config.regularization.cell_weights.items()
        )
        for field, source in inputs:
            if not Path(source.path).is_file():
                issues.append(
                    ValidationIssue(
                        field=field,
                        message=f"array input does not exist: {source.path}",
                        remediation="provide a finite .npy numeric array",
                    )
                )

    @staticmethod
    def _load_observations(path: Path) -> np.ndarray:
        try:
            table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to read observation CSV: {error}") from error
        required = {"x_m", "y_m", "z_m", "tmi_nt"}
        names = set(table.dtype.names or ())
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"observation CSV is missing columns: {', '.join(missing)}")
        table = np.atleast_1d(table)
        if table.size == 0 or any(not np.isfinite(table[name]).all() for name in required):
            raise ValueError("observation CSV must contain finite rows")
        return table

    @staticmethod
    def _artifact(
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
