"""Entry point for `python -m xllib`.

The `xllib` console script is written to the interpreter's `Scripts`
directory, which is not on `PATH` on every machine that installs this
package — including the author's, where `xllib lint` is "not recognized"
while the package imports fine. An instruction a consultant cannot run is
the same as no instruction, so the documented invocation is this one, which
needs nothing beyond the interpreter that already resolves the package.
"""

from xllib.cli import main

raise SystemExit(main())
