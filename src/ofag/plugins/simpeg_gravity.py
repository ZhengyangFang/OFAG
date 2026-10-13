"""A real, small-scale SimPEG 3D gravity inversion adapter."""

import json
import logging
from collections.abc import Callable
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
    GravityInversionSpec,
    GravityModelSpec,
    GravityOptimizerKind,
    GravityOptimizerSpec,
    GravityRegularizationKind,
    GravMagJointInversionSpec,
    JointGravityPropertySpec,
    JointMagneticsPropertySpec,
    MagneticsInversionSpec,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    TensorMeshSpec,
    TreeMeshSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.engines.simpeg import conventions
from ofag.engines.simpeg.petrophysics import declared_mixture
from ofag.engines.simpeg.units import (
    density_from_simpeg,
    density_to_simpeg,
    gravity_anomaly_from_simpeg,
    gravity_anomaly_to_simpeg,
    gravity_to_simpeg,
)
from ofag.engines.simpeg.visualization import render_active_model_slice, render_observation_map
from ofag.plugins.protocol import PluginContext, configuration_field


def chi_squared(phi_data: float, observation_count: int) -> float:
    """SimPEG's data objective as the reduced chi-squared a reader expects."""
    return 2.0 * float(phi_data) / max(1, int(observation_count))


class SimPEGGravity3DPlugin:
    """Least-squares density-contrast inversion on OFAG tensor or octree meshes."""

    plugin_id = "simpeg.pf.gravity3d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return GravityInversionSpec

    @staticmethod
    def _declared_configuration(spec: RunSpec) -> GravityInversionSpec | None:
        """The controls this run states, in whichever form it states them."""
        return spec.physics_as(GravityInversionSpec) or spec.gravity_inversion

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.GRAVITY_ACCELERATION,),
            supported_meshes=("TensorMesh", "TreeMesh"),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Initial adapter supports gz gravity only and local-process runs.",
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
        declared = self._declared_configuration(spec)
        if (
            declared is not None
            and declared.simulation.engine == "choclo"
            and find_spec("choclo") is None
        ):
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "gravity_inversion", "simulation.engine"),
                    message="Choclo is not installed",
                    remediation="install the optional SimPEG extra with the Choclo dependency",
                )
            )
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message="simpeg.pf.gravity3d requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        if spec.dataset.physical_quantity is not QuantityType.GRAVITY_ACCELERATION:
            issues.append(
                ValidationIssue(
                    field="dataset.physical_quantity",
                    message="SimPEG gravity requires gravity_acceleration observations",
                    remediation=(
                        "declare the source data as gravity_acceleration with explicit units"
                    ),
                )
            )
        if spec.mesh is None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="SimPEG gravity requires a TensorMeshSpec or TreeMeshSpec",
                    remediation="provide a metric tensor or octree mesh specification in metres",
                )
            )
        if isinstance(spec.mesh, TensorMeshSpec) and spec.mesh.dimension != 3:
            issues.append(
                ValidationIssue(
                    field="mesh.shape",
                    message="SimPEG gravity is a volume method and requires a 3D mesh",
                    remediation="give the mesh Easting, Northing and Elevation extents",
                )
            )
        observations_path = self._string_parameter(spec, "observations_path")
        if observations_path is None:
            issues.append(
                ValidationIssue(
                    field="parameters.observations_path",
                    message="a CSV with x_m,y_m,z_m,gravity_mgal is required",
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
                        remediation="provide finite x_m,y_m,z_m,gravity_mgal columns",
                    )
                )
        self._validate_topography(spec, issues)
        if declared is not None:
            self._validate_array_inputs(
                declared, issues, configuration_field(spec, "gravity_inversion")
            )
        required_parameters = (
            ("data_uncertainty",)
            if declared is not None
            else ("initial_density_contrast", "data_uncertainty")
        )
        for parameter in required_parameters:
            value = spec.parameters.get(parameter)
            if not isinstance(value, QuantitySpec):
                issues.append(
                    ValidationIssue(
                        field=f"parameters.{parameter}",
                        message=f"{parameter} must be an explicit QuantitySpec",
                        remediation=(
                            "use density_contrast in g/cm^3 for the initial model"
                            if parameter == "initial_density_contrast"
                            else "use gravity_acceleration in mGal for uncertainty"
                        ),
                    )
                )
            elif value.quantity_type is not self._expected_parameter_quantity(parameter):
                issues.append(
                    ValidationIssue(
                        field=f"parameters.{parameter}.quantity_type",
                        message=f"{parameter} has an incompatible quantity type",
                        remediation="use the quantity type required by this gravity adapter",
                    )
                )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (conventions.gravity_sign(), conventions.potential_field_placement("gravity"))

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        if spec.mesh is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        observation_count = 0
        observations_path = self._string_parameter(spec, "observations_path")
        if observations_path is not None and Path(observations_path).is_file():
            try:
                observation_count = len(self._load_observations(Path(observations_path)))
            except ValueError:
                observation_count = 0
        cells = self._estimated_mesh_cells(spec, observation_count)
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
        observations_path = Path(self._required_string_parameter(spec, "observations_path"))
        observations = self._load_observations(observations_path)
        inversion_config = self._inversion_config(spec)
        # Optional dependency imports stay inside execution so `ofag plugins` works without SimPEG.
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
        from simpeg.potential_fields import gravity  # type: ignore[import-untyped]

        topography_path = self._string_parameter(spec, "topography_path")
        topography = (
            self._load_topography(Path(topography_path)) if topography_path is not None else None
        )
        receiver_locations = np.c_[observations["x_m"], observations["y_m"], observations["z_m"]]
        tiling_config = inversion_config.simulation.tiling
        if tiling_config.enabled:
            mesh, local_meshes, tile_indices = self._build_tiled_mesh(
                spec,
                receiver_locations,
                topography,
                tiling_config.tile_count,
                tiling_config.partition_axis,
            )
        else:
            mesh = self._build_mesh(spec, receiver_locations, topography)
            local_meshes = []
            tile_indices = []
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
        observed_mgal = np.asarray(
            gravity_anomaly_to_simpeg(observations["gravity_mgal"]), dtype=float
        )
        uncertainty_mgal = self._quantity_parameter(
            spec, "data_uncertainty", QuantityType.GRAVITY_ACCELERATION
        )
        uncertainty_mgal = float(gravity_to_simpeg(uncertainty_mgal))
        if uncertainty_mgal <= 0:
            raise ValueError("parameters.data_uncertainty must be positive")
        run_dir = context.artifact_root / str(spec.run_id)
        tiled_simulations: list[tuple[np.ndarray, Any]] = []
        if tiling_config.enabled:
            run_dir.mkdir(parents=True, exist_ok=True)
            dmisfit, tiled_simulations = self._build_tiled_data_misfit(
                data,
                data_misfit,
                gravity,
                maps,
                mesh,
                active_cells,
                local_meshes,
                tile_indices,
                receiver_locations,
                observed_mgal,
                uncertainty_mgal,
                inversion_config,
                run_dir,
            )
            simulation: Any | None = None
        else:
            receivers = gravity.receivers.Point(receiver_locations, components="gz")
            survey = gravity.survey.Survey(gravity.sources.SourceField([receivers]))
            model_map = maps.IdentityMap(nP=active_count)
            simulation_options: dict[str, Any] = {
                "survey": survey,
                "mesh": mesh,
                "rhoMap": model_map,
                "active_cells": active_cells,
                "store_sensitivities": "ram",
                "engine": inversion_config.simulation.engine,
                "numba_parallel": inversion_config.simulation.numba_parallel,
                "sensitivity_dtype": getattr(np, inversion_config.simulation.sensitivity_dtype),
            }
            if inversion_config.simulation.engine == "geoana":
                simulation_options["n_processes"] = inversion_config.simulation.n_processes
            simulation = gravity.simulation.Simulation3DIntegral(**simulation_options)
            observed_data = data.Data(
                survey,
                dobs=observed_mgal,
                standard_deviation=np.full(observed_mgal.size, uncertainty_mgal),
            )
            dmisfit = data_misfit.L2DataMisfit(data=observed_data, simulation=simulation)
        initial_density_si = self._model_quantity(
            inversion_config.model.initial_density_contrast, "initial_density_contrast"
        )
        lower_bound_si = self._model_quantity(inversion_config.model.lower_bound, "lower_bound")
        upper_bound_si = self._model_quantity(inversion_config.model.upper_bound, "upper_bound")
        if lower_bound_si >= upper_bound_si:
            raise ValueError("gravity model lower_bound must be smaller than upper_bound")
        initial_model = self._model_array_or_constant(
            inversion_config.model.initial_model,
            initial_density_si,
            active_cells,
            mesh.nC,
            QuantityType.DENSITY_CONTRAST,
        )
        reference_model = self._model_array_or_constant(
            inversion_config.model.reference_model,
            initial_density_si,
            active_cells,
            mesh.nC,
            QuantityType.DENSITY_CONTRAST,
        )
        regularizer = self._build_regularization(
            regularization,
            mesh,
            active_cells,
            reference_model,
            inversion_config,
        )
        optimizer = self._build_optimizer(
            optimization,
            inversion_config,
            active_count,
            float(density_to_simpeg(lower_bound_si)),
            float(density_to_simpeg(upper_bound_si)),
        )
        run_dir = context.run_dir(spec.run_id)

        # An interrupted run continues from the model it had reached rather than from
        # the configured start.
        checkpoint = context.resume_from(spec)
        resumed_from_iteration: int | None = None
        if checkpoint is not None:
            saved = checkpoint.state.get("model_path")
            if isinstance(saved, str) and Path(saved).is_file():
                candidate = np.asarray(np.load(saved, allow_pickle=False), dtype=float)
                # A checkpoint from a mesh of a different size cannot be a starting
                # model for this one, and quietly padding it would be inventing values.
                if candidate.shape == np.shape(initial_model):
                    initial_model = candidate
                    resumed_from_iteration = checkpoint.iteration
                    context.emit(
                        RunEvent(
                            run_id=spec.run_id,
                            event_type="state",
                            iteration=checkpoint.iteration,
                            message=(
                                f"resumed from checkpoint at iteration {checkpoint.iteration}"
                            ),
                        )
                    )

        def write_checkpoint(iteration: int, model: np.ndarray) -> None:
            """Save the current model so an interruption is not a total loss."""
            model_path = run_dir / "checkpoint_model.npy"
            np.save(model_path, np.asarray(model, dtype=float))
            context.checkpoint(
                spec,
                {"model_path": str(model_path), "parameterisation": "density_contrast_g_cc"},
                plugin_id=self.plugin_id,
                plugin_version=self.plugin_version,
                iteration=iteration,
            )

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
                fixed_beta = (
                    inversion_config.beta.fixed_beta
                    if inversion_config.beta.estimation is BetaEstimationKind.FIXED
                    else 1.0
                )
                inverse_problem_instance = inverse_problem.BaseInvProblem(
                    dmisfit, regularizer, optimizer, beta=fixed_beta
                )
                directive_list, metrics_directive = self._build_directives(
                    directives,
                    inversion_config,
                    spec.seed,
                    progress_callback=write_progress,
                    checkpoint_callback=write_checkpoint,
                )
                inverse = inversion.BaseInversion(
                    inverse_problem_instance,
                    directiveList=directive_list,
                )
                recovered_g_cc = np.asarray(inverse.run(initial_model), dtype=float)
                if simulation is not None:
                    predicted_mgal = np.asarray(simulation.dpred(recovered_g_cc), dtype=float)
                else:
                    predicted_mgal = np.empty(observed_mgal.size, dtype=float)
                    for indices, tile_simulation in tiled_simulations:
                        predicted_mgal[indices] = tile_simulation.dpred(recovered_g_cc)
        finally:
            simpeg_logger.disabled = previous_logger_state
        predicted_mgal = np.asarray(gravity_anomaly_from_simpeg(predicted_mgal), dtype=float)
        recovered_g_cc = np.asarray(density_from_simpeg(recovered_g_cc), dtype=float)
        residual_mgal = predicted_mgal - observations["gravity_mgal"]
        normalized_residual = residual_mgal / uncertainty_mgal
        phi_data = float(0.5 * np.dot(normalized_residual, normalized_residual))
        phi_model = float(regularizer(recovered_g_cc))

        model_path = run_dir / "recovered_density_g_cc.npy"
        prediction_path = run_dir / "predicted_gravity_mgal.npy"
        residual_path = run_dir / "residual_gravity_mgal.npy"
        normalized_residual_path = run_dir / "normalized_residual.npy"
        log_path = run_dir / "simpeg.log"
        observation_figure_path = run_dir / "observed_gravity_map.png"
        prediction_figure_path = run_dir / "predicted_gravity_map.png"
        residual_figure_path = run_dir / "residual_gravity_map.png"
        model_figure_path = run_dir / "recovered_density_slice.png"
        np.save(model_path, recovered_g_cc)
        np.save(prediction_path, predicted_mgal)
        np.save(residual_path, residual_mgal)
        np.save(normalized_residual_path, normalized_residual)
        log_path.write_text(engine_log.getvalue(), encoding="utf-8")
        render_observation_map(
            receiver_locations,
            observed_mgal,
            observation_figure_path,
            title="Observed gravity acceleration",
            unit="mGal",
        )
        render_observation_map(
            receiver_locations,
            predicted_mgal,
            prediction_figure_path,
            title="Predicted gravity acceleration",
            unit="mGal",
        )
        render_observation_map(
            receiver_locations,
            residual_mgal,
            residual_figure_path,
            title="Gravity residual (predicted − observed)",
            unit="mGal",
        )
        render_active_model_slice(
            mesh,
            active_cells,
            recovered_g_cc,
            model_figure_path,
            title="Recovered density contrast",
            unit="g/cm^3",
        )
        artifacts: list[ArtifactManifest] = [
            self._artifact(
                spec,
                context,
                model_path,
                "recovered_model",
                QuantityType.DENSITY_CONTRAST,
                "g/cm^3",
            ),
            self._artifact(
                spec,
                context,
                prediction_path,
                "predicted_data",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                residual_path,
                "residual_data",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
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
                spec,
                context,
                log_path,
                "engine_log",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                observation_figure_path,
                "observation_map",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                prediction_figure_path,
                "prediction_map",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                residual_figure_path,
                "residual_map",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                model_figure_path,
                "model_slice",
                QuantityType.DENSITY_CONTRAST,
                "g/cm^3",
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
        if tiling_config.enabled:
            tiling_manifest_path = run_dir / "tiling_manifest.json"
            tiling_manifest_path.write_text(
                json.dumps(
                    {
                        "partition_axis": tiling_config.partition_axis,
                        "sensitivity_storage": tiling_config.sensitivity_storage,
                        "tile_count": len(tiled_simulations),
                        "tiles": [
                            {
                                "index": index,
                                "observation_count": int(indices.size),
                                "local_mesh_cells": int(tile_simulation.mesh.nC),
                                "local_active_cells": int(tile_simulation.active_cells.sum()),
                            }
                            for index, (indices, tile_simulation) in enumerate(tiled_simulations)
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            artifacts.append(
                self._artifact(
                    spec,
                    context,
                    tiling_manifest_path,
                    "tiling_manifest",
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
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=inversion_config.optimizer.max_iterations,
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
                "solver": "least_squares_gravity3d",
                "mesh_kind": type(mesh).__name__,
                "tile_count": len(tiled_simulations),
                "observation_count": int(observed_mgal.size),
                "mesh_cells": int(mesh.nC),
                "model_cells": active_count,
                "topography_applied": topography is not None,
                "phi_data": phi_data,
                "chi_squared": chi_squared(phi_data, int(observed_mgal.size)),
                "phi_model": phi_model,
                "data_unit": "mGal",
                "model_unit": "g/cm^3",
                # A result that continued an interrupted solve is not the same object as
                # one that ran straight through, and a reader comparing iteration counts
                # needs to know which this is.
                "resumed": resumed_from_iteration is not None,
                "resumed_from_iteration": (
                    -1 if resumed_from_iteration is None else resumed_from_iteration
                ),
            },
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _expected_parameter_quantity(parameter: str) -> QuantityType:
        return {
            "initial_density_contrast": QuantityType.DENSITY_CONTRAST,
            "data_uncertainty": QuantityType.GRAVITY_ACCELERATION,
        }[parameter]

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
    def _integer_parameter(
        spec: RunSpec, name: str, *, default: int, minimum: int, maximum: int
    ) -> int:
        value = spec.parameters.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"parameters.{name} must be an integer from {minimum} to {maximum}")
        return value

    @staticmethod
    def _quantity_parameter(spec: RunSpec, name: str, quantity_type: QuantityType) -> float:
        value = spec.parameters.get(name)
        if not isinstance(value, QuantitySpec) or value.quantity_type is not quantity_type:
            raise ValueError(f"parameters.{name} must be a {quantity_type.value} QuantitySpec")
        if isinstance(value.value, list):
            raise ValueError(f"parameters.{name} must be a scalar quantity")
        return float(canonicalize_quantity(value.value, value.unit, quantity_type))

    def _inversion_config(self, spec: RunSpec) -> GravityInversionSpec:
        declared = self._declared_configuration(spec)
        if declared is not None:
            return declared
        initial_density = self._quantity_parameter(
            spec, "initial_density_contrast", QuantityType.DENSITY_CONTRAST
        )
        max_iterations = self._integer_parameter(
            spec, "max_iterations", default=5, minimum=1, maximum=50
        )
        return GravityInversionSpec(
            model=GravityModelSpec(
                initial_density_contrast=QuantitySpec(
                    value=initial_density,
                    quantity_type=QuantityType.DENSITY_CONTRAST,
                    unit="g/cm^3",
                )
            ),
            optimizer=GravityOptimizerSpec(max_iterations=max_iterations),
        )

    @staticmethod
    def _model_quantity(value: QuantitySpec, name: str) -> float:
        if isinstance(value.value, list):
            raise ValueError(f"gravity_inversion.model.{name} must be scalar")
        return float(canonicalize_quantity(value.value, value.unit, QuantityType.DENSITY_CONTRAST))

    @staticmethod
    def _build_regularization(
        regularization: Any,
        mesh: Any,
        active_cells: np.ndarray,
        initial_model: np.ndarray,
        config: (
            GravityInversionSpec
            | MagneticsInversionSpec
            | JointGravityPropertySpec
            | JointMagneticsPropertySpec
        ),
        mapping: Any | None = None,
    ) -> Any:
        regularization_config = config.regularization
        common = {
            "active_cells": active_cells,
            "alpha_s": regularization_config.alpha_s,
            "alpha_x": regularization_config.alpha_x,
            "alpha_y": regularization_config.alpha_y,
            "alpha_z": regularization_config.alpha_z,
            "alpha_xx": regularization_config.alpha_xx,
            "alpha_yy": regularization_config.alpha_yy,
            "alpha_zz": regularization_config.alpha_zz,
            "length_scale_x": regularization_config.length_scale_x,
            "length_scale_y": regularization_config.length_scale_y,
            "length_scale_z": regularization_config.length_scale_z,
            "reference_model": initial_model,
            "reference_model_in_smooth": config.model.reference_model_in_smooth,
            "weights": {
                name: SimPEGGravity3DPlugin._regularization_weight_array(
                    item, active_cells, int(mesh.nC)
                )
                for name, item in regularization_config.cell_weights.items()
            }
            or None,
        }
        if mapping is not None:
            common["mapping"] = mapping
        if regularization_config.kind is GravityRegularizationKind.PETROPHYSICAL:
            return SimPEGGravity3DPlugin._build_petrophysical_regularization(
                regularization, mesh, active_cells, common, config, mapping
            )
        if regularization_config.kind is GravityRegularizationKind.L2:
            return regularization.WeightedLeastSquares(mesh, **common)
        return regularization.Sparse(
            mesh,
            **common,
            norms=regularization_config.norms,
            gradient_type=regularization_config.gradient_type,
            irls_scaled=regularization_config.irls_scaled,
            irls_threshold=regularization_config.irls_threshold,
        )

    @staticmethod
    def _build_petrophysical_regularization(
        regularization: Any,
        mesh: Any,
        active_cells: np.ndarray,
        common: dict[str, Any],
        config: (
            GravityInversionSpec
            | MagneticsInversionSpec
            | JointGravityPropertySpec
            | JointMagneticsPropertySpec
        ),
        mapping: Any | None,
    ) -> Any:
        from simpeg import maps

        if mapping is not None:
            # A joint PGI shares one mixture across both properties, so that its classes
            # are rocks rather than a density class and a susceptibility class that
            # happen to be listed together.
            raise ValueError(
                "petrophysical regularization is not available for the joint inversion: "
                "a joint PGI needs one mixture over both properties, which this does not build"
            )
        regularization_config = config.regularization
        classes = regularization_config.petrophysical_classes
        expected = (
            QuantityType.DENSITY_CONTRAST
            if isinstance(config, GravityInversionSpec | JointGravityPropertySpec)
            else QuantityType.SUSCEPTIBILITY
        )
        means = np.empty(len(classes))
        spreads = np.empty(len(classes))
        for index, item in enumerate(classes):
            if item.value.quantity_type is not expected:
                raise ValueError(
                    f"petrophysical class {item.name!r} is a {item.value.quantity_type}, "
                    f"but this inversion recovers {expected}"
                )
            means[index] = SimPEGGravity3DPlugin._to_engine_units(item.value, expected)
            spreads[index] = SimPEGGravity3DPlugin._to_engine_units(
                item.standard_deviation, expected
            )
        declared = [item.proportion for item in classes]
        proportions = (
            np.asarray(declared, dtype=float)
            if all(share is not None for share in declared)
            else np.full(len(classes), 1.0 / len(classes))
        )
        mixture = declared_mixture(mesh, active_cells, means, spreads, proportions)

        active_count = int(np.count_nonzero(active_cells))
        return regularization.PGI(
            mesh,
            mixture,
            # PGI sizes its own wires from the whole mesh unless told otherwise, which
            # does not match a model defined on the active cells alone.
            wiresmap=maps.Wires(("model", active_count)),
            maplist=[maps.IdentityMap(nP=active_count)],
            alpha_pgi=regularization_config.alpha_pgi,
            active_cells=active_cells,
            alpha_x=common["alpha_x"],
            alpha_y=common["alpha_y"],
            alpha_z=common["alpha_z"],
            alpha_xx=common["alpha_xx"],
            alpha_yy=common["alpha_yy"],
            alpha_zz=common["alpha_zz"],
            reference_model=common["reference_model"],
            reference_model_in_smooth=common["reference_model_in_smooth"],
        )

    @staticmethod
    def _to_engine_units(value: QuantitySpec, quantity_type: QuantityType) -> float:
        canonical = canonicalize_quantity(value.value, value.unit, quantity_type)
        if quantity_type is QuantityType.DENSITY_CONTRAST:
            return float(density_to_simpeg(canonical))
        return float(canonical)

    @staticmethod
    def _model_array_or_constant(
        source: ArrayInputSpec | None,
        constant_si: float,
        active_cells: np.ndarray,
        mesh_cell_count: int,
        quantity_type: QuantityType,
    ) -> np.ndarray:
        if source is None:
            canonical = np.full(int(active_cells.sum()), constant_si)
        else:
            canonical = SimPEGGravity3DPlugin._load_array_input(
                source, active_cells, mesh_cell_count
            )
        if quantity_type is QuantityType.DENSITY_CONTRAST:
            return np.asarray(density_to_simpeg(canonical), dtype=float)
        return canonical

    @staticmethod
    def _load_array_input(
        source: ArrayInputSpec, active_cells: np.ndarray, mesh_cell_count: int
    ) -> np.ndarray:
        path = Path(source.path)
        try:
            values = np.asarray(np.load(path, allow_pickle=False), dtype=float).reshape(-1)
        except (OSError, ValueError) as error:
            raise ValueError(f"unable to load numeric array {source.path}: {error}") from error
        active_count = int(active_cells.sum())
        if values.size == mesh_cell_count:
            values = values[active_cells]
        elif values.size != active_count:
            raise ValueError(
                f"array {source.path} must contain {active_count} active or "
                f"{mesh_cell_count} mesh values"
            )
        if not np.isfinite(values).all():
            raise ValueError(f"array {source.path} must contain only finite values in active cells")
        canonical = canonicalize_quantity(values, source.unit, source.quantity_type)
        return np.asarray(canonical, dtype=float)

    @staticmethod
    def _regularization_weight_array(
        source: ArrayInputSpec, active_cells: np.ndarray, mesh_cell_count: int
    ) -> np.ndarray:
        values = SimPEGGravity3DPlugin._load_array_input(source, active_cells, mesh_cell_count)
        if np.any(values <= 0):
            raise ValueError(f"regularization weights in {source.path} must be strictly positive")
        return values

    @staticmethod
    def _build_optimizer(
        optimization: Any,
        config: GravityInversionSpec | MagneticsInversionSpec | GravMagJointInversionSpec,
        active_count: int,
        lower_bound: float,
        upper_bound: float,
    ) -> Any:
        optimizer_config = config.optimizer
        common = {
            "maxIter": optimizer_config.max_iterations,
            "maxIterLS": optimizer_config.max_line_search_iterations,
            "cg_maxiter": min(optimizer_config.cg_max_iterations, active_count),
            "cg_rtol": optimizer_config.cg_relative_tolerance,
            "cg_atol": optimizer_config.cg_absolute_tolerance,
            "tolF": optimizer_config.tolerance_f,
            "tolX": optimizer_config.tolerance_x,
            "tolG": optimizer_config.tolerance_g,
        }
        if optimizer_config.kind is GravityOptimizerKind.INEXACT_GAUSS_NEWTON:
            return optimization.InexactGaussNewton(**common)
        return optimization.ProjectedGNCG(
            **common,
            lower=lower_bound,
            upper=upper_bound,
            step_active_set=optimizer_config.step_active_set,
            active_set_grad_scale=optimizer_config.active_set_gradient_scale,
        )

    @staticmethod
    def _build_directives(
        directives: Any,
        config: GravityInversionSpec | MagneticsInversionSpec | GravMagJointInversionSpec,
        seed: int,
        progress_callback: Callable[[int, float, float, float], None] | None = None,
        checkpoint_callback: Callable[[int, Any], None] | None = None,
    ) -> tuple[list[Any], Any | None]:
        items: list[Any] = []
        directive_config = config.directives
        weighting = directive_config.sensitivity_weighting
        if weighting.enabled:
            items.append(
                directives.UpdateSensitivityWeights(
                    every_iteration=weighting.every_iteration,
                    threshold_value=weighting.threshold_value,
                    threshold_method=weighting.threshold_method,
                    normalization_method=weighting.normalization_method,
                )
            )
        beta = config.beta
        if beta.estimation is BetaEstimationKind.BY_EIG:
            items.append(
                directives.BetaEstimate_ByEig(
                    beta0_ratio=beta.beta0_ratio,
                    n_pw_iter=beta.n_power_iterations,
                    random_seed=seed,
                )
            )
        elif beta.estimation is BetaEstimationKind.MAX_DERIVATIVE:
            items.append(
                directives.BetaEstimateMaxDerivative(beta0_ratio=beta.beta0_ratio, random_seed=seed)
            )
        uses_sparse_irls = (
            config.regularization.kind is GravityRegularizationKind.SPARSE_IRLS
            if not isinstance(config, GravMagJointInversionSpec)
            else False
        )
        uses_petrophysics = (
            config.petrophysical is not None
            if isinstance(config, GravMagJointInversionSpec)
            else config.regularization.kind is GravityRegularizationKind.PETROPHYSICAL
        )
        if (
            beta.estimation is not BetaEstimationKind.FIXED
            and not uses_sparse_irls
            and not uses_petrophysics
        ):
            items.append(
                directives.BetaSchedule(
                    coolingFactor=beta.cooling_factor,
                    coolingRate=beta.cooling_rate,
                )
            )
        if uses_sparse_irls:
            irls = directive_config.irls
            items.append(
                directives.UpdateIRLS(
                    cooling_factor=irls.cooling_factor,
                    cooling_rate=irls.cooling_rate,
                    chifact_start=irls.chi_factor_start,
                    chifact_target=irls.chi_factor_target,
                    irls_cooling_factor=irls.threshold_cooling_factor,
                    f_min_change=irls.minimum_phi_model_change,
                    max_irls_iterations=irls.max_iterations,
                    misfit_tolerance=irls.misfit_tolerance,
                    percentile=irls.percentile,
                    verbose=False,
                )
            )
        if uses_petrophysics:
            # Order matters.
            petrophysics = directive_config.petrophysical
            if petrophysics.update_reference:
                update = directives.PGI_UpdateParameters()
                update.update_gmm = petrophysics.learn_classes
                items.append(update)
            items.append(
                directives.MultiTargetMisfits(chifact=directive_config.target_chi_factor or 1.0)
            )
            items.append(directives.PGI_BetaAlphaSchedule(coolingFactor=beta.cooling_factor))
            if petrophysics.reference_in_smoothness:
                items.append(directives.PGI_AddMrefInSmooth())
        elif directive_config.target_chi_factor is not None:
            items.append(directives.TargetMisfit(chifact=directive_config.target_chi_factor))
        if directive_config.update_preconditioner:
            items.append(directives.UpdatePreconditioner())
        metrics_directive: Any | None = None
        if directive_config.save_iteration_metrics:
            if progress_callback is None:
                metrics_directive = directives.SaveOutputEveryIteration(on_disk=False)
            else:
                # Bind the callback locally: narrowing from the branch above is not
                # carried into the nested class body.
                report_progress = progress_callback

                # SimPEG is an untyped import, so its directive base is `Any`.
                save_checkpoint = checkpoint_callback

                class ProgressMetrics(directives.SaveOutputEveryIteration):  # type: ignore[misc]
                    def endIter(self) -> None:  # noqa: N802 - SimPEG callback name
                        super().endIter()
                        report_progress(
                            int(self.opt.iter),
                            float(self.phi[-1]),
                            float(self.phi_d[-1]),
                            float(self.phi_m[-1]),
                        )
                        if save_checkpoint is not None:
                            save_checkpoint(int(self.opt.iter), self.opt.xc)

                metrics_directive = ProgressMetrics(on_disk=False)
            items.append(metrics_directive)
        return items, metrics_directive

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
            self._load_topography(path)
        except ValueError as error:
            issues.append(
                ValidationIssue(
                    field="parameters.topography_path",
                    message=str(error),
                    remediation="provide finite x_m,y_m,z_m topography columns",
                )
            )

    def _validate_array_inputs(
        self, config: GravityInversionSpec, issues: list[ValidationIssue], field: str
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
            path = Path(source.path)
            if not path.is_file():
                issues.append(
                    ValidationIssue(
                        field=field,
                        message=f"array input does not exist: {source.path}",
                        remediation="provide a finite .npy numeric array",
                    )
                )

    @staticmethod
    def _tile_indices(
        receiver_locations: np.ndarray, tile_count: int, partition_axis: str
    ) -> list[np.ndarray]:
        axis = {"x": 0, "y": 1}[partition_axis]
        if receiver_locations.shape[0] < tile_count:
            raise ValueError("gravity tiling tile_count cannot exceed observation count")
        ordered_indices = np.argsort(receiver_locations[:, axis], kind="stable")
        return [
            np.asarray(indices, dtype=int)
            for indices in np.array_split(ordered_indices, tile_count)
            if indices.size
        ]

    @staticmethod
    def _build_tiled_mesh(
        spec: RunSpec,
        receiver_locations: np.ndarray,
        topography: np.ndarray | None,
        tile_count: int,
        partition_axis: str,
    ) -> tuple[Any, list[Any], list[np.ndarray]]:
        """Build local TreeMeshes then merge their refinement into one global mesh."""
        if not isinstance(spec.mesh, TreeMeshSpec):
            raise ValueError("tiled gravity inversion requires a TreeMeshSpec")
        tile_indices = SimPEGGravity3DPlugin._tile_indices(
            receiver_locations, tile_count, partition_axis
        )
        local_meshes = [
            SimPEGGravity3DPlugin._build_tree_mesh(spec, receiver_locations[indices], topography)
            for indices in tile_indices
        ]
        base_points = topography if topography is not None else receiver_locations
        global_mesh = SimPEGGravity3DPlugin._tree_mesh_base(spec, base_points)
        for local_mesh in local_meshes:
            global_mesh.insert_cells(
                local_mesh.cell_centers,
                local_mesh.cell_levels_by_index(np.arange(local_mesh.nC)),
                finalize=False,
            )
        global_mesh.finalize()
        return global_mesh, local_meshes, tile_indices

    @staticmethod
    def _build_tiled_data_misfit(
        data: Any,
        data_misfit: Any,
        gravity: Any,
        maps: Any,
        global_mesh: Any,
        global_active_cells: np.ndarray,
        local_meshes: list[Any],
        tile_indices: list[np.ndarray],
        receiver_locations: np.ndarray,
        observed_mgal: np.ndarray,
        uncertainty_mgal: float,
        config: GravityInversionSpec,
        run_dir: Path,
    ) -> tuple[Any, list[tuple[np.ndarray, Any]]]:
        """Create a SimPEG ``TileMap`` and L2 data misfit for every observation tile."""
        local_misfits: list[Any] = []
        simulations: list[tuple[np.ndarray, Any]] = []
        for index, (indices, local_mesh) in enumerate(zip(tile_indices, local_meshes, strict=True)):
            receivers = gravity.receivers.Point(receiver_locations[indices], components="gz")
            survey = gravity.survey.Survey(gravity.sources.SourceField([receivers]))
            tile_map = maps.TileMap(global_mesh, global_active_cells, local_mesh)
            options: dict[str, Any] = {
                "survey": survey,
                "mesh": local_mesh,
                "rhoMap": tile_map,
                "active_cells": tile_map.local_active,
                "store_sensitivities": config.simulation.tiling.sensitivity_storage,
                "engine": config.simulation.engine,
                "numba_parallel": config.simulation.numba_parallel,
                "sensitivity_dtype": getattr(np, config.simulation.sensitivity_dtype),
            }
            if config.simulation.engine == "geoana":
                options["n_processes"] = config.simulation.n_processes
                if config.simulation.tiling.sensitivity_storage == "disk":
                    options["sensitivity_path"] = str(run_dir / "sensitivities" / f"tile_{index}")
            elif config.simulation.tiling.sensitivity_storage == "disk":
                options["sensitivity_path"] = str(run_dir / "sensitivities" / f"tile_{index}.bin")
            simulation = gravity.simulation.Simulation3DIntegral(**options)
            observed_data = data.Data(
                survey,
                dobs=observed_mgal[indices],
                standard_deviation=np.full(indices.size, uncertainty_mgal),
            )
            local_misfits.append(
                data_misfit.L2DataMisfit(data=observed_data, simulation=simulation)
            )
            simulations.append((indices, simulation))
        global_misfit = local_misfits[0]
        for local_misfit in local_misfits[1:]:
            global_misfit = global_misfit + local_misfit
        return global_misfit, simulations

    @staticmethod
    def _estimated_mesh_cells(spec: RunSpec, observation_count: int) -> int:
        """Return a deliberately conservative pre-run cell count estimate."""
        assert spec.mesh is not None
        if isinstance(spec.mesh, TensorMeshSpec):
            return int(np.prod(spec.mesh.shape))
        cell_size = np.asarray(
            canonicalize_quantity(
                spec.mesh.cell_size.value, spec.mesh.cell_size.unit, QuantityType.LENGTH
            ),
            dtype=float,
        )
        padding = np.asarray(
            [
                canonicalize_quantity(item.value, item.unit, QuantityType.LENGTH)
                for item in spec.mesh.padding_distance
            ],
            dtype=float,
        )
        core_depth = float(
            canonicalize_quantity(
                spec.mesh.depth_core.value,
                spec.mesh.depth_core.unit,
                QuantityType.LENGTH,
            )
        )
        base_cells = int(np.prod(np.ceil((padding.sum(axis=1) + core_depth) / cell_size)))
        # Refinement around at least one source and the receivers can raise the count
        # substantially; keep this independent of an untrusted CSV's geometry.
        return max(1_024, base_cells * max(8, min(64, observation_count * 2)))

    @staticmethod
    def _build_mesh(
        spec: RunSpec, receiver_locations: np.ndarray, topography: np.ndarray | None
    ) -> Any:
        """Build the requested discretize mesh in canonical SI metres."""
        assert spec.mesh is not None
        if isinstance(spec.mesh, TensorMeshSpec):
            from discretize import TensorMesh  # type: ignore[import-untyped]

            return TensorMesh(SimPEGGravity3DPlugin._mesh_widths(spec), origin=spec.mesh.origin)
        if not isinstance(spec.mesh, TreeMeshSpec):  # defensive for future mesh contracts
            raise ValueError(f"unsupported mesh contract: {type(spec.mesh).__name__}")
        return SimPEGGravity3DPlugin._build_tree_mesh(spec, receiver_locations, topography)

    @staticmethod
    def _tree_mesh_base(spec: RunSpec, builder_points: np.ndarray) -> Any:
        """Construct an unrefined TreeMesh whose extents cover the supplied geometry."""
        assert isinstance(spec.mesh, TreeMeshSpec)
        from discretize.utils import mesh_builder_xyz

        cell_size = np.asarray(
            canonicalize_quantity(
                spec.mesh.cell_size.value, spec.mesh.cell_size.unit, QuantityType.LENGTH
            ),
            dtype=float,
        )
        padding_distance = np.asarray(
            [
                canonicalize_quantity(item.value, item.unit, QuantityType.LENGTH)
                for item in spec.mesh.padding_distance
            ],
            dtype=float,
        )
        depth_core = float(
            canonicalize_quantity(
                spec.mesh.depth_core.value,
                spec.mesh.depth_core.unit,
                QuantityType.LENGTH,
            )
        )
        return mesh_builder_xyz(
            builder_points,
            cell_size,
            padding_distance=padding_distance,
            depth_core=depth_core,
            mesh_type="tree",
            tree_diagonal_balance=spec.mesh.diagonal_balance,
        )

    @staticmethod
    def _build_tree_mesh(
        spec: RunSpec, receiver_locations: np.ndarray, topography: np.ndarray | None
    ) -> Any:
        """Refine a TreeMesh near topography and one local set of receivers."""
        assert isinstance(spec.mesh, TreeMeshSpec)
        # The mesh must include both the surface and every receiver.
        mesh_builder_points = (
            np.vstack((topography, receiver_locations))
            if topography is not None
            else receiver_locations
        )
        mesh = SimPEGGravity3DPlugin._tree_mesh_base(spec, mesh_builder_points)
        if topography is not None:
            mesh.refine_surface(
                topography,
                padding_cells_by_level=spec.mesh.surface_padding_cells,
                finalize=False,
            )
        mesh.refine_points(
            receiver_locations,
            padding_cells_by_level=spec.mesh.receiver_padding_cells,
            finalize=True,
        )
        return mesh

    @staticmethod
    def _mesh_widths(spec: RunSpec) -> list[np.ndarray]:
        assert spec.mesh is not None
        if not isinstance(spec.mesh, TensorMeshSpec):
            raise ValueError("tensor mesh widths are not defined for a TreeMeshSpec")
        if spec.mesh.cell_widths is None:
            cell_size = canonicalize_quantity(
                spec.mesh.cell_size.value, spec.mesh.cell_size.unit, QuantityType.LENGTH
            )
            cell_size_array = np.asarray(cell_size, dtype=float)
            dimension = len(spec.mesh.shape)
            if cell_size_array.shape != (dimension,) or np.any(cell_size_array <= 0):
                raise ValueError(f"mesh.cell_size must contain {dimension} positive length values")
            return [
                np.full(axis_size, cell_size_array[axis])
                for axis, axis_size in enumerate(spec.mesh.shape)
            ]
        return [
            np.asarray(
                canonicalize_quantity(item.value, item.unit, QuantityType.LENGTH), dtype=float
            )
            for item in spec.mesh.cell_widths
        ]

    @staticmethod
    def _load_observations(path: Path) -> np.ndarray:
        try:
            table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to read observation CSV: {error}") from error
        required = {"x_m", "y_m", "z_m"}
        names = set(table.dtype.names or ())
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"observation CSV is missing columns: {', '.join(missing)}")
        gravity_column = "gravity_mgal" if "gravity_mgal" in names else "gravity_m_s2"
        if gravity_column not in names:
            raise ValueError("observation CSV is missing a gravity_mgal column")
        table = np.atleast_1d(table)
        required = {*required, gravity_column}
        if table.size == 0 or any(not np.isfinite(table[name]).all() for name in required):
            raise ValueError("observation CSV must contain finite rows")
        normalized = np.empty(
            table.shape,
            dtype=[("x_m", float), ("y_m", float), ("z_m", float), ("gravity_mgal", float)],
        )
        for coordinate in ("x_m", "y_m", "z_m"):
            normalized[coordinate] = table[coordinate]
        source_unit = "mGal" if gravity_column == "gravity_mgal" else "m/s^2"
        normalized["gravity_mgal"] = canonicalize_quantity(
            table[gravity_column], source_unit, QuantityType.GRAVITY_ACCELERATION
        )
        return normalized

    @staticmethod
    def _load_topography(path: Path) -> np.ndarray:
        try:
            table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        except OSError as error:
            raise ValueError(f"unable to read topography CSV: {error}") from error
        required = {"x_m", "y_m", "z_m"}
        names = set(table.dtype.names or ())
        missing = sorted(required - names)
        if missing:
            raise ValueError(f"topography CSV is missing columns: {', '.join(missing)}")
        table = np.atleast_1d(table)
        if table.size == 0 or any(not np.isfinite(table[name]).all() for name in required):
            raise ValueError("topography CSV must contain finite rows")
        return np.asarray(np.c_[table["x_m"], table["y_m"], table["z_m"]], dtype=float)

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
