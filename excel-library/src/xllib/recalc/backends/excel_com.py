"""The Excel COM backend: last resort, Windows only.

Excel is the most faithful evaluator available and the least suitable as a
dependency, so it sits at the end of the chain even on Windows. `Visible`
defaults to True on a fresh Application object, which would flash a window at
whoever is running the linter; both `Visible` and `DisplayAlerts` are therefore
set before a workbook is opened, not after. See ADR-0004.

The instance is created with `DispatchEx`, which starts a dedicated Excel
rather than attaching to one the user already has open, and it is quit even
when recalculation fails.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..backend import Availability, BackendError

__all__ = ["ExcelComBackend"]

# Workbooks.Open(Filename, UpdateLinks, ReadOnly): 0 leaves external links alone.
_NO_LINK_UPDATE = 0
_WRITABLE = False

#: Returns an Excel Application and the callable that releases the COM apartment.
Dispatch = Callable[[], tuple[Any, Callable[[], None]]]


class ExcelComBackend:
    """Recalculate through a private, hidden Excel instance."""

    name = "excel_com"

    def __init__(self, *, dispatch: Dispatch | None = None) -> None:
        self._dispatch = dispatch if dispatch is not None else _dispatch_excel

    def available(self) -> Availability:
        if sys.platform != "win32":
            return Availability.unavailable(
                self.name, f"Excel COM requires Windows; this is {sys.platform}"
            )
        if importlib.util.find_spec("win32com") is None:
            return Availability.unavailable(
                self.name, "pywin32 is not installed, so Excel cannot be automated"
            )
        return Availability.ok(self.name)

    def recalculate(self, path: Path) -> None:
        application, release = self._dispatch()
        try:
            # Mandatory, and set before anything is opened.
            application.Visible = False
            application.DisplayAlerts = False
            application.EnableEvents = False

            book = application.Workbooks.Open(str(path), _NO_LINK_UPDATE, _WRITABLE)
            if book is None:
                raise BackendError(self.name, f"Excel opened no workbook for {path.name}")
            try:
                application.CalculateFullRebuild()
                book.Save()
            finally:
                book.Close(False)
        finally:
            _quit(application, release)


def _quit(application: Any, release: Callable[[], None]) -> None:
    """Quit Excel and release the apartment, whatever happened upstream."""
    try:
        application.Quit()
    finally:
        release()


def _dispatch_excel() -> tuple[Any, Callable[[], None]]:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        application = win32com.client.DispatchEx("Excel.Application")
    except BaseException:
        pythoncom.CoUninitialize()
        raise
    return application, pythoncom.CoUninitialize
