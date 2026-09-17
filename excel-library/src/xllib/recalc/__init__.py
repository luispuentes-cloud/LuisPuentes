"""Recalculation: give a workbook cached values without asking anyone to open it.

Three Phase 0 rules need cached formula values, and openpyxl does not evaluate
formulas. `recalculate` copies the target into a temp workspace and tries
`formulas`, then LibreOffice, then Excel COM, until one of them produces
values. The input is never written to. See ADR-0004.

    with recalculate("model.xlsx") as result:
        workbook = load_workbook(result.path, data_only=True)

`RecalcFailed` means every backend was unavailable or failed — the condition
behind exit 2.
"""

from .api import (
    Availability,
    BackendAttempt,
    BackendError,
    Outcome,
    RecalcBackend,
    RecalcError,
    RecalcFailed,
    RecalcResult,
    default_backends,
    recalculate,
)
from .backends import ExcelComBackend, FormulasBackend, LibreOfficeBackend
from .cache import CacheReport, write_cached_values

__all__ = [
    "Availability",
    "BackendAttempt",
    "BackendError",
    "CacheReport",
    "ExcelComBackend",
    "FormulasBackend",
    "LibreOfficeBackend",
    "Outcome",
    "RecalcBackend",
    "RecalcError",
    "RecalcFailed",
    "RecalcResult",
    "default_backends",
    "recalculate",
    "write_cached_values",
]
