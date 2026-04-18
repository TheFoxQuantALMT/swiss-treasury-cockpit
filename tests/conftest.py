"""Project-wide pytest fixtures and markers.

Defines the ``requires_wasp`` marker used to skip tests that need WASP
(the bank's market-data library) when it is not reachable from the current
machine. Production always has WASP; dev laptops off the bank network do not.
"""
from __future__ import annotations

import pytest


def _wasp_available() -> bool:
    try:
        from pnl_engine.curves import wt
        return wt is not None
    except Exception:
        return False


requires_wasp = pytest.mark.skipif(
    not _wasp_available(), reason="WASP not available in this environment"
)
