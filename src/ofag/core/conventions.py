"""The check that has to happen before an inversion, every time."""

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

__all__ = [
    "ConventionCheck",
    "ConventionResult",
    "ConventionOutcome",
    "UNVERIFIED",
    "engine_fingerprint",
    "run_checks",
]


@dataclass(frozen=True)
class ConventionResult:
    """What one check found."""

    passed: bool
    #: What was compared and what came out, in numbers.
    detail: str


@dataclass(frozen=True)
class ConventionCheck:
    """One convention, and an independent way to confirm it."""

    name: str
    #: The error this catches, in one line, and what it would look like if it were not
    #: caught.
    catches: str
    #: What the engine is measured against: closed-form arithmetic, a named second
    #: implementation, or a physical statement.
    against: str
    run: Callable[[], ConventionResult]


@dataclass(frozen=True)
class ConventionOutcome:
    """Every check a subject declares, and whether they all held."""

    #: What was checked: an inversion plugin's id, or an engine's, for an engine that a
    #: service reaches directly.
    subject: str
    fingerprint: str
    results: tuple[tuple[ConventionCheck, ConventionResult], ...] = ()
    #: Set when the plugin declares no checks at all.
    unverified_reason: str | None = None

    @property
    def passed(self) -> bool:
        return all(result.passed for _, result in self.results)

    @property
    def failures(self) -> tuple[tuple[ConventionCheck, ConventionResult], ...]:
        return tuple((check, result) for check, result in self.results if not result.passed)


#: A plugin returns this instead of checks when its conventions have not been verified
#: against anything independent.
@dataclass(frozen=True)
class _Unverified:
    def __bool__(self) -> bool:
        return False


UNVERIFIED = _Unverified()


_RESULTS: dict[tuple[str, str], ConventionOutcome] = {}


def engine_fingerprint(*packages: str) -> str:
    """A version string for the libraries a plugin's conventions depend on."""
    parts = []
    for name in packages:
        try:
            parts.append(f"{name}=={version(name)}")
        except PackageNotFoundError:
            parts.append(f"{name}==absent")
    return ";".join(parts)


def run_checks(
    subject: str,
    fingerprint: str,
    checks: tuple[ConventionCheck, ...] | _Unverified,
    *,
    use_cache: bool = True,
) -> ConventionOutcome:
    """Run one subject's convention checks, once per subject and engine version."""
    key = (subject, fingerprint)
    if use_cache and key in _RESULTS:
        return _RESULTS[key]
    if isinstance(checks, _Unverified) or not checks:
        outcome = ConventionOutcome(
            subject=subject,
            fingerprint=fingerprint,
            unverified_reason=(
                "this declares no convention checks, so nothing has confirmed that its "
                "engine's signs, axis order and array order are what the plugin assumes"
            ),
        )
        _RESULTS[key] = outcome
        return outcome
    results = []
    for check in checks:
        try:
            results.append((check, check.run()))
        except Exception as error:  # noqa: BLE001 - a check that cannot run has not passed
            results.append(
                (
                    check,
                    ConventionResult(
                        passed=False,
                        detail=f"the check itself failed: {type(error).__name__}: {error}",
                    ),
                )
            )
    outcome = ConventionOutcome(subject=subject, fingerprint=fingerprint, results=tuple(results))
    _RESULTS[key] = outcome
    return outcome


def forget() -> None:
    """Drop the cache. For tests, and for a session that has just reinstalled."""
    _RESULTS.clear()
