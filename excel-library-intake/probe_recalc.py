"""Can the linter recalculate without asking the user? Probe each backend."""
import importlib.util
import shutil
import sys

print("python", sys.version.split()[0])

# Backend 1: pure Python, the CI path.
print("formulas:", "installed" if importlib.util.find_spec("formulas") else "NOT installed")

# Backend 2: LibreOffice headless.
soffice = shutil.which("soffice") or shutil.which("soffice.exe")
print("libreoffice:", soffice or "NOT on PATH")

# Backend 3: Excel COM, the Windows path.
if importlib.util.find_spec("win32com") is None:
    print("pywin32: NOT installed -> COM unavailable")
else:
    print("pywin32: installed")
    try:
        import win32com.client as w

        app = w.Dispatch("Excel.Application")
        print("excel COM: OK, version", app.Version)
        print("excel visible default:", app.Visible)
        app.Quit()
        del app
    except Exception as exc:
        print("excel COM FAILED:", type(exc).__name__, exc)
