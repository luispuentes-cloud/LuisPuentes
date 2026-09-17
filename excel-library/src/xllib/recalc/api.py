"""Recalculate a workbook on a private copy, never the input.

`recalculate` copies the target into a temp workspace, tries each backend in
order until one succeeds, and returns a handle to the recalculated copy. The
caller closes the handle; the workspace goes with it. The input is never
opened for writing by anything here. See ADR-0004.
"""

from __future__ import annotations

import enum
import os
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from .backend import Availability, BackendError, RecalcBackend, RecalcError
from .backends import ExcelComBackend, FormulasBackend, LibreOfficeBackend

__all__ = [
    "Availability",
    "BackendAttempt",
    "BackendError",
    "Outcome",
    "RecalcBackend",
    "RecalcError",
    "RecalcFailed",
    "RecalcResult",
    "default_backends",
    "recalculate",
]

_SAFE_NAME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


class Outcome(enum.StrEnum):
    """How one backend attempt ended."""

    SUCCEEDED = "SUCCEEDED"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class BackendAttempt:
    """One backend's turn in the chain, kept whether it ran or not.

    The chain records an attempt for every backend it consulted, so a report
    can say which engine produced the values and why the ones ahead of it did
    not.
    """

    backend: str
    outcome: Outcome
    detail: str = ""
    error: BaseException | None = None

    def __str__(self) -> str:
        summary = f"{self.backend} {self.outcome.lower()}"
        return f"{summary} ({self.detail})" if self.detail else summary


class RecalcFailed(RecalcError):
    """Every backend was unavailable or failed.

    This is the condition behind exit 2: nothing failed a rule, but the values
    some rules need could not be produced.
    """

    def __init__(self, source: Path, attempts: tuple[BackendAttempt, ...]) -> None:
        detail = "; ".join(str(attempt) for attempt in attempts) or "no backends offered"
        super().__init__(f"no recalculation backend succeeded for {source}: {detail}")
        self.source = source
        self.attempts = attempts


class RecalcResult:
    """A recalculated copy of a workbook, valid until it is closed.

    Use it as a context manager, or call `close` yourself. Cleanup is
    deterministic: the temp workspace is removed on close, not at interpreter
    exit. `path` refuses to answer once closed, so a stale path cannot be
    handed to a loader.
    """

    __slots__ = ("_attempts", "_backend", "_path", "_source", "_workspace")

    def __init__(
        self,
        *,
        source: Path,
        path: Path,
        backend: str,
        attempts: tuple[BackendAttempt, ...],
        workspace: tempfile.TemporaryDirectory[str],
    ) -> None:
        self._source = source
        self._path = path
        self._backend = backend
        self._attempts = attempts
        self._workspace: tempfile.TemporaryDirectory[str] | None = workspace

    @property
    def source(self) -> Path:
        """The untouched input."""
        return self._source

    @property
    def path(self) -> Path:
        """The recalculated copy. Raises once this result is closed."""
        if self._workspace is None:
            raise RuntimeError(
                f"the recalculated copy of {self._source} has already been discarded"
            )
        return self._path

    @property
    def backend(self) -> str:
        """Name of the backend that produced the copy."""
        return self._backend

    @property
    def attempts(self) -> tuple[BackendAttempt, ...]:
        """Every backend consulted, in order, including the one that won."""
        return self._attempts

    @property
    def closed(self) -> bool:
        return self._workspace is None

    def close(self) -> None:
        """Discard the copy and its workspace. Safe to call more than once."""
        workspace, self._workspace = self._workspace, None
        if workspace is not None:
            workspace.cleanup()

    def __enter__(self) -> RecalcResult:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        state = "closed" if self.closed else str(self._path)
        return f"RecalcResult(backend={self._backend!r}, path={state!r})"


def default_backends() -> tuple[RecalcBackend, ...]:
    """The Phase 0 chain: pure Python first, a spreadsheet application only if it must.

    `formulas` is the only backend that runs in Linux CI. Excel COM is last
    even on Windows, so that the path CI exercises is the path developers
    exercise.
    """
    return (FormulasBackend(), LibreOfficeBackend(), ExcelComBackend())


def recalculate(
    source: str | os.PathLike[str],
    *,
    backends: Iterable[RecalcBackend] | None = None,
) -> RecalcResult:
    """Recalculate `source` on a temp copy and return a handle to that copy.

    Backends are tried in order. Each one gets its own pristine copy, so a
    backend that corrupts the file before failing cannot poison the next
    attempt. Raises `RecalcFailed` when none of them succeeds, and removes the
    workspace before it does.
    """
    target = Path(source)
    if not target.exists():
        raise FileNotFoundError(f"cannot recalculate a file that does not exist: {target}")
    if not target.is_file():
        raise ValueError(f"cannot recalculate a path that is not a file: {target}")
    target = target.resolve()

    chain = tuple(backends) if backends is not None else default_backends()
    workspace = tempfile.TemporaryDirectory(prefix="xllib-recalc-", ignore_cleanup_errors=True)
    try:
        attempts: list[BackendAttempt] = []
        copy = _run_chain(target, Path(workspace.name), chain, attempts)
        if copy is None:
            raise RecalcFailed(target, tuple(attempts))
        return RecalcResult(
            source=target,
            path=copy,
            backend=attempts[-1].backend,
            attempts=tuple(attempts),
            workspace=workspace,
        )
    except BaseException:
        workspace.cleanup()
        raise


def _run_chain(
    source: Path,
    workspace: Path,
    chain: tuple[RecalcBackend, ...],
    attempts: list[BackendAttempt],
) -> Path | None:
    """Return the copy produced by the first backend that succeeds.

    Appends one attempt record per backend consulted to `attempts`.
    """
    for index, backend in enumerate(chain):
        availability = backend.available()
        if not availability.available:
            attempts.append(
                BackendAttempt(
                    backend=backend.name,
                    outcome=Outcome.UNAVAILABLE,
                    detail=availability.reason,
                )
            )
            continue

        copy = _stage_copy(source, workspace, index, backend.name)
        try:
            backend.recalculate(copy)
        except Exception as error:
            # A backend is third-party code driving a spreadsheet engine; any
            # exception it raises is a failed attempt, not a failed run.
            attempts.append(
                BackendAttempt(
                    backend=backend.name,
                    outcome=Outcome.FAILED,
                    detail=_describe(error),
                    error=error,
                )
            )
            continue

        attempts.append(BackendAttempt(backend=backend.name, outcome=Outcome.SUCCEEDED))
        return copy

    return None


def _stage_copy(source: Path, workspace: Path, index: int, backend: str) -> Path:
    """Copy `source` into a per-attempt directory, keeping its name and suffix."""
    stage = workspace / f"{index:02d}-{_slug(backend)}"
    stage.mkdir(parents=True)
    copy = stage / source.name
    shutil.copy2(source, copy)
    return copy


def _slug(backend: str) -> str:
    """Reduce a backend name to something safe to use as a directory name."""
    cleaned = "".join(char if char in _SAFE_NAME_CHARS else "_" for char in backend)
    return cleaned.strip("._-") or "backend"


def _describe(error: BaseException) -> str:
    message = str(error).strip()
    return message or type(error).__name__
