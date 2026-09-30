"""pyGIMLi-backed 2.5D and 3D resistivity inversion, with optional IP."""

from importlib.util import find_spec
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
from ofag.core.units import canonicalize_quantity
from ofag.engines.pygimli.geometry import (
    FLAT_TOLERANCE_M,
    build_parameter_mesh,
    geometric_factors,
    mesh_geometry,
)
from ofag.engines.pygimli.units import resistivity_from_pygimli
from ofag.plugins.protocol import PluginContext

#: A quadrupole entry of -1 marks a remote electrode, which pole-pole and pole-dipole
#: arrays place effectively at infinity. pyGIMLi uses the same sentinel, so it survives
#: the boundary unchanged.
REMOTE_ELECTRODE = -1


class ERTElectrodeArraySpec(StrictModel):
    """The electrode table and the quadrupoles measured against it."""

    electrodes_path: str = Field(min_length=1)
    quadrupoles_path: str = Field(min_length=1)


class ERTMeshSpec(StrictModel):
    """Declarative controls for the mesh pyGIMLi generates."""

    dimension: Literal[2, 3] = 2
    #: Node spacing near the electrodes, as a fraction of electrode spacing.
    node_spacing_fraction: float = Field(default=0.25, gt=0, le=1)
    #: Depth of the parameter domain.
    depth: QuantitySpec | None = None
    #: Padding around the electrode spread, as a fraction of its length.
    boundary_fraction: float = Field(default=2.0, gt=0)
    quality: float = Field(default=33.0, gt=0)
    max_cell_area: QuantitySpec | None = None

    @model_validator(mode="after")
    def lengths_are_lengths(self) -> "ERTMeshSpec":
        if self.depth is not None and self.depth.quantity_type is not QuantityType.LENGTH:
            raise ValueError("mesh.depth must be a length")
        if self.max_cell_area is not None and self.max_cell_area.quantity_type is not (
            QuantityType.DIMENSIONLESS
        ):
            raise ValueError(
                "mesh.max_cell_area is an area in square metres and is declared dimensionless; "
                "OFAG has no area quantity type yet"
            )
        return self


class ERTRegularizationSpec(StrictModel):
    lam: float = Field(default=20.0, gt=0)
    #: Relative weight of vertical smoothing.  Below 1 favours layered models.
    vertical_weight: float = Field(default=1.0, gt=0)
    lower_bound: QuantitySpec | None = None
    upper_bound: QuantitySpec | None = None
    #: L1 rather than L2 on the model constraint, which lets the model hold a sharp
    #: boundary instead of smearing it.
    blocky_model: bool = False
    #: L1 rather than L2 on the data misfit, which stops a few bad readings from setting
    #: the model.
    robust_data: bool = False
    #: Multiply lambda by this after every iteration, so the inversion starts smooth and
    #: relaxes only as far as the data ask; with `stop_at_chi1` it stops at the
    #: smoothest model that fits. 1 keeps lambda fixed.
    lambda_factor: float = Field(default=1.0, gt=0, le=1)


class ERTOptimizerSpec(StrictModel):
    max_iterations: int = Field(default=10, ge=1, le=200)
    #: Stop once the misfit reaches this multiple of the estimated error.
    target_chi_squared: float = Field(default=1.0, gt=0)


class ERTDataQualitySpec(StrictModel):
    """Which measurements to leave out, and why."""

    #: Drop measurements whose *apparent resistivity* is zero or negative.
    drop_non_positive: bool = False
    #: Drop measurements whose apparent resistivity falls outside this range.
    minimum_apparent_resistivity: QuantitySpec | None = None
    maximum_apparent_resistivity: QuantitySpec | None = None
    #: Drop measurements whose geometric factor exceeds this magnitude.
    maximum_geometric_factor: float | None = Field(default=None, gt=0)
    #: Drop measurements whose stated relative error exceeds this fraction.
    maximum_relative_error: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def bounds_are_resistivities(self) -> "ERTDataQualitySpec":
        for value, name in (
            (self.minimum_apparent_resistivity, "minimum_apparent_resistivity"),
            (self.maximum_apparent_resistivity, "maximum_apparent_resistivity"),
        ):
            if value is not None and value.quantity_type is not QuantityType.APPARENT_RESISTIVITY:
                raise ValueError(f"{name} must be an apparent resistivity")
        low, high = self.minimum_apparent_resistivity, self.maximum_apparent_resistivity
        if low is not None and high is not None and _scalar(low.value) >= _scalar(high.value):
            raise ValueError("minimum_apparent_resistivity must be below the maximum")
        return self

    @property
    def is_active(self) -> bool:
        return any(
            (
                self.drop_non_positive,
                self.minimum_apparent_resistivity is not None,
                self.maximum_apparent_resistivity is not None,
                self.maximum_geometric_factor is not None,
                self.maximum_relative_error is not None,
            )
        )


class ERTInversionSpec(StrictModel):
    """Everything the resistivity plugin needs, owned by the plugin."""

    array: ERTElectrodeArraySpec
    mesh: ERTMeshSpec = Field(default_factory=ERTMeshSpec)
    regularization: ERTRegularizationSpec = Field(default_factory=ERTRegularizationSpec)
    optimizer: ERTOptimizerSpec = Field(default_factory=ERTOptimizerSpec)
    #: Channel ids resolved against `RunSpec.datasets`.
    resistance_channel: str = "dc"
    chargeability_channel: str | None = None
    starting_resistivity: QuantitySpec | None = None
    quality: ERTDataQualitySpec = Field(default_factory=ERTDataQualitySpec)
    #: A surface to read electrode elevations from, for a survey whose field file
    #: carried none.
    topography_path: str | None = None

    @model_validator(mode="after")
    def channels_differ(self) -> "ERTInversionSpec":
        if self.chargeability_channel == self.resistance_channel:
            raise ValueError("the IP channel must be a different channel from the DC channel")
        if (
            self.starting_resistivity is not None
            and self.starting_resistivity.quantity_type is not QuantityType.RESISTIVITY
        ):
            raise ValueError("starting_resistivity must be a resistivity")
        return self


class PyGIMLiERTPlugin:
    """Invert transfer resistance for a resistivity section or volume."""

    plugin_id = "pygimli.ert.dcip"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return ERTInversionSpec

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(
                QuantityType.TRANSFER_RESISTANCE,
                QuantityType.RESISTIVITY,
                QuantityType.CHARGEABILITY,
            ),
            supported_meshes=("PyGIMLiUnstructured2D", "PyGIMLiUnstructured3D"),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "2.5D and 3D DC resistivity from an electrode table and A/B/M/N quadrupoles.",
                "The mesh is generated by pyGIMLi and declared in the physics payload, so "
                "RunSpec.mesh must be unset.",
                "Induced polarisation is accepted as a second channel but is not yet inverted.",
                "Install with `uv sync --extra pygimli`; pyGIMLi is an optional backend.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if find_spec("pygimli") is None:
            issues.append(
                ValidationIssue(
                    field="environment",
                    message="pyGIMLi is not installed",
                    remediation="run `uv sync --extra pygimli` before submitting this plugin",
                )
            )
        if spec.engine != "pygimli":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message=f"{self.plugin_id} requires engine='pygimli'",
                    remediation="set engine: pygimli in the RunSpec",
                )
            )
        config = spec.physics_as(ERTInversionSpec)
        if config is None:
            issues.append(
                ValidationIssue(
                    field="physics",
                    message="an ERTInversionSpec physics payload is required",
                    remediation="provide array, mesh, regularization and channel references",
                )
            )
            return ValidationReport(valid=False, issues=tuple(issues))
        if spec.mesh is not None:
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message=(
                        "pyGIMLi builds its own unstructured mesh, so RunSpec.mesh must be unset"
                    ),
                    remediation="describe the mesh in physics.mesh and remove RunSpec.mesh",
                )
            )
        resistance = self._require_channel(
            spec, config.resistance_channel, QuantityType.TRANSFER_RESISTANCE, "resistance", issues
        )
        if config.chargeability_channel is not None:
            self._require_channel(
                spec,
                config.chargeability_channel,
                QuantityType.CHARGEABILITY,
                "chargeability",
                issues,
            )
        self._validate_geometry(config, resistance, issues)
        return ValidationReport(valid=not issues, issues=tuple(issues))

    @staticmethod
    def _require_channel(
        spec: RunSpec,
        channel_id: str,
        expected: QuantityType,
        role: str,
        issues: list[ValidationIssue],
    ) -> DataChannelSpec | None:
        channel = spec.channel(channel_id)
        if channel is None:
            available = ", ".join(item.channel_id for item in spec.datasets) or "none"
            issues.append(
                ValidationIssue(
                    field=f"physics.{role}_channel",
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
                    remediation=(
                        "apparent resistivity is derived from a geometric factor, so the "
                        "observation itself must be transfer resistance in ohm"
                        if expected is QuantityType.TRANSFER_RESISTANCE
                        else f"point {role}_channel at the {expected.value} observations"
                    ),
                )
            )
            return None
        return channel

    def _validate_geometry(
        self,
        config: ERTInversionSpec,
        resistance: DataChannelSpec | None,
        issues: list[ValidationIssue],
    ) -> None:
        try:
            electrodes, quadrupoles = self._load_geometry(config)
        except (OSError, ValueError) as error:
            issues.append(
                ValidationIssue(
                    field="physics.array",
                    message=str(error),
                    remediation=(
                        "provide an (n, 3) electrode .npy in SI metres and an (m, 4) integer "
                        "quadrupole .npy of 0-based indices"
                    ),
                )
            )
            return
        highest = int(quadrupoles.max()) if quadrupoles.size else -1
        if highest >= len(electrodes):
            issues.append(
                ValidationIssue(
                    field="physics.array.quadrupoles_path",
                    message=(
                        f"quadrupole references electrode {highest} but only "
                        f"{len(electrodes)} electrodes are declared"
                    ),
                    remediation="indices are 0-based; field formats number electrodes from 1",
                )
            )
        if resistance is not None:
            try:
                observations = self._load_observations(Path(resistance.observations_path))
            except (OSError, ValueError) as error:
                issues.append(
                    ValidationIssue(
                        field=f"datasets.{resistance.channel_id}.observations_path",
                        message=str(error),
                        remediation="provide a CSV with a resistance_ohm column",
                    )
                )
                return
            if observations.size != len(quadrupoles):
                issues.append(
                    ValidationIssue(
                        field=f"datasets.{resistance.channel_id}.observations_path",
                        message=(
                            f"{observations.size} resistance values do not match "
                            f"{len(quadrupoles)} quadrupoles"
                        ),
                        remediation="one measurement per quadrupole, in the same order",
                    )
                )

    @staticmethod
    def _load_geometry(config: ERTInversionSpec) -> tuple[np.ndarray, np.ndarray]:
        electrodes = np.asarray(
            np.load(Path(config.array.electrodes_path), allow_pickle=False), dtype=float
        )
        if electrodes.ndim != 2 or electrodes.shape[1] != 3 or not np.isfinite(electrodes).all():
            raise ValueError("electrodes must be a finite (n, 3) array of SI metres")
        raw = np.load(Path(config.array.quadrupoles_path), allow_pickle=False)
        quadrupoles = np.asarray(raw, dtype=np.int64)
        if quadrupoles.ndim != 2 or quadrupoles.shape[1] != 4:
            raise ValueError("quadrupoles must be an (m, 4) integer array of A, B, M, N indices")
        if quadrupoles.size and int(quadrupoles.min()) < REMOTE_ELECTRODE:
            raise ValueError(f"quadrupole indices must be 0-based, or {REMOTE_ELECTRODE} if remote")
        return electrodes, quadrupoles

    @staticmethod
    def _load_observations(path: Path) -> np.ndarray:
        table = np.genfromtxt(path, delimiter=",", names=True)
        if table.dtype.names is None or "resistance_ohm" not in table.dtype.names:
            raise ValueError("observation CSV must contain a resistance_ohm column")
        values = np.atleast_1d(np.asarray(table["resistance_ohm"], dtype=float))
        if not values.size or not np.isfinite(values).all():
            raise ValueError("resistance_ohm must contain finite values")
        return values

    def conventions(self) -> tuple[ConventionCheck, ...]:
        """The halfspace, and the one electrode-order permutation that is observable."""
        from ofag.engines.pygimli import conventions

        return conventions.checks()

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        config = spec.physics_as(ERTInversionSpec)
        if config is None:
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        try:
            electrodes, quadrupoles = self._load_geometry(config)
        except (OSError, ValueError):
            return ResourceEstimate(cpu_cores=1, memory_mb=256, estimated_seconds=1)
        # Cost scales with the Jacobian, which is data by parameter cells.
        cells = max(1, len(electrodes) * 40 * (1 if config.mesh.dimension == 2 else 20))
        jacobian_mb = max(1, len(quadrupoles) * cells * 8 // (1024 * 1024))
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(256, jacobian_mb * 4),
            estimated_seconds=max(1, len(quadrupoles) * cells // 200_000),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        config = spec.physics_as(ERTInversionSpec)
        assert config is not None
        resistance = spec.channel(config.resistance_channel)
        assert resistance is not None

        import pygimli as pg  # type: ignore[import-untyped]
        from pygimli.physics import ert  # type: ignore[import-untyped]

        electrodes, quadrupoles = self._load_geometry(config)
        observations = self._load_observations(Path(resistance.observations_path))
        uncertainty = self._relative_uncertainty(resistance, observations)
        electrodes, elevation_shift = self._apply_topography(electrodes, config.topography_path)
        electrode_relief = float(np.ptp(electrodes[:, 2])) if len(electrodes) else 0.0

        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=0,
                stage="setup",
                message=f"{len(quadrupoles)} quadrupoles on {len(electrodes)} electrodes",
            )
        )

        # pyGIMLi derives apparent resistivity as r * k only when *every* resistance is
        # non-zero, and refuses the whole container otherwise with "Datacontainer have
        # neither ... impedances 'r'", which reads as though the field were absent.
        zeros = int((observations == 0.0).sum())
        if zeros and not config.quality.drop_non_positive:
            raise ValueError(
                f"{zeros} measurements have a transfer resistance of exactly zero, and the "
                "solver cannot derive apparent resistivity while any of them remain; set "
                "quality.drop_non_positive to leave them out"
            )

        data = self._build_data_container(
            ert, electrodes, quadrupoles, observations, uncertainty, config.mesh.dimension
        )
        retained = self._retained_measurements(data, observations, uncertainty, config.quality)
        removed = int(len(observations) - retained.size)
        if removed:
            if not retained.size:
                raise ValueError(
                    "the data-quality thresholds removed every measurement; "
                    "loosen them or inspect the survey"
                )
            observations = observations[retained]
            uncertainty = uncertainty[retained]
            quadrupoles = quadrupoles[retained]
            # Rebuilt from the survivors rather than edited in place.
            data = self._build_data_container(
                ert, electrodes, quadrupoles, observations, uncertainty, config.mesh.dimension
            )
            context.emit(
                RunEvent(
                    run_id=spec.run_id,
                    event_type="warning",
                    stage="setup",
                    message=(
                        f"{removed} of {removed + retained.size} measurements removed by the "
                        "data-quality thresholds"
                    ),
                )
            )
        mesh = build_parameter_mesh(
            electrodes,
            dimension=config.mesh.dimension,
            node_spacing_fraction=config.mesh.node_spacing_fraction,
            depth_m=self._optional_length(config.mesh.depth),
            boundary_fraction=config.mesh.boundary_fraction,
            quality=config.mesh.quality,
            max_cell_area_m2=(
                None
                if config.mesh.max_cell_area is None
                else float(_scalar(config.mesh.max_cell_area.value))
            ),
        )

        manager = ert.ERTManager(sr=False)
        invert_options: dict[str, Any] = {
            "lam": config.regularization.lam,
            "zWeight": config.regularization.vertical_weight,
            "maxIter": config.optimizer.max_iterations,
            "blockyModel": config.regularization.blocky_model,
            "robustData": config.regularization.robust_data,
            "lambdaFactor": config.regularization.lambda_factor,
            "stopAtChi1": config.regularization.lambda_factor < 1.0,
            "verbose": False,
        }
        limits = self._resistivity_limits(config)
        if limits is not None:
            invert_options["limits"] = limits
        if config.starting_resistivity is not None:
            invert_options["startModel"] = float(_scalar(config.starting_resistivity.value))
        model = np.asarray(manager.invert(data, mesh=mesh, **invert_options), dtype=float)

        parameter_domain = manager.paraDomain
        geometry = mesh_geometry(parameter_domain)
        resistivity_ohm_m = np.asarray(resistivity_from_pygimli(model), dtype=float)

        # pyGIMLi inverts apparent resistivity, so its response is in ohm.m.
        geometric_factor = np.asarray(data["k"], dtype=float)
        predicted_rhoa = np.asarray(manager.inv.response, dtype=float)
        predicted_ohm = predicted_rhoa / geometric_factor
        residual_ohm = observations - predicted_ohm

        chi_squared = float(manager.inv.chi2())
        # The whole convergence history, not only where it stopped: reading a
        # resistivity result means knowing whether the misfit was still falling.
        history = [float(value) for value in np.asarray(manager.inv.chi2History, dtype=float)]
        for iteration, value in enumerate(history, start=1):
            context.emit(
                RunEvent(
                    run_id=spec.run_id,
                    event_type="iteration",
                    iteration=iteration,
                    stage="dc",
                    phi_data=value,
                    misfits={"chi_squared": value},
                    message="iteration completed",
                )
            )

        # Coverage says where the data constrain the model.
        coverage = np.asarray(manager.coverage(), dtype=float)

        run_dir = context.run_dir(spec.run_id)
        artifacts = [
            self._save_array(
                context,
                spec,
                run_dir,
                "recovered_model",
                resistivity_ohm_m,
                QuantityType.RESISTIVITY,
                "ohm*m",
            ),
            self._save_array(
                context,
                spec,
                run_dir,
                "predicted_data",
                predicted_ohm,
                QuantityType.TRANSFER_RESISTANCE,
                "ohm",
            ),
            self._save_array(
                context,
                spec,
                run_dir,
                "residual_data",
                residual_ohm,
                QuantityType.TRANSFER_RESISTANCE,
                "ohm",
            ),
            # Retained because it is what the solver actually fitted, and because
            # reading a pseudosection is how ERT data is judged.
            self._save_array(
                context,
                spec,
                run_dir,
                "predicted_apparent_resistivity",
                predicted_rhoa,
                QuantityType.APPARENT_RESISTIVITY,
                "ohm*m",
            ),
            self._save_array(
                context,
                spec,
                run_dir,
                "observed_apparent_resistivity",
                observations * geometric_factor,
                QuantityType.APPARENT_RESISTIVITY,
                "ohm*m",
            ),
            self._save_array(
                context,
                spec,
                run_dir,
                "model_coverage",
                coverage,
                QuantityType.DIMENSIONLESS,
                "log10(coverage per m^2)",
            ),
        ]
        if removed:
            # Which measurements the section was actually fitted to.
            artifacts.append(
                self._save_array(
                    context,
                    spec,
                    run_dir,
                    "retained_measurements",
                    retained.astype(float),
                    QuantityType.DIMENSIONLESS,
                    "dimensionless",
                )
            )
        artifacts.append(self._save_mesh_geometry(context, spec, run_dir, geometry))

        summary: dict[str, float | int | str | bool] = {
            "engine": "pygimli",
            "engine_version": str(pg.__version__),
            "solver": f"ert_{config.mesh.dimension}d_dc",
            "dimension": config.mesh.dimension,
            "electrodes": len(electrodes),
            "quadrupoles": len(quadrupoles),
            "model_cells": int(len(resistivity_ohm_m)),
            "mesh_cells": int(parameter_domain.cellCount()),
            "chi_squared": chi_squared,
            "chi_squared_initial": history[0] if history else chi_squared,
            "iterations": int(manager.inv.iter),
            "covered_cells": int((coverage > coverage.max() - 2.0).sum()) if coverage.size else 0,
            "data_unit": "ohm",
            "model_unit": "ohm*m",
            "measurements_removed": removed,
            "quality_filtered": config.quality.is_active,
            # Which norm produced this model.
            "blocky_model": config.regularization.blocky_model,
            "robust_data": config.regularization.robust_data,
            # Whether the mesh surface follows terrain, read from the relief the
            # electrodes actually have.
            "topography_applied": bool(electrode_relief > FLAT_TOLERANCE_M),
            "electrode_relief_m": float(electrode_relief),
            # How far a supplied surface moved the electrodes, which is a separate
            # question and stays separate.
            "electrode_elevation_shift_m": (
                0.0 if elevation_shift is None else float(elevation_shift)
            ),
        }
        if config.chargeability_channel is not None:
            summary["chargeability_channel_present"] = True
        return RunResult(run_id=spec.run_id, summary=summary, artifacts=tuple(artifacts))

    @staticmethod
    def _apply_topography(
        electrodes: np.ndarray, topography_path: str | None
    ) -> tuple[np.ndarray, float | None]:
        """Put the electrodes on the supplied surface, and say how far they moved."""
        if topography_path is None:
            return electrodes, None
        path = Path(topography_path)
        if not path.is_file():
            raise ValueError(f"topography file {path} does not exist")
        table = np.genfromtxt(path, delimiter=",", names=True)
        names = table.dtype.names
        if names is None or not {"x_m", "y_m", "z_m"} <= set(names):
            raise ValueError("topography CSV must contain x_m, y_m and z_m columns")
        surface = np.column_stack(
            [
                np.atleast_1d(np.asarray(table["x_m"], dtype=float)),
                np.atleast_1d(np.asarray(table["y_m"], dtype=float)),
                np.atleast_1d(np.asarray(table["z_m"], dtype=float)),
            ]
        )
        if not surface.size or not np.isfinite(surface).all():
            raise ValueError("topography CSV must contain finite coordinates")
        placed = electrodes.copy()
        for index, electrode in enumerate(electrodes):
            offsets = surface[:, :2] - electrode[:2]
            placed[index, 2] = surface[int(np.argmin(np.einsum("ij,ij->i", offsets, offsets))), 2]
        return placed, float(np.abs(placed[:, 2] - electrodes[:, 2]).max())

    @staticmethod
    def _retained_measurements(
        data: Any,
        observations: np.ndarray,
        uncertainty: np.ndarray,
        quality: ERTDataQualitySpec,
    ) -> np.ndarray:
        """Indices of the measurements that pass every declared threshold."""
        keep = np.ones(observations.shape, dtype=bool)
        if not quality.is_active:
            return np.flatnonzero(keep)
        factor = np.asarray(data["k"], dtype=float)
        with np.errstate(invalid="ignore"):
            apparent = observations * factor
        if quality.drop_non_positive:
            keep &= apparent > 0.0
        if quality.minimum_apparent_resistivity is not None:
            keep &= apparent >= _scalar(quality.minimum_apparent_resistivity.value)
        if quality.maximum_apparent_resistivity is not None:
            keep &= apparent <= _scalar(quality.maximum_apparent_resistivity.value)
        if quality.maximum_geometric_factor is not None:
            keep &= np.abs(factor) <= quality.maximum_geometric_factor
        if quality.maximum_relative_error is not None:
            keep &= uncertainty <= quality.maximum_relative_error
        # A measurement whose apparent resistivity is not a number cannot be judged
        # against any threshold, so it fails all of them.
        keep &= np.isfinite(apparent)
        return np.flatnonzero(keep)

    @staticmethod
    def _build_data_container(
        ert: Any,
        electrodes: np.ndarray,
        quadrupoles: np.ndarray,
        observations: np.ndarray,
        uncertainty: np.ndarray,
        dimension: int,
    ) -> Any:
        """Fill a pyGIMLi DataContainerERT from OFAG's arrays."""
        if dimension == 2:
            sensors = np.column_stack([electrodes[:, 0], electrodes[:, 2]])
        else:
            sensors = electrodes
        data = ert.createData(elecs=sensors, schemeName="dd")
        data.resize(len(quadrupoles))
        for position, token in enumerate("abmn"):
            data[token] = quadrupoles[:, position]
        data["r"] = observations
        data["err"] = uncertainty
        data["valid"] = np.ones(len(quadrupoles), dtype=int)
        data["k"] = geometric_factors(ert, data, electrodes)
        return data

    @staticmethod
    def _relative_uncertainty(channel: DataChannelSpec, observations: np.ndarray) -> np.ndarray:
        """Turn the channel's declared uncertainty into pyGIMLi relative errors."""
        magnitude = canonicalize_quantity(
            channel.data_uncertainty.value,
            channel.data_uncertainty.unit,
            QuantityType.TRANSFER_RESISTANCE,
        )
        absolute = np.broadcast_to(np.asarray(magnitude, dtype=float), observations.shape)
        with np.errstate(divide="ignore", invalid="ignore"):
            relative = np.abs(absolute / observations)
        # A vanishing observation cannot carry a relative error; fall back to a large
        # one so the solver down-weights it rather than dividing by zero.
        return np.where(np.isfinite(relative) & (relative > 0), relative, 1.0)

    @staticmethod
    def _resistivity_limits(config: ERTInversionSpec) -> list[float] | None:
        bounds = (config.regularization.lower_bound, config.regularization.upper_bound)
        if all(bound is None for bound in bounds):
            return None
        lower, upper = bounds
        return [
            float(_scalar(lower.value)) if lower is not None else 1e-4,
            float(_scalar(upper.value)) if upper is not None else 1e6,
        ]

    @staticmethod
    def _optional_length(quantity: QuantitySpec | None) -> float | None:
        if quantity is None:
            return None
        return float(
            _scalar(canonicalize_quantity(quantity.value, quantity.unit, QuantityType.LENGTH))
        )

    @staticmethod
    def _save_array(
        context: PluginContext,
        spec: RunSpec,
        run_dir: Path,
        artifact_type: str,
        values: np.ndarray,
        quantity: QuantityType,
        unit: str,
    ) -> ArtifactManifest:
        path = run_dir / f"{artifact_type}.npy"
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
        context: PluginContext, spec: RunSpec, run_dir: Path, geometry: dict[str, np.ndarray]
    ) -> ArtifactManifest:
        path = run_dir / "mesh_geometry.npz"
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
            # Anchored to the artifact root, like every other artifact in the project: a
            # bare filename resolves against the root rather than the run, so a reader
            # finds nothing -- or another run's mesh.
            relative_path=path.relative_to(context.artifact_root).as_posix(),
        )


def _scalar(value: float | list[float] | np.ndarray) -> float:
    if isinstance(value, list):
        raise ValueError("a scalar quantity is required here, not a list")
    return float(np.asarray(value).item())
