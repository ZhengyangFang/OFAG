"""Explicit, validated run-state transitions."""

from ofag.core.schemas import RunState

_ALLOWED: dict[RunState, set[RunState]] = {
    RunState.DRAFT: {RunState.VALIDATED, RunState.CANCELLED},
    RunState.VALIDATED: {RunState.QUEUED, RunState.CANCELLED},
    RunState.QUEUED: {RunState.RUNNING, RunState.CANCELLED, RunState.FAILED},
    RunState.RUNNING: {
        RunState.SUCCEEDED,
        RunState.FAILED,
        RunState.CANCELLED,
        # Cut off with a usable checkpoint.
        RunState.INTERRUPTED,
    },
    RunState.INTERRUPTED: {RunState.QUEUED, RunState.CANCELLED, RunState.FAILED},
    RunState.SUCCEEDED: set(),
    RunState.FAILED: set(),
    RunState.CANCELLED: set(),
}


#: The states in which a child process may still be writing into the run's directory.
IN_FLIGHT_STATES: frozenset[RunState] = frozenset({RunState.QUEUED, RunState.RUNNING})


def transition(current: RunState, target: RunState) -> RunState:
    if target not in _ALLOWED[current]:
        raise ValueError(f"illegal run-state transition {current.value} -> {target.value}")
    return target
