"""A small local-process executor for isolated numerical work."""

from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import Process, Queue
from queue import Empty
from typing import Any

from ofag.core.schemas import RunResult, RunSpec


@dataclass(frozen=True)
class JobHandle:
    job_id: str
    pid: int


def _worker(
    spec_data: dict[str, Any],
    run_function: Callable[[RunSpec], RunResult],
    result_queue: Any,
) -> None:
    try:
        result = run_function(RunSpec.model_validate(spec_data))
        result_queue.put({"result": result.model_dump(mode="json")})
    except Exception as error:  # sent across the process boundary as non-sensitive text
        result_queue.put({"error": f"{type(error).__name__}: {error}"})


class LocalProcessExecutor:
    """Submit picklable, validated run functions into a child process."""

    def __init__(self) -> None:
        self._jobs: dict[str, tuple[Process, Any]] = {}
        #: Messages taken off a queue before the caller asked for them, which is what
        #: unblocks the child.
        self._drained: dict[str, dict[str, Any]] = {}
        self._cancelled: set[str] = set()

    def submit(self, run_spec: RunSpec, run_function: Callable[[RunSpec], RunResult]) -> JobHandle:
        queue: Any = Queue(maxsize=1)
        process = Process(
            target=_worker,
            args=(run_spec.model_dump(mode="json"), run_function, queue),
            daemon=True,
        )
        process.start()
        job_id = str(run_spec.run_id)
        self._jobs[job_id] = (process, queue)
        assert process.pid is not None
        return JobHandle(job_id=job_id, pid=process.pid)

    def status(self, job_id: str) -> str:
        """Whether the work is finished, which is not whether the child exited."""
        if job_id in self._drained:
            return "COMPLETED"
        process, queue = self._jobs[job_id]
        try:
            self._drained[job_id] = queue.get_nowait()
        except Empty:
            return "RUNNING" if process.is_alive() else "COMPLETED"
        return "COMPLETED"

    def collect(self, job_id: str) -> RunResult:
        if job_id in self._cancelled:
            self._cancelled.remove(job_id)
            raise RuntimeError(f"job {job_id} exited without a result after cancellation")
        process, queue = self._jobs[job_id]
        message = self._drained.pop(job_id, None)
        if message is None:
            try:
                message = queue.get(timeout=30)
            except Empty as error:
                process.join(timeout=5)
                if not process.is_alive():
                    self._finish(job_id, process, queue)
                raise RuntimeError(f"job {job_id} exited without a result") from error
        # Only now, with the pipe drained, can the child finish and exit.
        process.join(timeout=30)
        if process.is_alive():
            raise TimeoutError(f"job {job_id} did not complete within 30 seconds")
        self._finish(job_id, process, queue)
        if "error" in message:
            raise RuntimeError(str(message["error"]))
        return RunResult.model_validate(message["result"])

    def cancel(self, job_id: str) -> None:
        process, queue = self._jobs[job_id]
        self._drained.pop(job_id, None)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join(timeout=5)
        if process.is_alive():
            raise TimeoutError(f"job {job_id} could not be stopped")
        self._finish(job_id, process, queue)
        self._cancelled.add(job_id)

    def _finish(self, job_id: str, process: Process, queue: Any) -> None:
        self._jobs.pop(job_id, None)
        self._drained.pop(job_id, None)
        queue.close()
        process.close()
