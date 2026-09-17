"""The LibreOffice backend: headless Calc driven over UNO.

`--convert-to` alone is not enough. It round-trips the file without a
guaranteed full recalculation, so this backend starts a private headless
instance, connects over a loopback UNO socket, calls `calculateAll()`, and
stores the document.

LibreOffice is frequently absent — it is not installed on the machine this was
designed on — so the interesting behaviour of this module is how cleanly it
reports being unavailable.
"""

from __future__ import annotations

import contextlib
import importlib.util
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..backend import Availability, BackendError

__all__ = ["LibreOfficeBackend"]

_EXECUTABLES = ("soffice", "soffice.bin", "libreoffice")

_WELL_KNOWN = {
    "win32": (
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ),
    "darwin": ("/Applications/LibreOffice.app/Contents/MacOS/soffice",),
}
_WELL_KNOWN_POSIX = (
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/opt/libreoffice/program/soffice",
    "/snap/bin/libreoffice",
)

# NEVER_EXECUTE: a workbook being linted must not run code during recalculation.
_MACRO_EXEC_MODE_NEVER = 0
# NO_UPDATE: do not reach out to external workbooks while recalculating.
_UPDATE_DOC_MODE_NO_UPDATE = 0


class LibreOfficeBackend:
    """Recalculate through a private headless LibreOffice instance."""

    name = "libreoffice"

    def __init__(
        self,
        *,
        soffice: str | Path | None = None,
        startup_timeout: float = 60.0,
    ) -> None:
        self._soffice = Path(soffice) if soffice is not None else None
        self._startup_timeout = startup_timeout

    def available(self) -> Availability:
        executable = self._find_soffice()
        if executable is None:
            return Availability.unavailable(
                self.name, "LibreOffice (soffice) was not found on PATH"
            )
        if importlib.util.find_spec("uno") is None:
            return Availability.unavailable(
                self.name,
                f"found {executable} but the python-uno bridge is not importable "
                f"in this interpreter",
            )
        return Availability.ok(self.name)

    def recalculate(self, path: Path) -> None:
        executable = self._find_soffice()
        if executable is None:
            raise BackendError(self.name, "LibreOffice (soffice) was not found on PATH")
        try:
            import uno
        except ImportError as error:
            raise BackendError(
                self.name, "the python-uno bridge is not importable in this interpreter"
            ) from error

        port = _free_port()
        with _headless_instance(executable, port, path.parent, self.name) as process:
            context = _connect(uno, port, process, self._startup_timeout, self.name)
            desktop = context.ServiceManager.createInstanceWithContext(
                "com.sun.star.frame.Desktop", context
            )
            document = desktop.loadComponentFromURL(
                uno.systemPathToFileUrl(str(path)),
                "_blank",
                0,
                (
                    _property(uno, "Hidden", True),
                    _property(uno, "MacroExecutionMode", _MACRO_EXEC_MODE_NEVER),
                    _property(uno, "UpdateDocMode", _UPDATE_DOC_MODE_NO_UPDATE),
                ),
            )
            if document is None:
                raise BackendError(self.name, f"LibreOffice opened no document for {path.name}")
            try:
                document.calculateAll()
                document.store()
            finally:
                with contextlib.suppress(Exception):
                    document.close(False)
                with contextlib.suppress(Exception):
                    desktop.terminate()

    def _find_soffice(self) -> Path | None:
        if self._soffice is not None:
            return self._soffice if self._soffice.exists() else None

        for name in _EXECUTABLES:
            found = shutil.which(name)
            if found is not None:
                return Path(found)

        candidates = _WELL_KNOWN.get(sys.platform, _WELL_KNOWN_POSIX)
        return next((Path(c) for c in candidates if Path(c).exists()), None)


@contextlib.contextmanager
def _headless_instance(
    executable: Path, port: int, workspace: Path, backend: str
) -> Iterator[subprocess.Popen[bytes]]:
    """Run a private soffice instance listening on loopback, and stop it after.

    The profile lives in the recalculation workspace so this instance shares no
    state with a LibreOffice the user may already have open, and the socket is
    bound to 127.0.0.1 only. The command is a list passed straight to exec —
    never a shell string.
    """
    profile = workspace / "libreoffice-profile"
    command = [
        str(executable),
        "--headless",
        "--invisible",
        "--nologo",
        "--nodefault",
        "--norestore",
        "--nolockcheck",
        f"-env:UserInstallation={profile.resolve().as_uri()}",
        f"--accept=socket,host=127.0.0.1,port={port},tcpNoDelay=1;urp",
    ]
    try:
        process = subprocess.Popen(
            command,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise BackendError(backend, f"could not start {executable.name}: {error}") from error

    try:
        yield process
    finally:
        _stop(process)


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            process.wait(timeout=15)


def _connect(
    uno: Any,
    port: int,
    process: subprocess.Popen[bytes],
    timeout: float,
    backend: str,
) -> Any:
    """Resolve a UNO context on the instance, waiting for it to finish starting."""
    resolver = uno.getComponentContext().ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", uno.getComponentContext()
    )
    url = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise BackendError(
                backend, f"LibreOffice exited with status {process.returncode} while starting"
            )
        try:
            return resolver.resolve(url)
        except Exception as error:
            last = error
            time.sleep(0.25)
    raise BackendError(
        backend, f"LibreOffice did not accept a UNO connection within {timeout:g}s: {last}"
    )


def _property(uno: Any, name: str, value: Any) -> Any:
    argument = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    argument.Name = name
    argument.Value = value
    return argument


def _free_port() -> int:
    """Claim a loopback port from the OS and release it for soffice to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
