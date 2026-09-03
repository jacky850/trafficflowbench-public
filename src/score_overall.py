"""Stable Release 1.0 entry point for overall scoring."""
# Make the sibling task packages importable when this file is run as a script,
# so no PYTHONPATH is needed.
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))

from release.score_overall import *

if __name__ == "__main__":
    main()
