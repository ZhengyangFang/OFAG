"""Cancellable, isolated numerical tasks with GUI-thread result delivery."""

import multiprocessing as mp
from collections.abc import Callable
from queue import Empty
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication


def _execute(queue: Any, function: Callable[..., Any], args: tuple[Any, ...]) -> None:
    try:
        queue.put((True, function(*args)))
    except Exception as error:
        queue.put((False, f"{type(error).__name__}: {error}"))


class BackgroundTask(QObject):
    """One read-only computation."""

    succeeded = Signal(object)
    failed = Signal(str)
    status = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: Any = None
        self._queue: Any = None
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.cancel)

    @property
    def busy(self) -> bool:
        return self._process is not None

    def start(self, title: str, function: Callable[..., Any], *args: Any) -> None:
        if self.busy:
            return
        context = mp.get_context("spawn")
        self._queue = context.Queue()
        self._process = context.Process(target=_execute, args=(self._queue, function, args))
        try:
            self._process.start()
        except Exception as error:
            self._process = None
            self._queue.close()
            self._queue = None
            self.failed.emit(str(error))
            return
        self.busy_changed.emit(True)
        self.status.emit(title)
        self._timer.start()

    def _poll(self) -> None:
        if self._process is None:
            return
        try:
            ok, result = self._queue.get_nowait()
        except Empty:
            if self._process.is_alive():
                return
            ok, result = False, f"Worker exited without a result (code {self._process.exitcode})."
        self._finish()
        if ok:
            self.status.emit("Completed")
            self.succeeded.emit(result)
        else:
            self.status.emit("Failed")
            self.failed.emit(str(result))

    def _finish(self) -> None:
        self._timer.stop()
        process, queue = self._process, self._queue
        self._process = self._queue = None
        if process is not None:
            process.join(timeout=0.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1)
            process.close()
        if queue is not None:
            queue.close()
        self.busy_changed.emit(False)

    def cancel(self) -> None:
        if not self.busy:
            return
        self.status.emit("Cancellation requested")
        self._process.terminate()
        self._finish()
        self.status.emit("Cancelled")


def probe_sensitivity(root: Any, spec: Any) -> Any:
    from ofag.services.run_service import RunService

    return RunService(artifact_root=root).parameter_sensitivity(spec)


def interpolate_section(model: Any, geometry: Any) -> Any:
    from ofag.services.geology_service import GeologyService

    return GeologyService().section(model, geometry)
