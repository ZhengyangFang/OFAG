"""Continuing a run whose process was lost."""

import json
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ofag.api.app import create_app
from ofag.core.schemas import RunRecord, RunResult, RunSpec, RunState, spec_fingerprint
from ofag.execution.state import transition
from ofag.plugins.protocol import CHECKPOINT_FILENAME, PluginContext
from ofag.services.run_service import RunService
from tests.conftest import gravity_run_spec


def _interrupted(service: RunService, spec: RunSpec) -> None:
    """Leave behind exactly what a lost child process leaves behind."""
    record = RunRecord(spec=spec, state=RunState.RUNNING)
    service._records[spec.run_id] = record
    service._persist_record(record)
    service._persist_run_spec(spec)


def _slow_result(spec: RunSpec, artifact_root: Path) -> RunResult:
    time.sleep(5)
    return RunResult(run_id=spec.run_id, summary={}, artifacts=())


def test_a_checkpoint_is_only_read_back_for_the_spec_that_wrote_it() -> None:
    """Continuing under a changed configuration would produce an unquestionable result."""
    import tempfile

    root = Path(tempfile.mkdtemp())
    context = PluginContext(root)
    spec = gravity_run_spec()

    assert context.resume_from(spec) is None

    context.checkpoint(spec, {"note": "half way"}, plugin_id="p", plugin_version="1", iteration=4)
    restored = context.resume_from(spec)
    assert restored is not None
    assert restored.iteration == 4
    assert restored.state["note"] == "half way"
    assert restored.spec_fingerprint == spec_fingerprint(spec)

    # The same run id, a different configuration: the checkpoint no longer applies.
    edited = spec.model_copy(update={"seed": spec.seed + 1})
    assert context.resume_from(edited) is None


def test_a_corrupt_checkpoint_starts_over_rather_than_refusing_to_run() -> None:
    """Starting from nothing is what would have happened before checkpoints existed."""
    import tempfile

    root = Path(tempfile.mkdtemp())
    context = PluginContext(root)
    spec = gravity_run_spec()
    context.checkpoint(spec, {}, plugin_id="p", plugin_version="1", iteration=1)
    (context.run_dir(spec.run_id) / CHECKPOINT_FILENAME).write_text("{ not json", encoding="utf-8")

    assert context.resume_from(spec) is None


def test_a_lost_run_with_a_checkpoint_is_interrupted_not_failed(tmp_path: Path) -> None:
    """Cut off is not the same as gone wrong, and the difference is hours of solving."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    _interrupted(service, spec)
    PluginContext(service.artifact_root).checkpoint(
        spec, {"model_path": "unused"}, plugin_id="p", plugin_version="1", iteration=6
    )

    reopened = RunService(artifact_root=tmp_path / "artifacts")
    listed = reopened.list_runs()

    assert [record.state for record in listed] == [RunState.INTERRUPTED]
    assert "iteration 6" in (listed[0].error or "")
    assert "resumed" in (listed[0].error or "")


def test_a_lost_run_without_a_checkpoint_is_still_failed(tmp_path: Path) -> None:
    """Nothing was saved, so there is nothing to continue; saying otherwise would mislead."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    _interrupted(service, spec)

    reopened = RunService(artifact_root=tmp_path / "artifacts")
    listed = reopened.list_runs()

    assert [record.state for record in listed] == [RunState.FAILED]
    assert "no checkpoint" in (listed[0].error or "")


def test_another_service_requests_cancellation_without_claiming_it_finished(tmp_path: Path) -> None:
    owner = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    _interrupted(owner, spec)
    directory = owner.run_dir(spec.run_id)
    (directory / "owner.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

    observer = RunService(artifact_root=owner.artifact_root)
    assert observer.get(spec.run_id).state is RunState.RUNNING
    assert observer.cancel(spec.run_id).state is RunState.RUNNING
    assert (directory / "cancel.request").is_file()

    (directory / "result.json").write_text(
        RunResult(run_id=spec.run_id, summary={}, artifacts=()).model_dump_json(),
        encoding="utf-8",
    )
    assert observer.get(spec.run_id).state is RunState.SUCCEEDED


def test_a_second_service_cancels_the_live_worker(tmp_path: Path, monkeypatch) -> None:
    import ofag.services.run_service as module

    monkeypatch.setattr(module, "execute_registered_plugin", _slow_result)
    owner = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    owner.create(spec)
    owner.start(spec.run_id)

    observer = RunService(artifact_root=owner.artifact_root)
    cancelled = observer.cancel(spec.run_id)

    assert cancelled.state is RunState.CANCELLED
    assert owner.get(spec.run_id).state is RunState.CANCELLED


def test_only_an_interrupted_run_can_be_resumed(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service.create(spec)

    with pytest.raises(ValueError, match="only an interrupted run can be resumed"):
        service.resume(spec.run_id)


def test_resuming_without_a_matching_checkpoint_is_refused(tmp_path: Path) -> None:
    """The record says interrupted but the checkpoint is gone or was for another spec."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    _interrupted(service, spec)
    PluginContext(service.artifact_root).checkpoint(
        spec, {}, plugin_id="p", plugin_version="1", iteration=2
    )
    reopened = RunService(artifact_root=tmp_path / "artifacts")
    assert reopened.list_runs()[0].state is RunState.INTERRUPTED
    (service.artifact_root / str(spec.run_id) / CHECKPOINT_FILENAME).unlink()

    with pytest.raises(ValueError, match="nothing to continue from"):
        reopened.resume(spec.run_id)


def test_the_state_machine_allows_interruption_and_a_second_attempt() -> None:
    """A run may be cut off, queued again, and cut off again."""
    assert transition(RunState.RUNNING, RunState.INTERRUPTED) is RunState.INTERRUPTED
    assert transition(RunState.INTERRUPTED, RunState.QUEUED) is RunState.QUEUED
    assert transition(RunState.INTERRUPTED, RunState.CANCELLED) is RunState.CANCELLED
    # A finished run is finished; resuming one would rewrite a published result.
    with pytest.raises(ValueError, match="illegal run-state transition"):
        transition(RunState.SUCCEEDED, RunState.INTERRUPTED)
    with pytest.raises(ValueError, match="illegal run-state transition"):
        transition(RunState.INTERRUPTED, RunState.SUCCEEDED)


def test_the_api_reports_a_checkpoint_and_refuses_to_resume_a_healthy_run(
    tmp_path: Path,
) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    _interrupted(service, spec)
    PluginContext(service.artifact_root).checkpoint(
        spec, {"model_path": "x"}, plugin_id="p", plugin_version="1", iteration=3
    )
    client = TestClient(create_app(RunService(artifact_root=tmp_path / "artifacts")))
    client.get("/runs")  # adopt the persisted record

    checkpoint = client.get(f"/runs/{spec.run_id}/checkpoint")
    assert checkpoint.status_code == 200
    assert checkpoint.json()["iteration"] == 3

    missing = client.post(f"/runs/{uuid4()}/resume")
    assert missing.status_code == 404


def test_a_run_id_is_a_uuid_in_the_checkpoint_path(tmp_path: Path) -> None:
    """Checkpoints live in the run's own directory, so two runs cannot collide."""
    context = PluginContext(tmp_path)
    first, second = gravity_run_spec(), gravity_run_spec()
    assert first.run_id != second.run_id
    context.checkpoint(first, {"which": "first"}, plugin_id="p", plugin_version="1")
    context.checkpoint(second, {"which": "second"}, plugin_id="p", plugin_version="1")

    restored_first = context.resume_from(first)
    restored_second = context.resume_from(second)
    assert restored_first is not None and restored_first.state["which"] == "first"
    assert restored_second is not None and restored_second.state["which"] == "second"
    assert isinstance(first.run_id, UUID)


def test_the_owner_probe_does_not_signal_the_process() -> None:
    """On Windows os.kill(pid, 0) is CTRL_C_EVENT, not an existence check, so probing a live
    owner sent a console Ctrl+C to its process group."""
    import subprocess
    import sys

    from ofag.services.run_service import _process_alive

    assert _process_alive(os.getpid())
    finished = subprocess.run([sys.executable, "-c", "pass"], check=True)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    assert finished.returncode == 0
    assert not _process_alive(child.pid)
    assert not _process_alive(0)
    assert not _process_alive(-1)


def test_an_orphaned_queued_run_can_be_cancelled(tmp_path: Path) -> None:
    """Queued and owned by nobody: the submit failed or the owner died before writing
    owner.json."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    record = RunRecord(spec=spec, state=RunState.QUEUED)
    service._records[spec.run_id] = record
    service._persist_record(record)
    service._persist_run_spec(spec)

    reopened = RunService(artifact_root=tmp_path / "artifacts")
    cancelled = reopened.cancel(spec.run_id)

    assert cancelled.state is RunState.CANCELLED
    reopened.delete(spec.run_id)
