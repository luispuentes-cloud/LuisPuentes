"""The backend contract every recalculation engine implements.

A backend rewrites one workbook in place. It never chooses the file it works
on: `xllib.recalc.api.recalculate` stages a private copy and hands that copy
over. See ADR-0004.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = [
    "Availability",
    "BackendError",
    "RecalcBackend",
    "RecalcError",
]


class RecalcError(Exception):
    """Base class for every recalculation failure."""


class BackendError(RecalcError):
    """One backend could not recalculate the workbook it was given."""

    def __init__(self, backend: str, reason: str) -> None:
        super().__init__(f"{backend}: {reason}")
        self.backend = backend
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Availability:
    """Whether a backend can run here, and why not when it cannot.

    `reason` is empty when the backend is available and carries a
    caller-readable explanation when it is not. Availability is a static
    question — installed, on PATH, right platform — answered without starting
    an engine or touching a workbook.
    """

    backend: str
    available: bool
    reason: str = ""

    @classmethod
    def ok(cls, backend: str) -> Availability:
        return cls(backend=backend, available=True, reason="")

    @classmethod
    def unavailable(cls, backend: str, reason: str) -> Availability:
        return cls(backend=backend, available=False, reason=reason)


@runtime_checkable
class RecalcBackend(Protocol):
    """A recalculation engine.

    Implementations must:

    - report availability without side effects, and never raise from
      `available`;
    - recalculate `path` **in place**, leaving cached values readable by an
      openpyxl `data_only` load;
    - touch nothing outside `path` and its containing directory;
    - raise on failure — preferably `BackendError` — rather than returning
      after a partial or no-op recalculation.
    """

    name: str

    def available(self) -> Availability: ...

    def recalculate(self, path: Path) -> None: ...
