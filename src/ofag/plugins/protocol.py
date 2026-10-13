"""The protocol every OFAG inversion plugin must satisfy."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, JsonValue

from ofag.core.conventions import ConventionCheck, _Unverified
from ofag.core.schemas import (
    CapabilityManifest,
    ParameterSensitivity,
    ResourceEstimate,
    RunCheckpoint,
    RunEvent,
    RunResult,
    RunSpec,
    ValidationReport,
    spec_fingerprint,
)

#: What a plugin's saved progress is called inside a run directory.
CHECKPOINT_FILENAME = "checkpoint.json"


class PluginContext:
    """Narrow execution context; plugins receive no API or store handles."""

    def __init__(
        self,
        artifact_root: Path,
        emit: Callable[[RunEvent], None] | None = None,
    ) -> None:
        self.artifact_root = artifact_root
        self._emit = emit if emit is not None else self._append_progress_line

    def run_dir(self, run_id: UUID) -> Path:
        directory = self.artifact_root / str(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def emit(self, event: RunEvent) -> None:
        """Report progress from inside the numerical child process."""
        self._emit(event)

    def checkpoint(
        self,
        spec: RunSpec,
        state: dict[str, JsonValue],
        *,
        plugin_id: str,
        plugin_version: str,
        iteration: int | None = None,
    ) -> None:
        """Save enough to continue this solve if the process is lost."""
        directory = self.run_dir(spec.run_id)
        checkpoint = RunCheckpoint(
            plugin_id=plugin_id,
            plugin_version=plugin_version,
            spec_fingerprint=spec_fingerprint(spec),
            iteration=iteration,
            state=state,
        )
        path = directory / CHECKPOINT_FILENAME
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def resume_from(self, spec: RunSpec) -> RunCheckpoint | None:
        """The checkpoint this run left, if it left one this spec may continue."""
        path = self.run_dir(spec.run_id) / CHECKPOINT_FILENAME
        if not path.is_file():
            return None
        try:
            checkpoint = RunCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if checkpoint.spec_fingerprint != spec_fingerprint(spec):
            return None
        return checkpoint

    def _append_progress_line(self, event: RunEvent) -> None:
        path = self.run_dir(event.run_id) / "progress.jsonl"
        with path.open("a", encoding="utf-8") as stream:
            stream.write(event.model_dump_json() + "\n")
            stream.flush()


class InversionPlugin(Protocol):
    plugin_id: str
    plugin_version: str

    def manifest(self) -> CapabilityManifest: ...

    def physics_model(self) -> type[BaseModel] | None:
        """The plugin's own configuration model for `RunSpec.physics`."""
        ...

    def conventions(self) -> "tuple[ConventionCheck, ...] | _Unverified":
        """Independent confirmation that the engine means what the plugin assumes."""
        ...

    def validate(self, context: PluginContext, spec: RunSpec) -> ValidationReport: ...

    def estimate_resources(self, context: PluginContext, spec: RunSpec) -> ResourceEstimate: ...

    # Progress is reported through `context.emit`.
    def execute(self, context: PluginContext, spec: RunSpec) -> RunResult: ...


@runtime_checkable
class SensitivityCapable(Protocol):
    """A plugin that can say what its data sees before it is run."""

    def parameter_sensitivity(
        self, context: PluginContext, spec: RunSpec
    ) -> ParameterSensitivity: ...


def configuration_field(spec: RunSpec, legacy_field: str, path: str = "") -> str:
    """Name a configuration field in the form this run actually used."""
    root = "physics" if spec.physics is not None else legacy_field
    return f"{root}.{path}" if path else root
