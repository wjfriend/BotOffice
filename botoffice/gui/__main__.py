"""Entry point for `python -m botoffice.gui`.

Without this file the package cannot be run as a module, which is what both
launchers (scripts/run.sh and scripts/run.bat) call.
"""

from __future__ import annotations

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
