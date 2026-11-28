# node_tools.py
"""Run the V2 UI's Node tools the same way on Windows, Linux and macOS.

Version: 0.261.493
Implemented in: 0.261.493

``application/v2_ui/node_modules/esbuild/bin/esbuild`` is a JavaScript launcher on
Windows, which has to be run with ``node``. On Linux and macOS, esbuild's install
step replaces that file with the native esbuild executable, which ``node`` cannot
run. ``esbuild_command`` returns the right command prefix for the file that is
installed.
"""

from pathlib import Path


def esbuild_command(esbuild):
    """Return the command that starts ``esbuild`` (the path to ``esbuild/bin/esbuild``)."""
    path = Path(esbuild)
    with path.open("rb") as handle:
        is_script = handle.read(2) == b"#!"
    return ["node", str(path)] if is_script else [str(path)]
