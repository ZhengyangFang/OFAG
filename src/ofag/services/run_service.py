"""Run orchestration; numerical code never runs inside FastAPI route handlers."""

import json
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from threading import RLock, Thread
from uuid import UUID, uuid4

import yaml
from pydantic import ValidationError

from ofag.core.conventions import engine_fingerprint, run_checks
from ofag.core.schemas import (
    CapabilityManifest,
    ParameterSensitivity,
    ResourceEstimate,
    RunCheckpoint,
    RunEvent,
    RunRecord,
    RunResult,
    RunSpec,
    RunState,
    ValidationIssue,
    ValidationReport,
)
from ofag.execution.local_process import JobHandle, LocalProcessExecutor
from ofag.execution.state import IN_FLIGHT_STATES, transition
from ofag.plugins.protocol import InversionPlugin, PluginContext, SensitivityCapable
from ofag.plugins.registry import PluginRegistry, default_registry

DEFAULT_ARTIFACT_ROOT = Path("artifacts")
CANCEL_REQUEST_FILENAME = "cancel.request"


def execute_registered_plugin(spec: RunSpec, artifact_root: Path) -> RunResult:
    """Picklable child-process entrypoint used by LocalProcessExecutor."""
    registry = default_registry()
    plugin = registry.get(spec.plugin_id)
    result = plugin.execute(PluginContext(artifact_root=artifact_root), spec)
    # A second process must be able to discover a finished solve even if the submitting
    # service has not drained its queue yet.
    path = artifact_root / str(spec.run_id) / "result.json"
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return result


def _process_alive(pid: int) -> bool:
    """Whether a process with this id exists, without signalling it."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_query_limited_information = 0x1000
        still_active = 259
        error_access_denied = 5
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            # Denied means it exists and belongs to someone else.
            return ctypes.get_last_error() == error_access_denied
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class RunService:
    def __init__(
        self,
        registry: PluginRegistry | None = None,
        executor: LocalProcessExecutor | None = None,
        artifact_root: Path | None = None,
    ) -> None:
        # Injectable so tests do not deposit run output into the working tree.
        self._artifact_root = artifact_root or DEFAULT_ARTIFACT_ROOT
        self._registry = registry or default_registry()
        self._executor = executor or LocalProcessExecutor()
        self._records: dict[UUID, RunRecord] = {}
        self._events: dict[UUID, list[RunEvent]] = {}
        self._jobs: dict[UUID, JobHandle] = {}
        self._results: dict[UUID, RunResult] = {}
        self._ingested_progress_lines: dict[UUID, int] = {}
        self._refresh_lock = RLock()

    @property
    def artifact_root(self) -> Path:
        """Where this service reads and writes run output."""
        return self._artifact_root

    def list_plugins(self) -> tuple[CapabilityManifest, ...]:
        return tuple(plugin.manifest() for plugin in self._registry.all())

    def list_runs(self, project_id: UUID | None = None) -> tuple[RunRecord, ...]:
        """Discover persisted runs, including runs created before this process started."""
        if self._artifact_root.is_dir():
            for record_path in self._artifact_root.glob("*/run_record.json"):
                try:
                    record = RunRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    # A partially written legacy record must not prevent users from
                    # opening their other completed projects.
                    continue
                if record.spec.run_id not in self._records:
                    self._adopt(record)
        # A listing reports state, so it has to collect finished children the same way
        # `get` does.
        for run_id, record in tuple(self._records.items()):
            if record.state is RunState.RUNNING:
                self._refresh(run_id)
        records = tuple(
            record
            for record in self._records.values()
            if project_id is None or record.spec.project_id == project_id
        )
        return tuple(sorted(records, key=lambda record: record.updated_at, reverse=True))

    def validate(self, spec: RunSpec) -> ValidationReport:
        plugin = self._registry.get(spec.plugin_id)
        payload_issues = self._physics_payload_issues(plugin, spec)
        if payload_issues:
            # The plugin cannot parse its own configuration, so asking it to validate
            # the rest would only produce noise.
            return ValidationReport(valid=False, issues=tuple(payload_issues))
        report = plugin.validate(PluginContext(self._artifact_root), spec)
        convention_issues = self._convention_issues(plugin)
        if not convention_issues:
            return report
        return ValidationReport(
            valid=report.valid
            and not any(issue.field == "conventions" for issue in convention_issues),
            issues=tuple(report.issues) + tuple(convention_issues),
        )

    @staticmethod
    def _convention_issues(plugin: InversionPlugin) -> list[ValidationIssue]:
        """Confirm the engine's conventions before anything is dispatched."""
        checker = getattr(plugin, "conventions", None)
        if checker is None:
            return [
                ValidationIssue(
                    field="conventions.declaration",
                    message=(
                        f"plugin {plugin.plugin_id!r} declares no conventions() method, so its "
                        "engine's signs, axis order and array order are unconfirmed"
                    ),
                    remediation=(
                        "implement conventions() returning checks against closed-form "
                        "arithmetic or a second implementation, or UNVERIFIED with a reason"
                    ),
                )
            ]
        outcome = run_checks(
            plugin.plugin_id,
            engine_fingerprint("simpeg", "discretize", "numpy"),
            checker(),
        )
        if outcome.unverified_reason is not None:
            return [
                ValidationIssue(
                    field="conventions.unverified",
                    message=f"{plugin.plugin_id}: {outcome.unverified_reason}",
                    remediation="add a convention check against something outside the engine",
                )
            ]
        return [
            ValidationIssue(
                field="conventions",
                message=(
                    f"{plugin.plugin_id} failed the convention check {check.name!r}: "
                    f"{result.detail}"
                ),
                remediation=(
                    f"this check exists to catch: {check.catches}. It compares the engine "
                    f"against {check.against}. Do not run an inversion until it passes."
                ),
            )
            for check, result in outcome.failures
        ]

    @staticmethod
    def _physics_payload_issues(plugin: InversionPlugin, spec: RunSpec) -> list[ValidationIssue]:
        """Check `RunSpec.physics` against the model the plugin declares."""
        model = plugin.physics_model()
        if model is None:
            if spec.physics is not None:
                return [
                    ValidationIssue(
                        field="physics",
                        message=f"plugin {spec.plugin_id!r} does not accept a physics payload",
                        remediation="use this plugin's schema 1.0 configuration field instead",
                    )
                ]
            return []
        if spec.physics is None:
            return []
        try:
            spec.physics_as(model)
        except ValidationError as error:
            return [
                ValidationIssue(
                    field="physics." + ".".join(str(part) for part in item["loc"]),
                    message=item["msg"],
                    remediation=f"correct this field against the {model.__name__} contract",
                )
                for item in error.errors()
            ]
        return []

    def estimate_resources(self, spec: RunSpec) -> ResourceEstimate:
        """Return the selected plugin's estimate without creating or dispatching a run."""
        plugin = self._registry.get(spec.plugin_id)
        return plugin.estimate_resources(PluginContext(self._artifact_root), spec)

    def plugin(self, plugin_id: str) -> InversionPlugin:
        """The registered plugin, for a caller that needs more than a manifest."""
        return self._registry.get(plugin_id)

    def parameter_sensitivity(self, spec: RunSpec) -> ParameterSensitivity:
        """What this configuration's data can see, before it is run."""
        plugin = self._registry.get(spec.plugin_id)
        if not isinstance(plugin, SensitivityCapable):
            raise ValueError(f"{spec.plugin_id} cannot report what its data sees")
        return plugin.parameter_sensitivity(PluginContext(self._artifact_root), spec)

    def adopt_external_result(self, spec: RunSpec, result: RunResult) -> RunRecord:
        """Register a result this service did not compute, as a completed run."""
        if spec.run_id in self._records:
            raise ValueError(f"run {spec.run_id} already exists")
        record = RunRecord(spec=spec, state=RunState.SUCCEEDED)
        self._records[spec.run_id] = record
        self._results[spec.run_id] = result
        self._events[spec.run_id] = [self._state_event(record)]
        self._persist_record(record)
        self._persist_run_spec(spec)
        (self._run_dir(spec.run_id) / "result.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        return record

    def run_dir(self, run_id: UUID) -> Path:
        """Where a run's artifacts live."""
        return self._run_dir(run_id)

    def create(self, spec: RunSpec) -> RunRecord:
        if spec.run_id in self._records:
            raise ValueError(f"run {spec.run_id} already exists")
        report = self.validate(spec)
        if not report.valid:
            joined = "; ".join(issue.message for issue in report.issues)
            raise ValueError(f"invalid RunSpec: {joined}")
        record = RunRecord(spec=spec)
        record = self._with_state(record, RunState.VALIDATED)
        self._records[spec.run_id] = record
        self._events[spec.run_id] = [self._state_event(record)]
        self._persist_record(record)
        self._persist_run_spec(spec)
        return record

    def start(self, run_id: UUID) -> RunRecord:
        record = self.get(run_id)
        (self._run_dir(run_id) / CANCEL_REQUEST_FILENAME).unlink(missing_ok=True)
        record = self._with_state(record, RunState.QUEUED)
        self._records[run_id] = record
        self._persist_record(record)
        self._events[run_id].append(self._state_event(record))
        handle = self._executor.submit(
            record.spec, partial(execute_registered_plugin, artifact_root=self._artifact_root)
        )
        self._jobs[run_id] = handle
        (self._run_dir(run_id) / "owner.json").write_text(
            json.dumps({"pid": handle.pid, "owner_pid": os.getpid()}), encoding="utf-8"
        )
        record = self._with_state(record, RunState.RUNNING)
        self._records[run_id] = record
        self._persist_record(record)
        self._events[run_id].append(self._state_event(record))
        Thread(target=self._watch_run, args=(run_id,), daemon=True).start()
        return record

    def _watch_run(self, run_id: UUID) -> None:
        """Collect a finished worker and honor cancellation without UI polling."""
        while True:
            with self._refresh_lock:
                record = self._records.get(run_id)
                if record is None or record.state is not RunState.RUNNING:
                    return
                handle = self._jobs.get(run_id)
                if handle is None:
                    return
                requested = (self._run_dir(run_id) / CANCEL_REQUEST_FILENAME).is_file()
                if requested or self._executor.status(handle.job_id) != "RUNNING":
                    self._refresh_locked(run_id)
            time.sleep(0.1)

    def resume(self, run_id: UUID) -> RunRecord:
        """Continue an interrupted run from the checkpoint it saved."""
        record = self.get(run_id)
        if record.state is not RunState.INTERRUPTED:
            raise ValueError(
                f"run {run_id} is {record.state.value} and only an interrupted run can be resumed"
            )
        checkpoint = self._checkpoint(record.spec)
        if checkpoint is None:
            raise ValueError(
                f"run {run_id} has no checkpoint matching its specification, so there is "
                "nothing to continue from"
            )
        return self.start(run_id)

    def get(self, run_id: UUID) -> RunRecord:
        try:
            record = self._records[run_id]
        except KeyError as error:
            loaded_record = self._load_record(run_id)
            if loaded_record is None:
                raise KeyError(f"run {run_id} does not exist") from error
            record = self._adopt(loaded_record)
        if record.state is RunState.RUNNING:
            self._refresh(run_id)
        return self._records[run_id]

    def _adopt(self, record: RunRecord) -> RunRecord:
        """Take a persisted record into this service, resolving orphaned runs."""
        run_id = record.spec.run_id
        self._events.setdefault(run_id, [self._state_event(record)])
        reconciled = self._reconcile_orphan(record)
        if reconciled is not record:
            self._events[run_id].append(self._state_event(reconciled))
            self._persist_record(reconciled)
        self._records[run_id] = reconciled
        return reconciled

    def _reconcile_orphan(self, record: RunRecord) -> RunRecord:
        """Resolve a RUNNING record whose child process this service never held."""
        run_id = record.spec.run_id
        if record.state is not RunState.RUNNING or run_id in self._jobs:
            return record
        if (self._artifact_root / str(run_id) / "result.json").is_file():
            return self._with_state(record, RunState.SUCCEEDED)
        if self._owner_alive(run_id):
            return record
        checkpoint = self._checkpoint(record.spec)
        if checkpoint is not None:
            # Cut off, not gone wrong.
            reached = (
                "" if checkpoint.iteration is None else f" at iteration {checkpoint.iteration}"
            )
            return RunRecord(
                spec=record.spec,
                state=transition(record.state, RunState.INTERRUPTED),
                created_at=record.created_at,
                updated_at=datetime.now(UTC),
                error=(
                    f"the service stopped while this run was executing; it saved a checkpoint"
                    f"{reached}, so it can be resumed"
                ),
            )
        return RunRecord(
            spec=record.spec,
            state=transition(record.state, RunState.FAILED),
            created_at=record.created_at,
            updated_at=datetime.now(UTC),
            error=(
                "the service stopped while this run was executing, so its child "
                "process was lost, and it saved no checkpoint; resubmit the run "
                "to try again"
            ),
        )

    def _owner_alive(self, run_id: UUID) -> bool:
        try:
            payload = json.loads(
                (self._artifact_root / str(run_id) / "owner.json").read_text(encoding="utf-8")
            )
            pid = int(payload["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        return _process_alive(pid)

    def _checkpoint(self, spec: RunSpec) -> RunCheckpoint | None:
        """The checkpoint a run left, if one matching its spec is on disk."""
        return PluginContext(self._artifact_root).resume_from(spec)

    def checkpoint(self, run_id: UUID) -> RunCheckpoint | None:
        """What a run saved of itself, for the interface to report."""
        return self._checkpoint(self.get(run_id).spec)

    def events(self, run_id: UUID) -> tuple[RunEvent, ...]:
        self.get(run_id)
        return self._deduplicated_events(self._events[run_id])

    def result(self, run_id: UUID) -> RunResult | None:
        record = self.get(run_id)
        if record.state is not RunState.SUCCEEDED:
            return None
        cached = self._results.get(run_id)
        if cached is not None:
            return cached
        result_path = self._run_dir(run_id) / "result.json"
        if not result_path.exists():
            return None
        result = RunResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        self._results[run_id] = result
        return result

    def cancel(self, run_id: UUID) -> RunRecord:
        record = self.get(run_id)
        if record.state not in {RunState.QUEUED, RunState.RUNNING, RunState.VALIDATED}:
            raise ValueError(f"run {run_id} cannot be cancelled from {record.state.value}")
        handle = self._jobs.get(run_id)
        if handle is None and record.state in {RunState.QUEUED, RunState.RUNNING}:
            if not self._owner_alive(run_id):
                if record.state is RunState.QUEUED:
                    # Queued and owned by nobody: the submit failed or the owner died
                    # before writing owner.json, so no child can be writing.
                    return self._mark_cancelled(record)
                raise ValueError(f"run {run_id} has no live owner to accept cancellation")
            path = self._run_dir(run_id) / CANCEL_REQUEST_FILENAME
            path.write_text("requested\n", encoding="utf-8")
            # A running owner watches this file independently of API polling.
            for _ in range(20):
                time.sleep(0.05)
                latest = self._load_record(run_id)
                if latest is not None and latest.state is not RunState.RUNNING:
                    self._records[run_id] = latest
                    return latest
            return record
        if handle is not None:
            with self._refresh_lock:
                return self._cancel_owned(run_id, handle)
        return self._mark_cancelled(record)

    def _cancel_owned(self, run_id: UUID, handle: JobHandle) -> RunRecord:
        if self._records[run_id].state is not RunState.RUNNING:
            raise ValueError(f"run {run_id} is no longer running")
        self._executor.cancel(handle.job_id)
        self._jobs.pop(run_id, None)
        return self._mark_cancelled(self._records[run_id])

    def _mark_cancelled(self, record: RunRecord) -> RunRecord:
        cancelled = self._with_state(record, RunState.CANCELLED)
        run_id = record.spec.run_id
        self._records[run_id] = cancelled
        self._events[run_id].append(self._state_event(cancelled))
        self._persist_record(cancelled)
        return cancelled

    def delete(self, run_id: UUID) -> None:
        """Remove one finished run and everything it wrote."""
        # Refuse a run already known to this process as in flight before a status
        # refresh can reinterpret a missing synthetic/stale worker.
        known = self._records.get(run_id)
        if known is not None and known.state in IN_FLIGHT_STATES:
            raise ValueError(
                f"run {run_id} is {known.state.value} and a process may still be writing "
                "to its directory; cancel it before deleting it"
            )
        record = self.get(run_id)
        if record.state in IN_FLIGHT_STATES:
            raise ValueError(
                f"run {run_id} is {record.state.value} and a process may still be writing "
                "to its directory; cancel it before deleting it"
            )
        run_dir = self._run_dir(run_id)
        if run_dir.is_dir():
            shutil.rmtree(run_dir)
        # Dropped from every index together.
        self._records.pop(run_id, None)
        self._events.pop(run_id, None)
        self._jobs.pop(run_id, None)
        self._results.pop(run_id, None)
        self._ingested_progress_lines.pop(run_id, None)

    def _refresh(self, run_id: UUID) -> None:
        # The monitor requests the state and events independently.
        with self._refresh_lock:
            self._refresh_locked(run_id)

    def _refresh_locked(self, run_id: UUID) -> None:
        if self._records[run_id].state is not RunState.RUNNING:
            return
        self._ingest_progress_events(run_id)
        handle = self._jobs.get(run_id)
        if handle is None:
            latest = self._load_record(run_id)
            if latest is not None and latest.state is not RunState.RUNNING:
                if latest.state is not self._records[run_id].state:
                    self._events[run_id].append(self._state_event(latest))
                self._records[run_id] = latest
                return
            reconciled = self._reconcile_orphan(self._records[run_id])
            if reconciled is not self._records[run_id]:
                self._records[run_id] = reconciled
                self._events[run_id].append(self._state_event(reconciled))
                self._persist_record(reconciled)
            return
        if self._executor.status(handle.job_id) == "RUNNING":
            if (self._run_dir(run_id) / CANCEL_REQUEST_FILENAME).is_file():
                self._cancel_owned(run_id, handle)
            return
        record = self._records[run_id]
        try:
            result = self._executor.collect(handle.job_id)
        except Exception as error:
            record = RunRecord(
                spec=record.spec,
                state=transition(record.state, RunState.FAILED),
                created_at=record.created_at,
                updated_at=datetime.now(UTC),
                error=str(error),
            )
            self._events[run_id].append(
                RunEvent(run_id=run_id, event_type="error", message="numerical process failed")
            )
        else:
            self._results[run_id] = result
            record = self._with_state(record, RunState.SUCCEEDED)
        self._jobs.pop(run_id, None)
        self._records[run_id] = record
        self._events[run_id].append(self._state_event(record))
        self._persist_record(record)
        completed_result = self._results.get(run_id)
        if completed_result is not None:
            # Atomic, like the child's own write: another service reconciling this run
            # may read result.json at any moment, and a plain write_text exposes a
            # truncated file while it is being rewritten.
            path = self._run_dir(run_id) / "result.json"
            temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
            temporary.write_text(completed_result.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    def _ingest_progress_events(self, run_id: UUID) -> None:
        """Copy child-process progress updates into the service event stream."""
        progress_path = self._run_dir(run_id) / "progress.jsonl"
        if not progress_path.is_file():
            return
        try:
            lines = progress_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        events = self._events.setdefault(run_id, [])
        # The monitor re-reads this file every poll, so track how much of it has already
        # been consumed instead of trying to recognise duplicates by content.
        consumed = self._ingested_progress_lines.get(run_id, 0)
        appended = 0
        for line in lines[consumed:]:
            if not line.strip():
                appended += 1
                continue
            event = self._parse_progress_line(run_id, line)
            if event is None:
                # The child may be mid-write on the final line; it will be complete on
                # the next poll, so stop rather than skip it.
                break
            events.append(event)
            appended += 1
        self._ingested_progress_lines[run_id] = consumed + appended

    @staticmethod
    def _parse_progress_line(run_id: UUID, line: str) -> RunEvent | None:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        # Runs recorded before the event channel carried whole RunEvents wrote a bare
        # iteration record, so supply what those lines omit.
        payload.setdefault("run_id", str(run_id))
        payload.setdefault("event_type", "iteration")
        try:
            return RunEvent.model_validate(payload)
        except ValidationError:
            return None

    @staticmethod
    def _deduplicated_events(events: list[RunEvent]) -> tuple[RunEvent, ...]:
        """Keep one event per reported solver iteration for the monitor."""
        unique: list[RunEvent] = []
        # A staged solve restarts its iteration count in every stage, so the stage is
        # part of an iteration's identity.
        reported_iterations: set[tuple[str | None, int]] = set()
        for event in events:
            if event.event_type == "iteration" and event.iteration is not None:
                key = (event.stage, event.iteration)
                if key in reported_iterations:
                    continue
                reported_iterations.add(key)
            unique.append(event)
        return tuple(unique)

    @staticmethod
    def _with_state(record: RunRecord, state: RunState) -> RunRecord:
        return RunRecord(
            spec=record.spec,
            state=transition(record.state, state),
            created_at=record.created_at,
            updated_at=datetime.now(UTC),
            error=record.error,
        )

    @staticmethod
    def _state_event(record: RunRecord) -> RunEvent:
        return RunEvent(run_id=record.spec.run_id, event_type="state", message=record.state.value)

    def _run_dir(self, run_id: UUID) -> Path:
        directory = self._artifact_root / str(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _persist_record(self, record: RunRecord) -> None:
        path = self._run_dir(record.spec.run_id) / "run_record.json"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    def _persist_run_spec(self, spec: RunSpec) -> None:
        path = self._run_dir(spec.run_id) / "run_spec.yaml"
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
        )
        temporary.replace(path)

    def _load_record(self, run_id: UUID) -> RunRecord | None:
        record_path = self._artifact_root / str(run_id) / "run_record.json"
        if not record_path.exists():
            return None
        return RunRecord.model_validate_json(record_path.read_text(encoding="utf-8"))
