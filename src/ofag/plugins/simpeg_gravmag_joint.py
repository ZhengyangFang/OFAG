"""Shared-mesh SimPEG gravity/TMI inversion with cross-gradient coupling."""

import json
import logging
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from importlib.util import find_spec
from io import StringIO
from pathlib import Path
from typing import Any, cast

import numpy as np
from pydantic import BaseModel

from ofag.core.constants import QuantityType
from ofag.core.conventions import ConventionCheck
from ofag.core.schemas import (
    ArrayInputSpec,
    ArtifactManifest,
    BetaEstimationKind,
    CapabilityManifest,
    DataChannelSpec,
    GravMagJointInversionSpec,
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
from ofag.plugins.simpeg_gravity import SimPEGGravity3DPlugin, chi_squared
from ofag.plugins.simpeg_magnetics import SimPEGMagnetics3DPlugin

#: The regularization fields a joint PGI cannot hold one of per property.
_SHARED_SMOOTHNESS_FIELDS = (
    "alpha_x",
    "alpha_y",
    "alpha_z",
    "alpha_xx",
    "alpha_yy",
    "alpha_zz",
    "length_scale_x",
    "length_scale_y",
    "length_scale_z",
)


class SimPEGGravMagJointPlugin:
    """Joint density/susceptibility inversion with an explicit cross-gradient term."""

    plugin_id = "simpeg.joint.gravmag.cross_gradient"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return GravMagJointInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> GravMagJointInversionSpec | None:
        """Read this plugin's configuration from whichever form the run uses."""
        return spec.physics_as(GravMagJointInversionSpec) or spec.gravmag_joint_inversion

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(
                QuantityType.GRAVITY_ACCELERATION,
                QuantityType.MAGNETIC_ANOMALY,
            ),
            supported_meshes=("TensorMesh", "TreeMesh"),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Uses gz gravity and total magnetic intensity on one shared active-cell mesh.",
                "The coupling can use explicit density/susceptibility normalization scales.",
                "Tiling, remanence, vector susceptibility, and separate coupling meshes "
                "are not yet exposed.",
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
                    field=configuration_field(spec, "gravmag_joint_inversion"),
                    message="joint gravity/magnetics requires its inversion controls",
                    remediation=("provide channel references, property controls, and coupling"),
                )
            )
            return ValidationReport(valid=False, issues=tuple(issues))
        gravity_channel = self._require_channel(
            spec, config.gravity_channel, QuantityType.GRAVITY_ACCELERATION, "gravity", issues
        )
        magnetics_channel = self._require_channel(
            spec, config.magnetics_channel, QuantityType.MAGNETIC_ANOMALY, "magnetics", issues
        )
        if gravity_channel is None or magnetics_channel is None:
            return ValidationReport(valid=False, issues=tuple(issues))
        if config.gravity.simulation.engine == "choclo" and find_spec("choclo") is None:
            issues.append(
                ValidationIssue(
                    field=configuration_field(
                        spec, "gravmag_joint_inversion", "gravity.simulation.engine"
                    ),
                    message="Choclo is not installed",
                    remediation="install the optional SimPEG extra with the Choclo dependency",
                )
            )
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message="simpeg.joint.gravmag.cross_gradient requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        if spec.mesh is None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="joint gravity/magnetics requires a TensorMeshSpec or TreeMeshSpec",
                    remediation="provide one metric mesh shared by both physical properties",
                )
            )
        if isinstance(spec.mesh, TensorMeshSpec) and spec.mesh.dimension != 3:
            issues.append(
                ValidationIssue(
                    field="mesh.shape",
                    message="joint gravity/magnetics is a volume method and requires a 3D mesh",
                    remediation="give the mesh Easting, Northing and Elevation extents",
                )
            )
        self._validate_observations(
            gravity_channel.observations_path,
            SimPEGGravity3DPlugin._load_observations,
            f"datasets.{gravity_channel.channel_id}.observations_path",
            "provide finite x_m,y_m,z_m,gravity_mgal columns",
            issues,
        )
        self._validate_observations(
            magnetics_channel.observations_path,
            SimPEGMagnetics3DPlugin._load_observations,
            f"datasets.{magnetics_channel.channel_id}.observations_path",
            "provide finite x_m,y_m,z_m,tmi_nt columns",
            issues,
        )
        self._validate_topography(
            config, issues, configuration_field(spec, "gravmag_joint_inversion", "topography_path")
        )
        self._validate_array_inputs(
            config, issues, configuration_field(spec, "gravmag_joint_inversion")
        )
        for field, quantity in (
            (
                f"datasets.{gravity_channel.channel_id}.data_uncertainty",
                gravity_channel.data_uncertainty,
            ),
            (
                f"datasets.{magnetics_channel.channel_id}.data_uncertainty",
                magnetics_channel.data_uncertainty,
            ),
        ):
            if isinstance(quantity.value, list) or quantity.value <= 0:
                issues.append(
                    ValidationIssue(
                        field=field,
                        message="data uncertainty must be a positive scalar quantity",
                        remediation="provide one positive uncertainty in the declared data unit",
                    )
                )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _require_channel(
        spec: RunSpec,
        channel_id: str,
        expected: QuantityType,
        role: str,
        issues: list[ValidationIssue],
    ) -> DataChannelSpec | None:
        """Resolve one of the two channels this joint inversion needs."""
        channel = spec.channel(channel_id)
        if channel is None:
            available = ", ".join(item.channel_id for item in spec.datasets) or "none"
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "gravmag_joint_inversion", f"{role}_channel"),
                    message=f"no data channel {channel_id!r} is declared; available: {available}",
                    remediation=f"add the {role} observations to datasets with this channel_id",
                )
            )
            return None
        if channel.dataset.physical_quantity is not expected:
            issues.append(
                ValidationIssue(
                    field=f"datasets.{channel_id}.dataset.physical_quantity",
                    message=(
                        f"the {role} channel must declare {expected.value}, "
                        f"not {channel.dataset.physical_quantity.value}"
                    ),
                    remediation=f"point {role}_channel at the {expected.value} observations",
                )
            )
            return None
        return channel

    def conventions(self) -> tuple[ConventionCheck, ...]:
        # Both physics, because a joint inversion is where a sign error in one of them
        # is hardest to see: the other physics absorbs it.
        return (
            conventions.gravity_sign(),
            conventions.potential_field_placement("gravity"),
            conventions.potential_field_placement("magnetics"),
        )

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = self._configuration(spec)
        if spec.mesh is None or config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        gravity_channel = spec.channel(config.gravity_channel)
        magnetics_channel = spec.channel(config.magnetics_channel)
        if gravity_channel is None or magnetics_channel is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        observation_count = self._observation_count(
            gravity_channel.observations_path, SimPEGGravity3DPlugin._load_observations
        ) + self._observation_count(
            magnetics_channel.observations_path, SimPEGMagnetics3DPlugin._load_observations
        )
        cells = SimPEGGravity3DPlugin._estimated_mesh_cells(spec, observation_count)
        sensitivity_mb = max(1, cells * max(1, observation_count) * 8 // (1024 * 1024))
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(256, sensitivity_mb * 5),
            estimated_seconds=max(1, cells * max(1, observation_count) // 25_000),
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
        gravity_channel = spec.channel(config.gravity_channel)
        magnetics_channel = spec.channel(config.magnetics_channel)
        assert gravity_channel is not None and magnetics_channel is not None
        gravity_observations = SimPEGGravity3DPlugin._load_observations(
            Path(gravity_channel.observations_path)
        )
        magnetic_observations = SimPEGMagnetics3DPlugin._load_observations(
            Path(magnetics_channel.observations_path)
        )
        from discretize.utils import active_from_xyz  # type: ignore[import-untyped]
        from scipy import sparse  # type: ignore[import-untyped]
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
        from simpeg.potential_fields import gravity, magnetics  # type: ignore[import-untyped]

        topography = (
            SimPEGGravity3DPlugin._load_topography(Path(config.topography_path))
            if config.topography_path is not None
            else None
        )
        all_locations = np.vstack(
            [
                np.c_[
                    gravity_observations["x_m"],
                    gravity_observations["y_m"],
                    gravity_observations["z_m"],
                ],
                np.c_[
                    magnetic_observations["x_m"],
                    magnetic_observations["y_m"],
                    magnetic_observations["z_m"],
                ],
            ]
        )
        mesh = SimPEGGravity3DPlugin._build_mesh(spec, all_locations, topography)
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

        wires = maps.Wires(("density", active_count), ("susceptibility", active_count))
        gravity_receivers = gravity.receivers.Point(
            np.c_[
                gravity_observations["x_m"],
                gravity_observations["y_m"],
                gravity_observations["z_m"],
            ],
            components="gz",
        )
        gravity_survey = gravity.survey.Survey(gravity.sources.SourceField([gravity_receivers]))
        magnetic_receivers = magnetics.receivers.Point(
            np.c_[
                magnetic_observations["x_m"],
                magnetic_observations["y_m"],
                magnetic_observations["z_m"],
            ],
            components="tmi",
        )
        field = config.magnetics.inducing_field
        magnetic_source = magnetics.sources.UniformBackgroundField(
            [magnetic_receivers],
            amplitude=float(
                convert_to_engine_units(
                    self._quantity_value(field.amplitude, QuantityType.MAGNETIC_FLUX_DENSITY),
                    QuantityType.MAGNETIC_FLUX_DENSITY,
                    "simpeg",
                )
            ),
            inclination=float(
                np.degrees(self._quantity_value(field.inclination, QuantityType.ANGLE))
            ),
            declination=float(
                np.degrees(self._quantity_value(field.declination, QuantityType.ANGLE))
            ),
        )
        magnetic_survey = magnetics.survey.Survey(magnetic_source)
        gravity_simulation_options: dict[str, Any] = {
            "survey": gravity_survey,
            "mesh": mesh,
            "rhoMap": wires.density,
            "active_cells": active_cells,
            "store_sensitivities": "ram",
            "engine": config.gravity.simulation.engine,
            "numba_parallel": config.gravity.simulation.numba_parallel,
            "sensitivity_dtype": getattr(np, config.gravity.simulation.sensitivity_dtype),
        }
        magnetic_simulation_options: dict[str, Any] = {
            "survey": magnetic_survey,
            "mesh": mesh,
            "chiMap": wires.susceptibility,
            "active_cells": active_cells,
            "store_sensitivities": "ram",
            "engine": config.magnetics.simulation.engine,
            "numba_parallel": config.magnetics.simulation.numba_parallel,
            "sensitivity_dtype": getattr(np, config.magnetics.simulation.sensitivity_dtype),
        }
        if config.gravity.simulation.engine == "geoana":
            gravity_simulation_options["n_processes"] = config.gravity.simulation.n_processes
        if config.magnetics.simulation.engine == "geoana":
            magnetic_simulation_options["n_processes"] = config.magnetics.simulation.n_processes
        gravity_simulation = gravity.simulation.Simulation3DIntegral(**gravity_simulation_options)
        magnetic_simulation = magnetics.simulation.Simulation3DIntegral(
            **magnetic_simulation_options
        )
        gravity_uncertainty_mgal = self._quantity_value(
            gravity_channel.data_uncertainty, QuantityType.GRAVITY_ACCELERATION
        )
        magnetic_uncertainty_nt = self._quantity_value(
            magnetics_channel.data_uncertainty, QuantityType.MAGNETIC_ANOMALY
        )
        gravity_data = data.Data(
            gravity_survey,
            dobs=np.asarray(
                gravity_anomaly_to_simpeg(gravity_observations["gravity_mgal"]), dtype=float
            ),
            standard_deviation=np.full(
                gravity_observations.size, float(gravity_to_simpeg(gravity_uncertainty_mgal))
            ),
        )
        magnetic_data = data.Data(
            magnetic_survey,
            dobs=np.asarray(
                convert_to_engine_units(
                    magnetic_observations["tmi_nt"], QuantityType.MAGNETIC_ANOMALY, "simpeg"
                ),
                dtype=float,
            ),
            standard_deviation=np.full(
                magnetic_observations.size,
                float(
                    convert_to_engine_units(
                        magnetic_uncertainty_nt, QuantityType.MAGNETIC_ANOMALY, "simpeg"
                    )
                ),
            ),
        )
        gravity_misfit = data_misfit.L2DataMisfit(data=gravity_data, simulation=gravity_simulation)
        magnetic_misfit = data_misfit.L2DataMisfit(
            data=magnetic_data, simulation=magnetic_simulation
        )
        density_initial = self._quantity_value(
            config.gravity.model.initial_density_contrast, QuantityType.DENSITY_CONTRAST
        )
        susceptibility_initial = self._quantity_value(
            config.magnetics.model.initial_susceptibility, QuantityType.SUSCEPTIBILITY
        )
        density_model = SimPEGGravity3DPlugin._model_array_or_constant(
            config.gravity.model.initial_model,
            density_initial,
            active_cells,
            int(mesh.nC),
            QuantityType.DENSITY_CONTRAST,
        )
        density_reference = SimPEGGravity3DPlugin._model_array_or_constant(
            config.gravity.model.reference_model,
            density_initial,
            active_cells,
            int(mesh.nC),
            QuantityType.DENSITY_CONTRAST,
        )
        susceptibility_model = SimPEGGravity3DPlugin._model_array_or_constant(
            config.magnetics.model.initial_model,
            susceptibility_initial,
            active_cells,
            int(mesh.nC),
            QuantityType.SUSCEPTIBILITY,
        )
        susceptibility_reference = SimPEGGravity3DPlugin._model_array_or_constant(
            config.magnetics.model.reference_model,
            susceptibility_initial,
            active_cells,
            int(mesh.nC),
            QuantityType.SUSCEPTIBILITY,
        )
        joint_reference = np.r_[density_reference, susceptibility_reference]
        petrophysical_smallness: Any | None = None
        if config.petrophysical is not None:
            property_regularizer = self._build_petrophysical_regularization(
                regularization,
                maps,
                mesh,
                active_cells,
                active_count,
                joint_reference,
                config,
                wires,
            )
            # SimPEG's PGI is the shared smallness followed by one smoothness per wire,
            # in the order the wires were given.
            (
                petrophysical_smallness,
                gravity_regularizer,
                magnetic_regularizer,
            ) = property_regularizer.objfcts
        else:
            gravity_regularizer = SimPEGGravity3DPlugin._build_regularization(
                regularization,
                mesh,
                active_cells,
                joint_reference,
                config.gravity,
                mapping=wires.density,
            )
            magnetic_regularizer = SimPEGGravity3DPlugin._build_regularization(
                regularization,
                mesh,
                active_cells,
                joint_reference,
                config.magnetics,
                mapping=wires.susceptibility,
            )
            property_regularizer = gravity_regularizer + magnetic_regularizer

        class NormalizedCrossGradient(regularization.CrossGradient):  # type: ignore[misc]
            """Delegate cross-gradient calculus to SimPEG after explicit model scaling."""

            def __init__(self, *args: Any, normalization: np.ndarray, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                self._normalization = normalization
                self._normalization_matrix = sparse.diags(normalization)

            def __call__(self, model: np.ndarray) -> float:
                return float(super().__call__(self._normalization * model))

            def deriv(self, model: np.ndarray) -> np.ndarray:
                return cast(
                    np.ndarray,
                    self._normalization
                    * np.asarray(super().deriv(self._normalization * model), dtype=float),
                )

            def deriv2(self, model: np.ndarray, v: np.ndarray | None = None) -> Any:
                scaled_model = self._normalization * model
                if v is None:
                    return (
                        self._normalization_matrix
                        @ super().deriv2(scaled_model)
                        @ self._normalization_matrix
                    )
                return self._normalization * np.asarray(
                    super().deriv2(scaled_model, self._normalization * v), dtype=float
                )

            def calculate_cross_gradient(
                self, model: np.ndarray, normalized: bool = False, rtol: float = 1e-6
            ) -> np.ndarray:
                return np.asarray(
                    super().calculate_cross_gradient(
                        self._normalization * model, normalized=normalized, rtol=rtol
                    ),
                    dtype=float,
                )

        density_scale = float(
            density_to_simpeg(
                self._quantity_value(config.coupling.density_scale, QuantityType.DENSITY_CONTRAST)
            )
        )
        susceptibility_scale = self._quantity_value(
            config.coupling.susceptibility_scale, QuantityType.SUSCEPTIBILITY
        )
        normalization = (
            np.full(2 * active_count, 1.0)
            / np.r_[
                np.full(active_count, density_scale),
                np.full(active_count, susceptibility_scale),
            ]
            if config.coupling.normalize_models
            else np.ones(2 * active_count)
        )
        cross_gradient = NormalizedCrossGradient(
            mesh,
            wire_map=wires,
            active_cells=active_cells,
            approx_hessian=config.coupling.approximate_hessian,
            normalization=normalization,
        )
        # A joint petrophysical inversion couples through the rock, so it does not also
        # couple through structure: the schema refuses a non-zero cross-gradient weight
        # beside it, and the term is left out of the objective.
        joint_regularizer = (
            property_regularizer
            if petrophysical_smallness is not None
            else property_regularizer + config.coupling.weight * cross_gradient
        )
        lower_bound = np.r_[
            np.full(
                active_count,
                float(
                    density_to_simpeg(
                        self._quantity_value(
                            config.gravity.model.lower_bound, QuantityType.DENSITY_CONTRAST
                        )
                    )
                ),
            ),
            np.full(
                active_count,
                self._quantity_value(
                    config.magnetics.model.lower_bound, QuantityType.SUSCEPTIBILITY
                ),
            ),
        ]
        upper_bound = np.r_[
            np.full(
                active_count,
                float(
                    density_to_simpeg(
                        self._quantity_value(
                            config.gravity.model.upper_bound, QuantityType.DENSITY_CONTRAST
                        )
                    )
                ),
            ),
            np.full(
                active_count,
                self._quantity_value(
                    config.magnetics.model.upper_bound, QuantityType.SUSCEPTIBILITY
                ),
            ),
        ]
        optimizer = SimPEGGravity3DPlugin._build_optimizer(
            optimization, config, 2 * active_count, lower_bound, upper_bound
        )
        initial_model = np.r_[density_model, susceptibility_model]
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
                    gravity_misfit + magnetic_misfit,
                    joint_regularizer,
                    optimizer,
                    beta=fixed_beta,
                )
                if config.directive_strategy == "simpeg_cross_gradient_tutorial":
                    directive_list = self._build_tutorial_directives(directives, config)
                    metrics_directive = None
                else:

                    def progress_callback(
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

                    directive_list, metrics_directive = SimPEGGravity3DPlugin._build_directives(
                        directives, config, spec.seed, progress_callback=progress_callback
                    )
                inverse = inversion.BaseInversion(
                    inverse_problem_instance, directiveList=directive_list
                )
                recovered = np.asarray(inverse.run(initial_model), dtype=float)
        finally:
            simpeg_logger.disabled = previous_logger_state
        recovered_density_g_cc, recovered_susceptibility = wires * recovered
        predicted_gravity_mgal = np.asarray(
            gravity_anomaly_from_simpeg(gravity_simulation.dpred(recovered)), dtype=float
        )
        predicted_magnetic_nt = np.asarray(
            convert_from_engine_units(
                magnetic_simulation.dpred(recovered), QuantityType.MAGNETIC_ANOMALY, "simpeg"
            ),
            dtype=float,
        )
        gravity_residual = predicted_gravity_mgal - gravity_observations["gravity_mgal"]
        magnetic_residual = predicted_magnetic_nt - magnetic_observations["tmi_nt"]
        gravity_normalized = gravity_residual / gravity_uncertainty_mgal
        magnetic_normalized = magnetic_residual / magnetic_uncertainty_nt
        cross_magnitude = cross_gradient.calculate_cross_gradient(recovered)
        objective_components = {
            "phi_gravity_data": float(gravity_misfit(recovered)),
            "phi_magnetics_data": float(magnetic_misfit(recovered)),
            "phi_gravity_regularization": float(gravity_regularizer(recovered)),
            "phi_magnetics_regularization": float(magnetic_regularizer(recovered)),
            "phi_cross_gradient": float(cross_gradient(recovered)),
            "cross_gradient_weight": config.coupling.weight,
        }
        if petrophysical_smallness is not None:
            # The one term the two properties share, reported beside the two they do
            # not, so a reader can see which coupling did the work.
            objective_components["phi_petrophysical"] = float(petrophysical_smallness(recovered))
        phi_data = (
            objective_components["phi_gravity_data"] + objective_components["phi_magnetics_data"]
        )
        phi_model = float(joint_regularizer(recovered))
        run_dir = context.artifact_root / str(spec.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        paths = {
            "density": run_dir / "recovered_density_g_cc.npy",
            "susceptibility": run_dir / "recovered_susceptibility.npy",
            "gravity_prediction": run_dir / "predicted_gravity_mgal.npy",
            "magnetic_prediction": run_dir / "predicted_tmi_nt.npy",
            "gravity_residual": run_dir / "residual_gravity_mgal.npy",
            "magnetic_residual": run_dir / "residual_tmi_nt.npy",
            "gravity_normalized": run_dir / "normalized_gravity_residual.npy",
            "magnetic_normalized": run_dir / "normalized_tmi_residual.npy",
            "cross_gradient": run_dir / "cross_gradient_magnitude_1_m2.npy",
            "components": run_dir / "objective_components.json",
            "log": run_dir / "simpeg.log",
            "gravity_observation_figure": run_dir / "observed_gravity_map.png",
            "magnetic_observation_figure": run_dir / "observed_tmi_map.png",
            "density_slice": run_dir / "recovered_density_slice.png",
            "susceptibility_slice": run_dir / "recovered_susceptibility_slice.png",
        }
        np.save(
            paths["density"], np.asarray(density_from_simpeg(recovered_density_g_cc), dtype=float)
        )
        np.save(paths["susceptibility"], recovered_susceptibility)
        np.save(paths["gravity_prediction"], predicted_gravity_mgal)
        np.save(paths["magnetic_prediction"], predicted_magnetic_nt)
        np.save(paths["gravity_residual"], gravity_residual)
        np.save(paths["magnetic_residual"], magnetic_residual)
        np.save(paths["gravity_normalized"], gravity_normalized)
        np.save(paths["magnetic_normalized"], magnetic_normalized)
        np.save(paths["cross_gradient"], cross_magnitude)
        paths["components"].write_text(
            json.dumps(objective_components, indent=2, sort_keys=True), encoding="utf-8"
        )
        paths["log"].write_text(engine_log.getvalue(), encoding="utf-8")
        render_observation_map(
            np.c_[
                gravity_observations["x_m"],
                gravity_observations["y_m"],
                gravity_observations["z_m"],
            ],
            gravity_observations["gravity_mgal"],
            paths["gravity_observation_figure"],
            title="Observed gravity acceleration",
            unit="mGal",
        )
        render_observation_map(
            np.c_[
                magnetic_observations["x_m"],
                magnetic_observations["y_m"],
                magnetic_observations["z_m"],
            ],
            magnetic_observations["tmi_nt"],
            paths["magnetic_observation_figure"],
            title="Observed total magnetic intensity",
            unit="nT",
        )
        recovered_density_si = np.asarray(density_from_simpeg(recovered_density_g_cc), dtype=float)
        render_active_model_slice(
            mesh,
            active_cells,
            recovered_density_si,
            paths["density_slice"],
            title="Recovered density contrast",
            unit="g/cm^3",
        )
        render_active_model_slice(
            mesh,
            active_cells,
            recovered_susceptibility,
            paths["susceptibility_slice"],
            title="Recovered susceptibility",
            unit="dimensionless",
        )
        artifacts = [
            self._artifact(
                spec,
                context,
                paths["density"],
                "recovered_density",
                QuantityType.DENSITY_CONTRAST,
                "g/cm^3",
            ),
            self._artifact(
                spec,
                context,
                paths["susceptibility"],
                "recovered_susceptibility",
                QuantityType.SUSCEPTIBILITY,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                paths["gravity_prediction"],
                "predicted_gravity",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                paths["magnetic_prediction"],
                "predicted_tmi",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                paths["gravity_residual"],
                "gravity_residual",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                paths["magnetic_residual"],
                "tmi_residual",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                paths["gravity_normalized"],
                "normalized_gravity_residual",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                paths["magnetic_normalized"],
                "normalized_tmi_residual",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                paths["cross_gradient"],
                "cross_gradient_magnitude",
                QuantityType.CROSS_GRADIENT,
                "1/m^2",
            ),
            self._artifact(
                spec,
                context,
                paths["components"],
                "objective_components",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                paths["log"],
                "engine_log",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                paths["gravity_observation_figure"],
                "gravity_observation_map",
                QuantityType.GRAVITY_ACCELERATION,
                "mGal",
            ),
            self._artifact(
                spec,
                context,
                paths["magnetic_observation_figure"],
                "tmi_observation_map",
                QuantityType.MAGNETIC_ANOMALY,
                "nT",
            ),
            self._artifact(
                spec,
                context,
                paths["density_slice"],
                "density_model_slice",
                QuantityType.DENSITY_CONTRAST,
                "g/cm^3",
            ),
            self._artifact(
                spec,
                context,
                paths["susceptibility_slice"],
                "susceptibility_model_slice",
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
                "solver": "joint_gravity_magnetics_cross_gradient",
                "mesh_kind": type(mesh).__name__,
                "gravity_observation_count": int(gravity_observations.size),
                "magnetics_observation_count": int(magnetic_observations.size),
                "mesh_cells": int(mesh.nC),
                "model_cells": active_count,
                "cross_gradient_weight": config.coupling.weight,
                "phi_data": phi_data,
                "chi_squared": chi_squared(
                    phi_data,
                    int(gravity_observations.size) + int(magnetic_observations.size),
                ),
                "phi_model": phi_model,
                "phi_cross_gradient": objective_components["phi_cross_gradient"],
                # Present only when the run had rock classes.
                **(
                    {"phi_petrophysical": objective_components["phi_petrophysical"]}
                    if "phi_petrophysical" in objective_components
                    else {}
                ),
                "gravity_data_unit": "mGal",
                "magnetics_data_unit": "nT",
            },
            artifacts=tuple(artifacts),
        )

    @staticmethod
    def _build_petrophysical_regularization(
        regularization: Any,
        maps: Any,
        mesh: Any,
        active_cells: np.ndarray,
        active_count: int,
        joint_reference: np.ndarray,
        config: GravMagJointInversionSpec,
        wires: Any,
    ) -> Any:
        """One mixture over density and susceptibility together."""
        petrophysical = config.petrophysical
        assert petrophysical is not None  # guarded by the caller
        smoothness = config.gravity.regularization
        differing = [
            field
            for field in _SHARED_SMOOTHNESS_FIELDS
            if getattr(smoothness, field) != getattr(config.magnetics.regularization, field)
        ]
        if differing:
            raise ValueError(
                "a joint petrophysical inversion applies one smoothness to both properties, "
                f"so gravity and magnetics must declare the same {', '.join(differing)}"
            )

        classes = petrophysical.classes
        means = np.empty((len(classes), 2))
        spreads = np.empty((len(classes), 2))
        for index, item in enumerate(classes):
            means[index] = (
                float(
                    density_to_simpeg(
                        canonicalize_quantity(
                            item.density_contrast.value,
                            item.density_contrast.unit,
                            QuantityType.DENSITY_CONTRAST,
                        )
                    )
                ),
                float(
                    canonicalize_quantity(
                        item.susceptibility.value,
                        item.susceptibility.unit,
                        QuantityType.SUSCEPTIBILITY,
                    )
                ),
            )
            spreads[index] = (
                float(
                    density_to_simpeg(
                        canonicalize_quantity(
                            item.density_standard_deviation.value,
                            item.density_standard_deviation.unit,
                            QuantityType.DENSITY_CONTRAST,
                        )
                    )
                ),
                float(
                    canonicalize_quantity(
                        item.susceptibility_standard_deviation.value,
                        item.susceptibility_standard_deviation.unit,
                        QuantityType.SUSCEPTIBILITY,
                    )
                ),
            )
        declared = [item.proportion for item in classes]
        proportions = (
            np.asarray(declared, dtype=float)
            if all(share is not None for share in declared)
            else np.full(len(classes), 1.0 / len(classes))
        )
        mixture = declared_mixture(mesh, active_cells, means, spreads, proportions)
        identity = maps.IdentityMap(nP=active_count)
        return regularization.PGI(
            mesh,
            mixture,
            wiresmap=wires,
            maplist=[identity, identity],
            active_cells=active_cells,
            alpha_pgi=petrophysical.alpha_pgi,
            alpha_x=smoothness.alpha_x,
            alpha_y=smoothness.alpha_y,
            alpha_z=smoothness.alpha_z,
            alpha_xx=smoothness.alpha_xx,
            alpha_yy=smoothness.alpha_yy,
            alpha_zz=smoothness.alpha_zz,
            reference_model=joint_reference,
            reference_model_in_smooth=config.gravity.model.reference_model_in_smooth,
        )

    @staticmethod
    def _build_tutorial_directives(directives: Any, config: GravMagJointInversionSpec) -> list[Any]:
        """Mirror SimPEG's published cross-gradient tutorial directive sequence."""
        if config.beta.estimation is not BetaEstimationKind.BY_EIG:
            raise ValueError(
                "simpeg_cross_gradient_tutorial directives require beta.estimation='by_eig'"
            )
        if config.directives.target_chi_factor is not None:
            raise ValueError(
                "simpeg_cross_gradient_tutorial uses MovingAndMultiTargetStopping, "
                "not target_chi_factor"
            )
        return [
            directives.SimilarityMeasureInversionDirective(),
            directives.UpdateSensitivityWeights(every_iteration=False),
            directives.MovingAndMultiTargetStopping(tol=1e-6),
            directives.PairedBetaEstimate_ByEig(beta0_ratio=config.beta.beta0_ratio),
            directives.PairedBetaSchedule(
                cooling_factor=config.beta.cooling_factor,
                cooling_rate=config.beta.cooling_rate,
            ),
            directives.SimilarityMeasureSaveOutputEveryIteration(on_disk=False),
            directives.UpdatePreconditioner(),
        ]

    @staticmethod
    def _quantity_value(value: QuantitySpec, quantity_type: QuantityType) -> float:
        if isinstance(value.value, list):
            raise ValueError("joint inversion quantities must be scalar")
        return float(canonicalize_quantity(value.value, value.unit, quantity_type))

    @staticmethod
    def _observation_count(path_value: str, loader: Callable[[Path], np.ndarray]) -> int:
        path = Path(path_value)
        if not path.is_file():
            return 0
        try:
            return int(loader(path).size)
        except ValueError:
            return 0

    @staticmethod
    def _validate_observations(
        path_value: str,
        loader: Callable[[Path], np.ndarray],
        field: str,
        remediation: str,
        issues: list[ValidationIssue],
    ) -> None:
        path = Path(path_value)
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    field=field,
                    message=f"observation CSV does not exist: {path_value}",
                    remediation="generate or fetch the dataset before validating the run",
                )
            )
            return
        try:
            loader(path)
        except ValueError as error:
            issues.append(ValidationIssue(field=field, message=str(error), remediation=remediation))

    @staticmethod
    def _validate_topography(
        config: GravMagJointInversionSpec, issues: list[ValidationIssue], field: str
    ) -> None:
        if config.topography_path is None:
            return
        path = Path(config.topography_path)
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    field=field,
                    message=f"topography CSV does not exist: {config.topography_path}",
                    remediation="prepare or import the topography before validating the run",
                )
            )
            return
        try:
            SimPEGGravity3DPlugin._load_topography(path)
        except ValueError as error:
            issues.append(
                ValidationIssue(
                    field=field,
                    message=str(error),
                    remediation="provide finite x_m,y_m,z_m topography columns",
                )
            )

    @staticmethod
    def _validate_array_inputs(
        config: GravMagJointInversionSpec, issues: list[ValidationIssue], field: str
    ) -> None:
        inputs: list[tuple[str, ArrayInputSpec]] = []
        for name, property_config in (
            ("gravity", config.gravity),
            ("magnetics", config.magnetics),
        ):
            if property_config.model.initial_model is not None:
                inputs.append(
                    (
                        f"{field}.{name}.model.initial_model",
                        property_config.model.initial_model,
                    )
                )
            if property_config.model.reference_model is not None:
                inputs.append(
                    (
                        f"{field}.{name}.model.reference_model",
                        property_config.model.reference_model,
                    )
                )
            inputs.extend(
                (
                    f"{field}.{name}.regularization.cell_weights.{weight_name}",
                    item,
                )
                for weight_name, item in property_config.regularization.cell_weights.items()
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
