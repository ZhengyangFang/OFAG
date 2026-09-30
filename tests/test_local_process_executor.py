"""Getting a result back out of a child process, including a large one."""

import pytest

from ofag.core.constants import QuantityType
from ofag.core.schemas import (
    ArtifactManifest,
    CoordinateConvention,
    DatasetSpec,
    RunResult,
    RunSpec,
)
from ofag.execution.local_process import LocalProcessExecutor


def _spec() -> RunSpec:
    return RunSpec(
        plugin_id="test.executor",
        engine="ofag",
        dataset=DatasetSpec(
            name="executor",
            coordinate_convention=CoordinateConvention(crs="LOCAL_CARTESIAN_METRIC"),
            physical_quantity=QuantityType.GRAVITY_ACCELERATION,
            units="mGal",
        ),
    )


def _small(spec: RunSpec) -> RunResult:
    return RunResult(run_id=spec.run_id, summary={"value": 1}, artifacts=())


def _large(spec: RunSpec) -> RunResult:
    """A result comfortably past the pipe buffer, as a real batch is."""
    return RunResult(
        run_id=spec.run_id,
        summary={f"sounding_{index}": float(index) for index in range(2_000)},
        artifacts=tuple(
            ArtifactManifest(
                artifact_type="recovered_model",
                physical_quantity=QuantityType.CONDUCTIVITY,
                units="S/m",
                source_run_id=spec.run_id,
                relative_path=f"soundings/{index:04d}/recovered_conductivity_s_m.npy",
            )
            for index in range(2_000)
        ),
    )


def _fails(spec: RunSpec) -> RunResult:
    raise ValueError("the plugin said no")


def _wait(executor: LocalProcessExecutor, handle, limit: float = 120.0) -> None:
    import time

    started = time.monotonic()
    while executor.status(handle.job_id) == "RUNNING":
        if time.monotonic() - started > limit:
            raise AssertionError("the job never reported itself finished")
        time.sleep(0.05)


class TestGettingAResultBack:
    def test_a_small_result_comes_back(self) -> None:
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _small)
        _wait(executor, handle)

        assert executor.collect(handle.job_id).summary == {"value": 1}

    def test_a_result_larger_than_the_pipe_buffer_comes_back(self) -> None:
        """Collect results larger than the process pipe buffer."""
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _large)
        _wait(executor, handle)

        result = executor.collect(handle.job_id)

        assert len(result.artifacts) == 2_000
        assert len(result.summary) == 2_000

    def test_status_reports_finished_while_the_child_is_still_alive(self) -> None:
        """Which is the point: with a large result those two are different things, and asking
        the process rather than the queue conflates them."""
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _large)
        _wait(executor, handle)

        assert executor.status(handle.job_id) == "COMPLETED"
        assert executor.collect(handle.job_id).run_id == spec.run_id

    def test_status_can_be_asked_many_times_without_losing_the_result(self) -> None:
        """It reads the queue, so a second read must not find it empty."""
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _small)
        _wait(executor, handle)
        for _ in range(5):
            assert executor.status(handle.job_id) == "COMPLETED"

        assert executor.collect(handle.job_id).summary == {"value": 1}

    def test_a_failure_comes_back_as_a_failure_and_not_as_silence(self) -> None:
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _fails)
        _wait(executor, handle)

        with pytest.raises(RuntimeError, match="the plugin said no"):
            executor.collect(handle.job_id)

    def test_a_cancelled_job_drops_anything_it_had_read(self) -> None:
        executor = LocalProcessExecutor()
        spec = _spec()
        handle = executor.submit(spec, _small)
        _wait(executor, handle)
        executor.status(handle.job_id)

        executor.cancel(handle.job_id)

        with pytest.raises(RuntimeError, match="exited without a result"):
            executor.collect(handle.job_id)
