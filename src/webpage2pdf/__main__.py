"""
Allow `python -m webpage2pdf` as an alternative to the installed `webpage2pdf`
script — useful when the package is on the path but its scripts are not, which
is the normal situation inside a checked-out source tree.
"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
