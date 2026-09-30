"""SimPEG 3D TDEM forward modelling adapter (no inversion)."""

from importlib.util import find_spec
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from ofag.core.constants import QuantityType
from ofag.core.conventions import UNVERIFIED, _Unverified
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    TDEM3DForwardSpec,
    TensorMeshSpec,
    TreeMeshSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.plugins.protocol import PluginContext, configuration_field
from ofag.plugins.simpeg_tdem1d import SimPEGTDEM1DPlugin


class SimPEGTDEM3DForwardPlugin:
    """Compute paired 3D TDEM survey responses on OFAG meshes in SI units."""

    plugin_id = "simpeg.aem.tdem3d_forward"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        return TDEM3DForwardSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> TDEM3DForwardSpec | None:
        """Read this plugin's configuration from whichever form the run uses."""
        return spec.physics_as(TDEM3DForwardSpec) or spec.tdem3d_forward

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(
                QuantityType.MAGNETIC_FLUX_DENSITY,
                QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE,
            ),
            supported_meshes=("TensorMesh", "TreeMesh"),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "3D forward modelling only; no 3D inversion or sensitivity artifact is produced.",
                "Supports paired survey arrays and circular-loop or magnetic-dipole sources, "
                "but not independent system settings per sounding.",
                "Time gates are rectangular numerical averages; receiver transfer functions and "
                "waveform-file import are not yet modelled.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        config = self._configuration(spec)
        field = configuration_field(spec, "tdem3d_forward")
        if find_spec("simpeg") is None:
            issues.append(
                ValidationIssue(
                    field="environment",
                    message="SimPEG is not installed",
                    remediation="run `uv sync --extra simpeg`",
                )
            )
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message="tdem3d_forward requires engine='simpeg'",
                    remediation="set engine: simpeg",
                )
            )
        if not isinstance(spec.mesh, (TensorMeshSpec, TreeMeshSpec)):
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="3D TDEM forward requires TensorMeshSpec or TreeMeshSpec",
                    remediation="provide a metric mesh with air cells around the system",
                )
            )
        if isinstance(spec.mesh, TensorMeshSpec) and spec.mesh.dimension != 3:
            issues.append(
                ValidationIssue(
                    field="mesh.shape",
                    message="3D TDEM forward is a volume method and requires a 3D mesh",
                    remediation="give the mesh Easting, Northing and Elevation extents",
                )
            )
        if config is None:
            issues.append(
                ValidationIssue(
                    field=field,
                    message="a TDEM3DForwardSpec is required",
                    remediation="provide system, conductivity model and time steps",
                )
            )
        else:
            expected = QuantityType(config.system.receiver_quantity)
            if spec.dataset.physical_quantity is not expected:
                issues.append(
                    ValidationIssue(
                        field="dataset.physical_quantity",
                        message=f"dataset must declare {expected.value}",
                        remediation="match the selected receiver_quantity",
                    )
                )
            duration = sum(
                float(canonicalize_quantity(item.step.value, item.step.unit, QuantityType.TIME))
                * item.count
                for item in config.time_steps
            )
            initial_time = SimPEGTDEM1DPlugin._scalar_quantity(
                config.initial_time, QuantityType.TIME
            )
            times = self._simulation_times(config.system)
            if float(times.max()) > initial_time + duration:
                issues.append(
                    ValidationIssue(
                        field=f"{field}.time_steps",
                        message="time steps do not reach the last receiver time from initial_time",
                        remediation="increase total simulation time",
                    )
                )
            if config.system.waveform_times is not None:
                waveform_times = SimPEGTDEM1DPlugin._vector_quantity(
                    config.system.waveform_times, QuantityType.TIME
                )
                if initial_time > float(waveform_times.min()):
                    issues.append(
                        ValidationIssue(
                            field=f"{field}.initial_time",
                            message="initial_time must be no later than the waveform start",
                            remediation="start the simulation at or before waveform_times[0]",
                        )
                    )
            if config.model.conductivity_model is not None:
                path = Path(config.model.conductivity_model.path)
                if not path.is_file():
                    issues.append(
                        ValidationIssue(
                            field=f"{field}.model.conductivity_model",
                            message="conductivity model file is missing",
                            remediation="provide a .npy array",
                        )
                    )
            self._validate_survey_arrays(config.system, issues, field)
        self._validate_topography(spec, issues)
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> _Unverified:
        """Unverified. A 3D transient forward model has an independent check available -- it
        must agree with the layered simulation over ground that does not vary sideways --
        and it has not been written."""
        return UNVERIFIED

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        cells = int(np.prod(spec.mesh.shape)) if isinstance(spec.mesh, TensorMeshSpec) else 100_000
        config = self._configuration(spec)
        steps = sum(item.count for item in config.time_steps) if config else 1
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(512, cells * 32 // 1024),
            estimated_seconds=max(1, cells * steps // 5_000),
        )

    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(item.message for item in report.issues))
        config = self._configuration(spec)
        assert spec.mesh is not None and config is not None
        from discretize import TensorMesh  # type: ignore[import-untyped]
        from discretize.utils import (  # type: ignore[import-untyped]
            active_from_xyz,
            mesh_builder_xyz,
        )
        from simpeg import maps  # type: ignore[import-untyped]
        from simpeg.electromagnetics import time_domain as tdem  # type: ignore[import-untyped]

        source_locations, receiver_locations = self._survey_locations(config.system)
        topography = self._load_topography_parameter(spec)
        if isinstance(spec.mesh, TensorMeshSpec):
            mesh = TensorMesh(self._mesh_widths(spec.mesh), origin=spec.mesh.origin)
            active = (
                active_from_xyz(mesh, topography)
                if topography is not None
                else mesh.cell_centers[:, 2] < 0.0
            )
        else:
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
            depth = float(
                canonicalize_quantity(
                    spec.mesh.depth_core.value, spec.mesh.depth_core.unit, QuantityType.LENGTH
                )
            )
            builder_points = (
                topography
                if topography is not None
                else np.vstack([source_locations, receiver_locations])
            )
            mesh = mesh_builder_xyz(
                builder_points,
                cell_size,
                padding_distance=padding,
                depth_core=depth,
                mesh_type="tree",
                tree_diagonal_balance=spec.mesh.diagonal_balance,
            )
            if topography is not None:
                mesh.refine_surface(
                    topography,
                    padding_cells_by_level=spec.mesh.surface_padding_cells,
                    finalize=False,
                )
            mesh.refine_points(
                np.vstack([source_locations, receiver_locations]),
                padding_cells_by_level=spec.mesh.receiver_padding_cells,
                finalize=True,
            )
            active = (
                active_from_xyz(mesh, topography)
                if topography is not None
                else np.ones(mesh.nC, dtype=bool)
            )
        if not active.any():
            raise ValueError("3D TDEM mesh has no earth cells below z=0")
        response_quantity = QuantityType(config.system.receiver_quantity)
        times = self._simulation_times(config.system)
        receiver_class = (
            tdem.receivers.PointMagneticFluxDensity
            if response_quantity is QuantityType.MAGNETIC_FLUX_DENSITY
            else tdem.receivers.PointMagneticFluxTimeDerivative
        )
        sources = [
            self._source(
                tdem,
                receiver_class,
                config,
                source_location,
                receiver_location,
                times,
            )
            for source_location, receiver_location in zip(
                source_locations, receiver_locations, strict=True
            )
        ]
        sigma_map = maps.InjectActiveCells(
            mesh,
            active,
            SimPEGTDEM1DPlugin._scalar_quantity(
                config.model.air_conductivity, QuantityType.CONDUCTIVITY
            ),
        )
        simulation = tdem.Simulation3DMagneticFluxDensity(
            mesh,
            survey=tdem.Survey(sources),
            sigmaMap=sigma_map,
            t0=SimPEGTDEM1DPlugin._scalar_quantity(config.initial_time, QuantityType.TIME),
            time_steps=[
                (SimPEGTDEM1DPlugin._scalar_quantity(item.step, QuantityType.TIME), item.count)
                for item in config.time_steps
            ],
        )
        conductivity = self._conductivity(
            config.model.conductivity_model, config.model.conductivity, active, mesh.nC
        )
        conductivity = self._apply_conductivity_blocks(
            conductivity, mesh.cell_centers[active], config.model.conductivity_blocks
        )
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=0,
                message="3D forward started",
            )
        )
        raw_predicted = np.asarray(simulation.dpred(conductivity), dtype=float)
        predicted = self._apply_time_gates(
            raw_predicted, config.system, times, source_locations.shape[0]
        )
        root = context.artifact_root / str(spec.run_id)
        root.mkdir(parents=True, exist_ok=True)
        suffix = SimPEGTDEM1DPlugin._response_suffix(response_quantity)
        data_path = root / f"predicted_{suffix}.npy"
        geometry_path = root / "mesh_geometry.npz"
        survey_path = root / "survey_definition.npz"
        np.save(data_path, predicted)
        np.savez_compressed(geometry_path, cell_centers_m=mesh.cell_centers, active_cells=active)
        self._write_survey_definition(
            survey_path, config.system, source_locations, receiver_locations
        )
        unit = SimPEGTDEM1DPlugin._response_unit(response_quantity)
        artifacts = (
            self._artifact(spec, context, data_path, "predicted_data", response_quantity, unit),
            self._artifact(
                spec,
                context,
                geometry_path,
                "mesh_geometry",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
            self._artifact(
                spec,
                context,
                survey_path,
                "survey_definition",
                QuantityType.DIMENSIONLESS,
                "dimensionless",
            ),
        )
        context.emit(
            RunEvent(
                run_id=spec.run_id,
                event_type="iteration",
                iteration=1,
                message="3D forward completed",
            )
        )
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "tdem3d_forward",
                "mesh_cells": int(mesh.nC),
                "model_cells": int(active.sum()),
                "sounding_count": int(source_locations.shape[0]),
                "channel_count": self._channel_count(config.system),
                "observation_count": int(predicted.size),
                "data_unit": unit,
            },
            artifacts=artifacts,
        )

    @staticmethod
    def _mesh_widths(mesh: TensorMeshSpec) -> list[np.ndarray]:
        if mesh.cell_widths is None:
            size = np.asarray(
                canonicalize_quantity(
                    mesh.cell_size.value, mesh.cell_size.unit, QuantityType.LENGTH
                ),
                dtype=float,
            )
            return [np.full(mesh.shape[index], size[index]) for index in range(3)]
        return [
            np.asarray(
                canonicalize_quantity(item.value, item.unit, QuantityType.LENGTH), dtype=float
            )
            for item in mesh.cell_widths
        ]

    def _validate_survey_arrays(
        self, system: Any, issues: list[ValidationIssue], field: str
    ) -> None:
        if system.source_locations is None:
            return
        assert system.receiver_locations is not None
        try:
            source_locations = self._load_location_array(system.source_locations)
            receiver_locations = self._load_location_array(system.receiver_locations)
            if source_locations.shape != receiver_locations.shape:
                raise ValueError(
                    "source_locations and receiver_locations must have equal (N, 3) shapes"
                )
        except ValueError as error:
            issues.append(
                ValidationIssue(
                    field=f"{field}.system.source_locations",
                    message=str(error),
                    remediation="provide finite (N, 3) .npy arrays in length units",
                )
            )

    @staticmethod
    def _load_location_array(source: Any) -> np.ndarray:
        path = Path(source.path)
        if not path.is_file():
            raise ValueError("survey location array is missing")
        values = np.asarray(np.load(path, allow_pickle=False), dtype=float)
        if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] != 3:
            raise ValueError("survey location arrays must have a non-empty (N, 3) shape")
        if not np.isfinite(values).all():
            raise ValueError("survey location arrays must contain only finite coordinates")
        return np.asarray(
            canonicalize_quantity(values, source.unit, QuantityType.LENGTH), dtype=float
        )

    def _survey_locations(self, system: Any) -> tuple[np.ndarray, np.ndarray]:
        if system.source_locations is not None:
            assert system.receiver_locations is not None
            source_locations = self._load_location_array(system.source_locations)
            receiver_locations = self._load_location_array(system.receiver_locations)
            if source_locations.shape != receiver_locations.shape:
                raise ValueError(
                    "source_locations and receiver_locations must have equal (N, 3) shapes"
                )
            return source_locations, receiver_locations
        return (
            SimPEGTDEM1DPlugin._vector_quantity(
                system.source_location, QuantityType.LENGTH
            ).reshape(1, 3),
            SimPEGTDEM1DPlugin._vector_quantity(
                system.receiver_location, QuantityType.LENGTH
            ).reshape(1, 3),
        )

    @staticmethod
    def _source(
        tdem: Any,
        receiver_class: Any,
        config: Any,
        source_location: np.ndarray,
        receiver_location: np.ndarray,
        times: np.ndarray,
    ) -> Any:
        receiver = receiver_class(
            receiver_location.reshape(1, 3),
            times,
            orientation=config.system.receiver_orientation,
        )
        waveform = SimPEGTDEM1DPlugin._build_waveform(tdem, config)
        if config.system.source_kind == "magnetic_dipole":
            assert config.system.source_moment is not None
            return tdem.sources.MagDipole(
                receiver_list=[receiver],
                location=source_location,
                orientation=config.system.source_orientation,
                moment=SimPEGTDEM1DPlugin._scalar_quantity(
                    config.system.source_moment, QuantityType.MAGNETIC_DIPOLE_MOMENT
                ),
                waveform=waveform,
            )
        return tdem.sources.CircularLoop(
            receiver_list=[receiver],
            location=source_location,
            orientation=config.system.source_orientation,
            radius=SimPEGTDEM1DPlugin._scalar_quantity(
                config.system.source_radius, QuantityType.LENGTH
            ),
            current=SimPEGTDEM1DPlugin._scalar_quantity(
                config.system.source_current, QuantityType.ELECTRIC_CURRENT
            ),
            n_turns=config.system.source_turns,
            waveform=waveform,
        )

    @staticmethod
    def _simulation_times(system: Any) -> np.ndarray:
        channel_times = SimPEGTDEM1DPlugin._vector_quantity(system.times, QuantityType.TIME)
        if not system.time_gates:
            return channel_times
        gate_samples = [
            np.linspace(
                SimPEGTDEM1DPlugin._scalar_quantity(gate.start, QuantityType.TIME),
                SimPEGTDEM1DPlugin._scalar_quantity(gate.end, QuantityType.TIME),
                gate.integration_points,
            )
            for gate in system.time_gates
        ]
        return np.unique(np.concatenate([channel_times, *gate_samples]))

    @staticmethod
    def _apply_time_gates(
        predicted: np.ndarray, system: Any, simulation_times: np.ndarray, sounding_count: int
    ) -> np.ndarray:
        if not system.time_gates:
            return predicted
        channels = predicted.reshape(sounding_count, simulation_times.size)
        values = np.empty((sounding_count, len(system.time_gates)), dtype=float)
        for gate_index, gate in enumerate(system.time_gates):
            start = SimPEGTDEM1DPlugin._scalar_quantity(gate.start, QuantityType.TIME)
            end = SimPEGTDEM1DPlugin._scalar_quantity(gate.end, QuantityType.TIME)
            quadrature_times = np.linspace(start, end, gate.integration_points)
            for sounding_index, response in enumerate(channels):
                values[sounding_index, gate_index] = np.trapezoid(
                    np.interp(quadrature_times, simulation_times, response), quadrature_times
                ) / (end - start)
        return values.reshape(-1)

    @staticmethod
    def _channel_count(system: Any) -> int:
        return len(system.time_gates) or len(system.times.value)

    @staticmethod
    def _write_survey_definition(
        path: Path,
        system: Any,
        source_locations: np.ndarray,
        receiver_locations: np.ndarray,
    ) -> None:
        gate_starts = np.asarray(
            [
                SimPEGTDEM1DPlugin._scalar_quantity(gate.start, QuantityType.TIME)
                for gate in system.time_gates
            ],
            dtype=float,
        )
        gate_ends = np.asarray(
            [
                SimPEGTDEM1DPlugin._scalar_quantity(gate.end, QuantityType.TIME)
                for gate in system.time_gates
            ],
            dtype=float,
        )
        np.savez_compressed(
            path,
            source_locations_m=source_locations,
            receiver_locations_m=receiver_locations,
            receiver_times_s=SimPEGTDEM1DPlugin._vector_quantity(system.times, QuantityType.TIME),
            gate_starts_s=gate_starts,
            gate_ends_s=gate_ends,
        )

    @staticmethod
    def _conductivity(source: Any, value: Any, active: np.ndarray, cells: int) -> np.ndarray:
        if source is None:
            return np.full(
                int(active.sum()),
                SimPEGTDEM1DPlugin._scalar_quantity(value, QuantityType.CONDUCTIVITY),
            )
        values = np.asarray(np.load(source.path, allow_pickle=False), dtype=float).reshape(-1)
        if values.size == cells:
            values = values[active]
        if values.size != int(active.sum()) or not np.isfinite(values).all() or np.any(values <= 0):
            raise ValueError("conductivity_model must contain positive active or mesh values")
        return np.asarray(
            canonicalize_quantity(values, source.unit, QuantityType.CONDUCTIVITY), dtype=float
        )

    @staticmethod
    def _apply_conductivity_blocks(
        conductivity: np.ndarray, cell_centers: np.ndarray, blocks: tuple[Any, ...]
    ) -> np.ndarray:
        values = conductivity.copy()
        for block in blocks:
            minimum = SimPEGTDEM1DPlugin._vector_quantity(block.minimum, QuantityType.LENGTH)
            maximum = SimPEGTDEM1DPlugin._vector_quantity(block.maximum, QuantityType.LENGTH)
            inside = np.all((cell_centers >= minimum) & (cell_centers <= maximum), axis=1)
            values[inside] = SimPEGTDEM1DPlugin._scalar_quantity(
                block.conductivity, QuantityType.CONDUCTIVITY
            )
        return values

    def _validate_topography(self, spec: RunSpec, issues: list[ValidationIssue]) -> None:
        path_text = self._string_parameter(spec, "topography_path")
        if path_text is None:
            return
        path = Path(path_text)
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    field="parameters.topography_path",
                    message="topography file is missing",
                    remediation="provide the exact SI topography CSV",
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

    def _load_topography_parameter(self, spec: RunSpec) -> np.ndarray | None:
        path_text = self._string_parameter(spec, "topography_path")
        return self._load_topography(Path(path_text)) if path_text is not None else None

    @staticmethod
    def _string_parameter(spec: RunSpec, name: str) -> str | None:
        value = spec.parameters.get(name)
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _load_topography(path: Path) -> np.ndarray:
        table = np.genfromtxt(path, delimiter=",", names=True, dtype=float, encoding="utf-8")
        required = {"x_m", "y_m", "z_m"}
        names = set(table.dtype.names or ())
        if required - names:
            raise ValueError("topography CSV must contain x_m,y_m,z_m")
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
