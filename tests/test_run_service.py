from pathlib import Path
from uuid import UUID

from ofag.core.schemas import RunEvent, RunResult, RunState
from ofag.services.run_service import RunService
from tests.conftest import await_terminal_state, gravity_run_spec


def _persist_running_record(service: RunService, spec_run_id: UUID) -> None:
    """Leave a RUNNING record on disk the way an interrupted service would."""
    record = service._records[spec_run_id]
    for state in (RunState.QUEUED, RunState.RUNNING):
        record = service._with_state(record, state)
    service._persist_record(record)


def test_fixture_run_is_dispatched_in_a_child_process(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    record = service.create(gravity_run_spec())
    assert record.state is RunState.VALIDATED
    service.start(record.spec.run_id)
    record = await_terminal_state(service, record.spec.run_id)
    assert record.state is RunState.SUCCEEDED
    result = service.result(record.spec.run_id)
    assert result is not None
    assert result.summary["fixture"] is True
    assert result.artifacts[0].units == "mGal"

    # Progress crosses the process boundary: the child appends whole RunEvents to
    # progress.jsonl and the service ingests them while polling.
    iterations = [
        event for event in service.events(record.spec.run_id) if event.event_type == "iteration"
    ]
    assert [event.iteration for event in iterations] == [0, 1]

    reloaded = RunService(artifact_root=tmp_path / "artifacts")
    assert reloaded.get(record.spec.run_id).state is RunState.SUCCEEDED
    assert reloaded.result(record.spec.run_id) is not None


def test_event_monitor_deduplicates_repeated_iteration_reports(tmp_path: Path) -> None:
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service._records[spec.run_id] = service.create(spec)
    service._events[spec.run_id].extend(
        [
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, phi_total=10),
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, phi_total=10),
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=2, phi_total=5),
        ]
    )

    events = service.events(spec.run_id)

    assert [event.iteration for event in events if event.event_type == "iteration"] == [1, 2]


def test_staged_iterations_are_kept_apart(tmp_path: Path) -> None:
    """A staged solve restarts its iteration count, so the stage identifies it."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service._records[spec.run_id] = service.create(spec)
    service._events[spec.run_id].extend(
        [
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, stage="A01"),
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, stage="A02"),
            RunEvent(run_id=spec.run_id, event_type="iteration", iteration=1, stage="A02"),
        ]
    )

    events = service.events(spec.run_id)

    iterations = [event for event in events if event.event_type == "iteration"]
    assert [event.stage for event in iterations] == ["A01", "A02"]


def test_a_run_orphaned_by_a_service_restart_is_reported_as_failed(tmp_path: Path) -> None:
    """A RUNNING record whose child process was lost must not poll forever."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service.create(spec)
    _persist_running_record(service, spec.run_id)

    restarted = RunService(artifact_root=tmp_path / "artifacts")
    recovered = restarted.get(spec.run_id)

    assert recovered.state is RunState.FAILED
    assert recovered.error is not None
    assert "service stopped" in recovered.error


def test_an_orphaned_run_that_had_finished_is_recovered_as_succeeded(tmp_path: Path) -> None:
    """The child may have written its result before the service went away."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service.create(spec)
    _persist_running_record(service, spec.run_id)
    result = RunResult(run_id=spec.run_id, summary={"fixture": True})
    (service._run_dir(spec.run_id) / "result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    restarted = RunService(artifact_root=tmp_path / "artifacts")

    assert restarted.get(spec.run_id).state is RunState.SUCCEEDED
    assert restarted.result(spec.run_id) is not None


def test_progress_events_are_ingested_once_in_both_line_formats(tmp_path: Path) -> None:
    """The file is re-read on every poll, and older runs used a bare record."""
    service = RunService(artifact_root=tmp_path / "artifacts")
    spec = gravity_run_spec()
    service.create(spec)
    progress = service._run_dir(spec.run_id) / "progress.jsonl"
    progress.write_text(
        RunEvent(
            run_id=spec.run_id, event_type="iteration", iteration=1, phi_total=9.0
        ).model_dump_json()
        + "\n"
        # The shape written before the event channel carried whole RunEvents.
        + '{"iteration": 2, "phi_total": 4.0, "phi_data": 3.0, "phi_model": 1.0}\n',
        encoding="utf-8",
    )

    service._ingest_progress_events(spec.run_id)
    service._ingest_progress_events(spec.run_id)

    iterations = [
        event.iteration for event in service._events[spec.run_id] if event.event_type == "iteration"
    ]
    assert iterations == [1, 2]
