"""Batch orchestration for independent SimPEG 1D TDEM soundings."""

import csv
import json
from pathlib import Path
from uuid import uuid5

import numpy as np
from pydantic import BaseModel

from ofag.core.constants import QuantityType
from ofag.core.conventions import ConventionCheck
from ofag.core.schemas import (
    ArtifactManifest,
    CapabilityManifest,
    ResourceEstimate,
    RunEvent,
    RunResult,
    RunSpec,
    TDEMBatchInversionSpec,
    TDEMBatchSoundingSpec,
    TDEMInversionSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.core.units import canonicalize_quantity
from ofag.engines.simpeg import conventions
from ofag.plugins.protocol import PluginContext, configuration_field
from ofag.plugins.simpeg_tdem1d import SimPEGTDEM1DPlugin


class SimPEGTDEMBatchPlugin:
    """Run a shared 1D TDEM inversion configuration over multiple soundings."""

    plugin_id = "simpeg.aem.batch_tdem1d"
    plugin_version = "0.1.0"

    def __init__(self) -> None:
        self._single = SimPEGTDEM1DPlugin()

    def physics_model(self) -> type[BaseModel] | None:
        return TDEMBatchInversionSpec

    @staticmethod
    def _configuration(spec: RunSpec) -> TDEMBatchInversionSpec | None:
        """Read this plugin's configuration from whichever form the run uses."""
        return spec.physics_as(TDEMBatchInversionSpec) or spec.tdem_batch_inversion

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.MAGNETIC_FLUX_DENSITY,),
            supported_meshes=("Layered1D",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Each sounding is an independent 1D inversion with shared earth discretization.",
                "Current local-process batch execution is deterministic and sequential.",
                "Distributed per-sounding scheduling will use the same child RunSpec contract.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if spec.engine != "simpeg":
            issues.append(
                ValidationIssue(
                    field="engine",
                    message="simpeg.aem.batch_tdem1d requires engine='simpeg'",
                    remediation="set engine: simpeg in the RunSpec",
                )
            )
        batch = self._configuration(spec)
        expected_quantity = (
            QuantityType(batch.soundings[0].system.receiver_quantity)
            if batch is not None
            else QuantityType.MAGNETIC_FLUX_DENSITY
        )
        if spec.dataset.physical_quantity is not expected_quantity:
            issues.append(
                ValidationIssue(
                    field="dataset.physical_quantity",
                    message=f"batch TDEM requires {expected_quantity.value} observations",
                    remediation="declare the batch manifest with the matching SI response quantity",
                )
            )
        if batch is None:
            issues.append(
                ValidationIssue(
                    field=configuration_field(spec, "tdem_batch_inversion"),
                    message="a TDEMBatchInversionSpec is required",
                    remediation="provide shared inversion settings and one or more soundings",
                )
            )
            return ValidationReport(valid=False, issues=tuple(issues))
        self._validate_batch_manifest(spec, issues)
        for sounding in batch.soundings:
            child = self._child_spec(spec, batch, sounding)
            child_report = self._single.validate(context, child)
            issues.extend(
                ValidationIssue(
                    field=f"tdem_batch_inversion.soundings.{sounding.sounding_id}.{issue.field}",
                    message=issue.message,
                    remediation=issue.remediation,
                )
                for issue in child_report.issues
            )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> tuple[ConventionCheck, ...]:
        return (conventions.layered_tem_layer_order(),)

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        batch = self._configuration(spec)
        if batch is None:
            return self._single.estimate_resources(context, spec)
        estimates = [
            self._single.estimate_resources(context, self._child_spec(spec, batch, sounding))
            for sounding in batch.soundings
        ]
        return ResourceEstimate(
            cpu_cores=1,
            memory_mb=max(estimate.memory_mb for estimate in estimates),
            estimated_seconds=sum(estimate.estimated_seconds for estimate in estimates),
        )

    def execute(
        self,
        context: PluginContext,
        spec: RunSpec,
    ) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            raise ValueError("; ".join(issue.message for issue in report.issues))
        batch = self._configuration(spec)
        assert batch is not None
        run_dir = context.artifact_root / str(spec.run_id)
        soundings_root = run_dir / "soundings"
        soundings_root.mkdir(parents=True, exist_ok=True)
        results: list[tuple[TDEMBatchSoundingSpec, RunResult]] = []
        # Each sounding is its own stage.
        total = len(batch.soundings)
        for index, sounding in enumerate(batch.soundings):
            context.emit(
                RunEvent(
                    run_id=spec.run_id,
                    event_type="iteration",
                    iteration=0,
                    stage=sounding.sounding_id,
                    stage_index=index,
                    stage_total=total,
                    message=f"sounding {sounding.sounding_id} started",
                )
            )
            child = self._child_spec(spec, batch, sounding)
            # The child writes its own progress under soundings/<child run id>/.
            result = self._single.execute(PluginContext(soundings_root), child)
            results.append((sounding, result))
            context.emit(
                RunEvent(
                    run_id=spec.run_id,
                    event_type="iteration",
                    iteration=1,
                    stage=sounding.sounding_id,
                    stage_index=index,
                    stage_total=total,
                    phi_total=self._summary_float(result, "phi_data")
                    + self._summary_float(result, "phi_model"),
                    phi_data=self._summary_float(result, "phi_data"),
                    phi_model=self._summary_float(result, "phi_model"),
                    message=f"sounding {sounding.sounding_id} completed",
                )
            )
        section_path = run_dir / "stitched_conductivity_section.npz"
        summary_path = run_dir / "sounding_summary.csv"
        batch_manifest_path = run_dir / "batch_manifest.json"
        self._write_section(soundings_root, results, section_path)
        self._write_summary(results, summary_path)
        batch_manifest_path.write_text(
            json.dumps(
                {
                    "soundings": [
                        {
                            "sounding_id": sounding.sounding_id,
                            "child_run_id": str(result.run_id),
                            "observation_count": result.summary["observation_count"],
                            "phi_data": result.summary["phi_data"],
                            "phi_model": result.summary["phi_model"],
                        }
                        for sounding, result in results
                    ],
                    "shared_layer_count": self._layer_count(batch),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        artifacts = [
            artifact
            for _, result in results
            for artifact in self._reparent_child_artifacts(spec, result)
        ]
        artifacts.extend(
            [
                self._artifact(
                    spec,
                    context,
                    section_path,
                    "stitched_conductivity_section",
                    QuantityType.DIMENSIONLESS,
                    "dimensionless",
                ),
                self._artifact(
                    spec,
                    context,
                    summary_path,
                    "sounding_summary",
                    QuantityType.DIMENSIONLESS,
                    "dimensionless",
                ),
                self._artifact(
                    spec,
                    context,
                    batch_manifest_path,
                    "batch_manifest",
                    QuantityType.DIMENSIONLESS,
                    "dimensionless",
                ),
            ]
        )
        # Chi-squared per sounding, which the batch had never reported: its summary said
        # how many soundings ran and not whether any of them fit, so a batch that
        # converged on nothing looked the same as one that worked.
        chi = np.array(
            [
                float(result.summary["phi_data"]) / max(1, int(result.summary["observation_count"]))
                for _, result in results
            ]
        )
        return RunResult(
            run_id=spec.run_id,
            summary={
                "engine": "simpeg",
                "solver": "tdem1d_batch",
                "sounding_count": len(results),
                "chi_squared_median": float(np.median(chi)),
                "chi_squared_worst": float(chi.max()),
                "soundings_fitting": int((chi <= 2.0).sum()),
                "model_layers": self._layer_count(batch),
                "data_unit": self._response_unit(
                    QuantityType(batch.soundings[0].system.receiver_quantity)
                ),
                "model_unit": "S/m",
            },
            artifacts=tuple(artifacts),
        )

    def _validate_batch_manifest(self, spec: RunSpec, issues: list[ValidationIssue]) -> None:
        path_text = self._string_parameter(spec, "batch_manifest_path")
        if path_text is None:
            issues.append(
                ValidationIssue(
                    field="parameters.batch_manifest_path",
                    message="a batch manifest is required",
                    remediation="provide a JSON manifest path",
                )
            )
            return
        path = Path(path_text)
        if not path.is_file():
            issues.append(
                ValidationIssue(
                    field="parameters.batch_manifest_path",
                    message=f"batch manifest does not exist: {path_text}",
                    remediation="write the manifest before validating the batch",
                )
            )
            return

    @staticmethod
    def _child_spec(
        parent: RunSpec, batch: TDEMBatchInversionSpec, sounding: TDEMBatchSoundingSpec
    ) -> RunSpec:
        return RunSpec(
            run_id=uuid5(parent.run_id, sounding.sounding_id),
            plugin_id=SimPEGTDEM1DPlugin.plugin_id,
            plugin_version=SimPEGTDEM1DPlugin.plugin_version,
            engine="simpeg",
            seed=parent.seed,
            dataset=parent.dataset.model_copy(
                update={
                    "name": f"{parent.dataset.name}-{sounding.sounding_id}",
                }
            ),
            executor=parent.executor.model_copy(update={"max_workers": 1}),
            tdem_inversion=TDEMInversionSpec(
                system=sounding.system,
                earth=batch.earth,
                model=batch.model,
                regularization=batch.regularization,
                optimizer=batch.optimizer,
                beta=batch.beta,
                directives=batch.directives,
            ),
            parameters={
                "observations_path": sounding.observations_path,
                "data_uncertainty": sounding.data_uncertainty,
            },
        )

    @staticmethod
    def _write_section(
        soundings_root: Path,
        results: list[tuple[TDEMBatchSoundingSpec, RunResult]],
        target: Path,
    ) -> None:
        conductivity: list[np.ndarray] = []
        locations: list[np.ndarray] = []
        sounding_ids: list[str] = []
        layer_tops: np.ndarray | None = None
        for sounding, result in results:
            result_dir = soundings_root / str(result.run_id)
            conductivity.append(np.load(result_dir / "recovered_conductivity_s_m.npy"))
            current_layer_tops = np.load(result_dir / "layer_top_depth_m.npy")
            if layer_tops is None:
                layer_tops = current_layer_tops
            elif not np.allclose(layer_tops, current_layer_tops):
                raise ValueError("all batch soundings must share the same layer depth contract")
            # The station, not the receiver.
            placed = sounding.station_location or sounding.system.receiver_location
            locations.append(
                np.asarray(
                    canonicalize_quantity(placed.value, placed.unit, QuantityType.LENGTH),
                    dtype=float,
                )
            )
            sounding_ids.append(sounding.sounding_id)
        assert layer_tops is not None
        np.savez_compressed(
            target,
            sounding_ids=np.asarray(sounding_ids),
            receiver_locations_m=np.vstack(locations),
            layer_top_depth_m=layer_tops,
            conductivity_s_m=np.vstack(conductivity),
        )

    @staticmethod
    def _write_summary(
        results: list[tuple[TDEMBatchSoundingSpec, RunResult]], target: Path
    ) -> None:
        with target.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=(
                    "sounding_id",
                    "child_run_id",
                    "observation_count",
                    "phi_data",
                    "phi_model",
                ),
            )
            writer.writeheader()
            for sounding, result in results:
                writer.writerow(
                    {
                        "sounding_id": sounding.sounding_id,
                        "child_run_id": result.run_id,
                        "observation_count": result.summary["observation_count"],
                        "phi_data": result.summary["phi_data"],
                        "phi_model": result.summary["phi_model"],
                    }
                )

    @staticmethod
    def _summary_float(result: RunResult, name: str) -> float:
        value = result.summary[name]
        return float(value)

    @staticmethod
    def _string_parameter(spec: RunSpec, name: str) -> str | None:
        value = spec.parameters.get(name)
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _layer_count(batch: TDEMBatchInversionSpec) -> int:
        values = batch.earth.layer_thicknesses.value
        assert isinstance(values, list)
        return len(values) + 1

    @staticmethod
    def _response_unit(quantity_type: QuantityType) -> str:
        return {
            QuantityType.MAGNETIC_FLUX_DENSITY: "T",
            QuantityType.MAGNETIC_FLUX_DENSITY_TIME_DERIVATIVE: "T/s",
        }[quantity_type]

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

    def _reparent_child_artifacts(
        self, parent: RunSpec, result: RunResult
    ) -> list[ArtifactManifest]:
        return [
            ArtifactManifest(
                artifact_type=artifact.artifact_type,
                physical_quantity=artifact.physical_quantity,
                units=artifact.units,
                source_run_id=parent.run_id,
                relative_path=(
                    Path(str(parent.run_id)) / "soundings" / artifact.relative_path
                ).as_posix(),
            )
            for artifact in result.artifacts
        ]
