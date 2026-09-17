"""Phase 0 feasibility probe. Verifies the parsing substrate before design commits to it."""
import sys

print("python", sys.version.split()[0])

try:
    import openpyxl
    print("openpyxl", openpyxl.__version__)
except Exception as exc:
    print("openpyxl MISSING:", exc)

try:
    from openpyxl.formula.tokenizer import Tokenizer
    f = '=IF(SUM($I$4:$I$15)=0,"N/A - no FTE load",K4*FTE_TARGET/SUM($I$4:$I$15))'
    toks = Tokenizer(f).items
    print("tokens", len(toks))
    for t in toks:
        print("  %-22r %-10s %s" % (t.value, t.type, t.subtype))
except Exception as exc:
    print("tokenizer FAILED:", exc)

for mod in ("formulas", "pydantic", "pytest"):
    try:
        m = __import__(mod)
        print(mod, getattr(m, "__version__", "?"))
    except Exception:
        print(mod, "not installed")
