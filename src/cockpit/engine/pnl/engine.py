"""P&L computation engine — re-exports from standalone pnl_engine package.

All computation logic lives in ``pnl_engine.engine``. This module provides
backward-compatible imports for the cockpit project.
"""
from pnl_engine.engine import (  # noqa: F401
    # Private re-exports used by tests (test_invariants.py, test_engine.py,
    # test_reconciliation.py, test_validation.py) via this wrapper.
    _build_ois_matrix,
    _resolve_rate_ref,
    aggregate_to_monthly,
    compute_book2_mtm,
    compute_daily_pnl,
    compute_strategy_pnl,
    merge_results,
    run_all_shocks,
    weighted_average,
)
