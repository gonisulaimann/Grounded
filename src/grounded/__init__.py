"""grounded: find dangling references in code comments. Deterministic, offline."""
from __future__ import annotations

import sys

if sys.version_info < (3, 10):  # pragma: no cover
    raise RuntimeError(
        f"Grounded requires Python 3.10 or newer (running on {sys.version.split()[0]}). "
        "Please upgrade Python or run via uvx: uvx --from grounded-lint grounded"
    )

__version__ = "0.17.0"
__all__ = ["__version__"]
