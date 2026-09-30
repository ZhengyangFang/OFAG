"""Invert first-arrival traveltimes for a P-wave velocity section."""

from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, model_validator

from ofag.core.constants import QuantityType
from ofag.core.conventions import ConventionCheck
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    DataChannelSpec,
    QuantitySpec,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    StrictModel,
    ValidationIssue,
    ValidationReport,
)
from ofag.engines.pygimli.geometry import build_traveltime_mesh, mesh_geometry
from ofag.plugins.protocol import PluginContext

#: Below this a velocity bound would be read by pyGIMLi as a slowness.
_SLOWNESS_SNIFF_M_S = 1.0


class TravelTimeArraySpec(StrictModel):
    """Where the shots and geophones are, and which pairs were recorded."""

    #: `(sensor, 3)` of x, y, z in project SI metres, as a `.npy`.
    sensors_path: str = Field(min_length=1)
    #: `(pick, 2)` of 0-based indices into the sensor table, as shot then receiver.
    shot_receiver_path: str = Field(min_length=1)


class TravelTimeMeshSpec(StrictModel):
    """The parameter mesh, built by pyGIMLi from the sensor geometry."""

    #: Two dimensions only.
    dimension: Literal[2] = 2
    node_spacing_fraction: float = Field(default=0.25, gt=0, le=1)
    depth: QuantitySpec | None = None
    quality: float = Field(default=33.0, gt=0)
    max_cell_area: QuantitySpec | None = None
    #: Extra nodes per cell edge for the shortest-path solver.
    secondary_nodes: int = Field(default=3, ge=1, le=10)


class TravelTimeRegularizationSpec(StrictModel):
    lam: float = Field(default=30.0, gt=0)
    #: Relative weight of vertical smoothing.
    vertical_weight: float = Field(default=0.5, gt=0)
    lower_velocity: QuantitySpec | None = None
    upper_velocity: QuantitySpec | None = None


class TravelTimeStartingModelSpec(StrictModel):
    """A gradient from `top_velocity` to `bottom_velocity`."""

    use_gradient: bool = True
    top_velocity: QuantitySpec | None = None
    bottom_velocity: QuantitySpec | None = None


class TravelTimeOptimizerSpec(StrictModel):
    max_iterations: int = Field(default=10, ge=1, le=200)
    target_chi_squared: float = Field(default=1.0, gt=0)


class TravelTimeDataQualitySpec(StrictModel):
    """Filters, each of which reports how many picks it removed."""

    #: A pick whose shot and receiver are the same sensor.
    drop_zero_offset: bool = False
    #: Drop picks at or below a floor.
    minimum_traveltime: QuantitySpec | None = None
    #: Drop picks whose offset over traveltime falls below a plausible velocity.
    minimum_apparent_velocity: QuantitySpec | None = None

    @property
    def is_active(self) -> bool:
        return (
            self.drop_zero_offset
            or self.minimum_traveltime is not None
            or self.minimum_apparent_velocity is not None
        )


class TravelTimeInversionSpec(StrictModel):
    array: TravelTimeArraySpec
    mesh: TravelTimeMeshSpec = Field(default_factory=TravelTimeMeshSpec)
    regularization: TravelTimeRegularizationSpec = Field(
        default_factory=TravelTimeRegularizationSpec
    )
    starting_model: TravelTimeStartingModelSpec = Field(default_factory=TravelTimeStartingModelSpec)
    optimizer: TravelTimeOptimizerSpec = Field(default_factory=TravelTimeOptimizerSpec)
    quality: TravelTimeDataQualitySpec = Field(default_factory=TravelTimeDataQualitySpec)
    traveltime_channel: str = "traveltime"

    @model_validator(mode="after")
    def velocity_bounds_are_velocities(self) -> "TravelTimeInversionSpec":
        lower = self.regularization.lower_velocity
        upper = self.regularization.upper_velocity
        if lower is not None and _scalar(lower.value) <= _SLOWNESS_SNIFF_M_S:
            raise ValueError(
                f"lower_velocity must exceed {_SLOWNESS_SNIFF_M_S} m/s: pyGIMLi decides whether "
                "bounds are velocities or slownesses by whether the lower one exceeds 1, so a "
                "smaller value would be silently inverted as a slowness"
            )
        if lower is not None and upper is not None and _scalar(upper.value) <= _scalar(lower.value):
            raise ValueError("upper_velocity must exceed lower_velocity")
        return self


def _scalar(value: Any) -> float:
    if isinstance(value, list | tuple):
        raise ValueError("a bound must be one number, not a sequence")
    return float(value)


class PyGIMLiTravelTimePlugin:
    """Invert first-arrival traveltimes for a P-wave velocity section."""

    plugin_id = "pygimli.seismic.traveltime"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return TravelTimeInversionSpec

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.TRAVELTIME, QuantityType.P_WAVE_VELOCITY),
            supported_meshes=("PyGIMLiUnstructured2D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "2D refraction tomography from a sensor table and shot/receiver index pairs.",
                "The traveltime error is ABSOLUTE, in seconds: pyGIMLi's traveltime container "
                "reads `err` that way, unlike its resistivity container.",
                "The mesh is generated by pyGIMLi and declared in the physics payload, so "
                "RunSpec.mesh must be unset.",
                "Crosshole geometry is not validated; the starting model assumes a surface "
                "spread with velocity increasing downward.",
                "Install with `uv sync --extra pygimli`; pyGIMLi is an optional backend.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        try:
            config = TravelTimeInversionSpec.model_validate(spec.physics)
        except Exception as error:  # noqa: BLE001 - reported, not raised
            return ValidationReport(
                valid=False,
                issues=(
                    ValidationIssue(
                        field="physics",
                        message=str(error),
                        remediation="see TravelTimeInversionSpec",
                    ),
                ),
            )

        if spec.mesh is not None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="pyGIMLi generates its own unstructured mesh",
                    remediation="leave RunSpec.mesh unset and use physics.mesh",
                )
            )

        channel = self._require_channel(spec, config.traveltime_channel, issues)
        try:
            sensors, pairs = self._load_geometry(config)
        except (OSError, ValueError) as error:
            issues.append(
                ValidationIssue(
                    field="physics.array", message=str(error), remediation="check the .npy files"
                )
            )
            return ValidationReport(valid=not issues, issues=tuple(issues))

        highest = int(pairs.max()) if pairs.size else -1
        if highest >= len(sensors):
            issues.append(
                ValidationIssue(
                    field="physics.array.shot_receiver_path",
                    message=f"index {highest} is used but only {len(sensors)} sensors are declared",
                    remediation="indices are 0-based; field formats number traces from 1",
                )
            )
        if channel is not None:
            try:
                observations = self._load_observations(Path(channel.observations_path))
            except (OSError, ValueError) as error:
                issues.append(
                    ValidationIssue(
                        field="datasets", message=str(error), remediation="check the observations"
                    )
                )
            else:
                if observations.size != len(pairs):
                    issues.append(
                        ValidationIssue(
                            field="datasets",
                            message=f"{observations.size} traveltimes against {len(pairs)} pairs",
                            remediation="one traveltime per shot-receiver pair",
                        )
                    )
                elif (observations <= 0).any():
                    issues.append(
                        ValidationIssue(
                            field="datasets",
                            message=(
                                f"{int((observations <= 0).sum())} traveltimes are not positive"
                            ),
                            remediation=(
                                "a first arrival is a positive time; drop zero-offset picks "
                                "with quality.drop_zero_offset"
                            ),
                        )
                    )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _require_channel(
        spec: RunSpec, name: str, issues: list[ValidationIssue]
    ) -> DataChannelSpec | None:
        for channel in spec.datasets:
            if channel.channel_id == name:
                return channel
        issues.append(
            ValidationIssue(
                field="datasets",
                message=f"no channel {name!r}",
                remediation=f"provide the traveltimes as channel {name!r}",
            )
        )
        return None

    @staticmethod
    def _load_geometry(config: TravelTimeInversionSpec) -> tuple[np.ndarray, np.ndarray]:
        sensors = np.asarray(
            np.load(Path(config.array.sensors_path), allow_pickle=False), dtype=float
        )
        if sensors.ndim != 2 or sensors.shape[1] != 3 or not np.isfinite(sensors).all():
            raise ValueError("sensors must be a finite (n, 3) array of SI metres")
        pairs = np.asarray(
            np.load(Path(config.array.shot_receiver_path), allow_pickle=False), dtype=np.int64
        )
        if pairs.ndim != 2 or pairs.shape[1] != 2:
            raise ValueError("shot_receiver must be an (m, 2) array of sensor indices")
        if pairs.size and pairs.min() < 0:
            raise ValueError("sensor indices are 0-based and cannot be negative")
        return sensors, pairs

    @staticmethod
    def _load_observations(path: Path) -> np.ndarray:
        values = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=1)
        if not np.isfinite(values).all():
            raise ValueError("traveltimes must all be finite")
        return np.asarray(values, dtype=float)

    def conventions(self) -> tuple[ConventionCheck, ...]:
        from ofag.engines.pygimli.traveltime_conventions import checks

        return checks()

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        try:
            config = TravelTimeInversionSpec.model_validate(spec.physics)
            sensors, pairs = self._load_geometry(config)
        except Exception:  # noqa: BLE001 - an estimate is not a validation
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        # Cost scales with the Jacobian, which is picks by parameter cells, and with the
        # secondary nodes the shortest-path solver refines to.
        cells = max(1, len(sensors) * 60)
        jacobian_mb = max(1, len(pairs) * cells * 8 // (1024 * 1024))
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(256, jacobian_mb * 4),
            estimated_seconds=max(1, len(pairs) * cells * config.mesh.secondary_nodes // 200_000),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        import pygimli as pg  # type: ignore[import-untyped]
        from pygimli.physics import TravelTimeManager  # type: ignore[import-untyped]

        config = TravelTimeInversionSpec.model_validate(spec.physics)
        channel = next(c for c in spec.datasets if c.channel_id == config.traveltime_channel)
        sensors, pairs = self._load_geometry(config)
        observations = self._load_observations(Path(channel.observations_path))
        uncertainty = self._absolute_uncertainty(channel, observations)

        keep, removed = self._retained_picks(config, sensors, pairs, observations)
        pairs, observations, uncertainty = pairs[keep], observations[keep], uncertainty[keep]
        if not observations.size:
            raise ValueError("the quality filters removed every pick")

        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                message=f"{len(pairs)} picks on {len(sensors)} sensors, {removed} removed",
            )
        )

        mesh = build_traveltime_mesh(
            sensors,
            node_spacing_fraction=config.mesh.node_spacing_fraction,
            depth_m=self._optional_length(config.mesh.depth),
            quality=config.mesh.quality,
            max_cell_area_m2=self._optional_length(config.mesh.max_cell_area),
        )
        data = self._build_data_container(pg, sensors, pairs, observations, uncertainty)

        manager = TravelTimeManager()
        options: dict[str, Any] = {
            "mesh": mesh,
            "lam": config.regularization.lam,
            "zWeight": config.regularization.vertical_weight,
            "maxIter": config.optimizer.max_iterations,
            "secNodes": config.mesh.secondary_nodes,
            "useGradient": config.starting_model.use_gradient,
            "verbose": False,
        }
        if config.starting_model.top_velocity is not None:
            options["vTop"] = _scalar(config.starting_model.top_velocity.value)
        if config.starting_model.bottom_velocity is not None:
            options["vBottom"] = _scalar(config.starting_model.bottom_velocity.value)
        limits = self._velocity_limits(config)
        if limits is not None:
            options["limits"] = limits

        velocity = np.asarray(manager.invert(data, **options), dtype=float)
        parameter_domain = manager.paraDomain
        geometry = mesh_geometry(parameter_domain)
        predicted = np.asarray(manager.inv.response, dtype=float)
        chi_squared = float(manager.inv.chi2())
        history = [float(v) for v in np.asarray(manager.inv.chi2History, dtype=float)]
        ray_coverage = np.asarray(manager.rayCoverage(), dtype=float)
        touched = np.asarray(manager.standardizedCoverage(), dtype=float)

        directory = context.run_dir(spec.run_id)
        second = QuantityType.TRAVELTIME
        artifacts = [
            self._save_array(
                context,
                directory,
                spec,
                "recovered_model",
                velocity,
                QuantityType.P_WAVE_VELOCITY,
                "m/s",
            ),
            self._save_array(
                context, directory, spec, "observed_traveltime", observations, second, "s"
            ),
            self._save_array(
                context, directory, spec, "predicted_traveltime", predicted, second, "s"
            ),
            self._save_array(
                context,
                directory,
                spec,
                "residual_traveltime",
                predicted - observations,
                second,
                "s",
            ),
            self._save_array(
                context, directory, spec, "ray_coverage", ray_coverage, QuantityType.LENGTH, "m"
            ),
            self._save_array(
                context,
                directory,
                spec,
                "cells_touched_by_a_ray",
                touched,
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._save_mesh_geometry(context, spec, directory, geometry),
        ]

        summary: dict[str, Any] = {
            "engine": "pygimli",
            "engine_version": str(pg.__version__),
            "dimension": config.mesh.dimension,
            "sensors": len(sensors),
            "picks": len(pairs),
            "picks_removed": removed,
            "quality_filtered": config.quality.is_active,
            "model_cells": int(velocity.size),
            "chi_squared": chi_squared,
            "chi_squared_initial": history[0] if history else chi_squared,
            "iterations": int(manager.inv.iter),
            # The honest answer to what a sparse survey resolved.
            "cells_touched_by_a_ray": int(touched.sum()),
            "cells_touched_share": float(touched.mean()) if touched.size else 0.0,
            "data_unit": "second",
            "model_unit": "meter / second",
            "secondary_nodes": config.mesh.secondary_nodes,
            "velocity_min": float(velocity.min()) if velocity.size else 0.0,
            "velocity_max": float(velocity.max()) if velocity.size else 0.0,
        }
        return RunResult(run_id=spec.run_id, summary=summary, artifacts=tuple(artifacts))

    @staticmethod
    def _absolute_uncertainty(channel: DataChannelSpec, observations: np.ndarray) -> np.ndarray:
        """The per-pick error, in seconds, absolute."""
        value = channel.data_uncertainty.value
        error = np.broadcast_to(np.asarray(value, dtype=float), observations.shape).copy()
        if not np.isfinite(error).all() or (error <= 0).any():
            raise ValueError("every traveltime error must be finite and positive")
        return error

    @staticmethod
    def _retained_picks(
        config: TravelTimeInversionSpec,
        sensors: np.ndarray,
        pairs: np.ndarray,
        observations: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        keep = np.ones(observations.shape, dtype=bool)
        offset = np.linalg.norm(sensors[pairs[:, 0]] - sensors[pairs[:, 1]], axis=1)
        if config.quality.drop_zero_offset:
            keep &= offset > 0
        if config.quality.minimum_traveltime is not None:
            keep &= observations > _scalar(config.quality.minimum_traveltime.value)
        if config.quality.minimum_apparent_velocity is not None:
            floor = _scalar(config.quality.minimum_apparent_velocity.value)
            with np.errstate(divide="ignore", invalid="ignore"):
                apparent = offset / observations
            keep &= ~(np.isfinite(apparent) & (offset > 0) & (apparent < floor))
        return keep, int((~keep).sum())

    @staticmethod
    def _build_data_container(
        pg: Any,
        sensors: np.ndarray,
        pairs: np.ndarray,
        observations: np.ndarray,
        uncertainty: np.ndarray,
    ) -> Any:
        """A traveltime container with the sensor arity the mesh expects."""
        data = pg.DataContainer()
        for x, _, z in sensors:
            data.createSensor([float(x), float(z)])
        data.registerSensorIndex("s")
        data.registerSensorIndex("g")
        data.resize(len(pairs))
        data["s"] = pairs[:, 0].tolist()
        data["g"] = pairs[:, 1].tolist()
        data["t"] = observations.tolist()
        data["err"] = uncertainty.tolist()
        data["valid"] = np.ones(len(pairs), dtype=int).tolist()
        return data

    @staticmethod
    def _velocity_limits(config: TravelTimeInversionSpec) -> list[float] | None:
        lower = config.regularization.lower_velocity
        upper = config.regularization.upper_velocity
        if lower is None or upper is None:
            return None
        return [_scalar(lower.value), _scalar(upper.value)]

    @staticmethod
    def _optional_length(quantity: QuantitySpec | None) -> float | None:
        return None if quantity is None else _scalar(quantity.value)

    @staticmethod
    def _save_array(
        context: PluginContext,
        directory: Path,
        spec: RunSpec,
        artifact_type: str,
        values: np.ndarray,
        quantity: QuantityType,
        unit: str,
    ) -> ArtifactManifest:
        path = directory / f"{artifact_type}.npy"
        np.save(path, values)
        return ArtifactManifest(
            artifact_type=artifact_type,
            physical_quantity=quantity,
            units=unit,
            source_run_id=spec.run_id,
            relative_path=path.relative_to(context.artifact_root).as_posix(),
        )

    @staticmethod
    def _save_mesh_geometry(
        context: PluginContext, spec: RunSpec, directory: Path, geometry: dict[str, np.ndarray]
    ) -> ArtifactManifest:
        path = directory / "mesh_geometry.npz"
        np.savez(
            path,
            nodes_m=geometry["nodes_m"],
            cell_nodes=geometry["cell_nodes"],
            cell_centers_m=geometry["cell_centers_m"],
            cell_sizes=geometry["cell_sizes"],
        )
        return ArtifactManifest(
            artifact_type="mesh_geometry",
            physical_quantity=QuantityType.LENGTH,
            units="m",
            source_run_id=spec.run_id,
            # Anchored to the artifact root, like every other artifact in the project; a
            # bare filename resolves against the root, not the run.
            relative_path=path.relative_to(context.artifact_root).as_posix(),
        )
