"""A deterministic gravity fixture that exercises OFAG contracts offline."""

import math

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
    TensorMeshSpec,
    ValidationIssue,
    ValidationReport,
)
from ofag.plugins.protocol import PluginContext


class SyntheticGravityPlugin:
    plugin_id = "ofag.fixture.gravity3d"
    plugin_version = "0.1.0"

    def physics_model(self) -> type[BaseModel] | None:
        """This fixture has no physics configuration, rather than an unmigrated one."""
        return None

    def manifest(self) -> CapabilityManifest:
        return CapabilityManifest(
            plugin_id=self.plugin_id,
            plugin_version=self.plugin_version,
            supported_quantities=(QuantityType.GRAVITY_ACCELERATION,),
            supported_meshes=("TensorMesh",),
            supports_parallel=False,
            supports_restart=False,
            limitations=(
                "Deterministic offline contract fixture only; not a SimPEG numerical inversion.",
            ),
        )

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if spec.dataset.physical_quantity is not QuantityType.GRAVITY_ACCELERATION:
            issues.append(
                ValidationIssue(
                    field="dataset.physical_quantity",
                    message="gravity fixture requires gravity_acceleration data",
                    remediation="use m/s² or mGal data declared as gravity_acceleration",
                )
            )
        if not isinstance(spec.mesh, TensorMeshSpec):
            issues.append(
                ValidationIssue(
                    field="mesh",
                    message="gravity fixture requires a TensorMeshSpec",
                    remediation="provide a metric TensorMeshSpec with length cell_size",
                )
            )
        return ValidationReport(valid=not issues, issues=tuple(issues))

    def conventions(self) -> _Unverified:
        """Unverified, and least urgent: this plugin makes fixture data rather than reading a
        survey, so a wrong convention here produces a wrong fixture rather than a wrong
        model of real ground."""
        return UNVERIFIED

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate:
        cells = 1
        if isinstance(spec.mesh, TensorMeshSpec):
            cells = math.prod(spec.mesh.shape)
        return ResourceEstimate(cpu_cores=1, memory_mb=max(64, cells // 16), estimated_seconds=0)

    def execute(
        self,
        context: PluginContext,
        spec: RunSpec,
    ) -> RunResult:
        report = self.validate(context, spec)
        if not report.valid:
            detail = "; ".join(issue.message for issue in report.issues)
            raise ValueError(detail)

        context.emit(
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=0, phi_total=1.0)
        )
        run_dir = context.artifact_root / str(spec.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        summary_path = run_dir / "summary.txt"
        payload = "synthetic gravity contract fixture\nunit=mGal\nphi_total=0.0\n"
        summary_path.write_text(payload, encoding="utf-8")
        artifact = ArtifactManifest(
            artifact_type="summary",
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
            source_run_id=spec.run_id,
            relative_path=summary_path.relative_to(context.artifact_root).as_posix(),
        )
        context.emit(
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, phi_total=0.0)
        )
        return RunResult(
            run_id=spec.run_id,
            summary={"fixture": True, "phi_total": 0.0, "units": "mGal"},
            artifacts=(artifact,),
        )
