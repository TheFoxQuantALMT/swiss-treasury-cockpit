"""pnl_engine — standalone P&L computation engine for treasury rate risk.

Usage::

    from pnl_engine import PnlEngine

    engine = PnlEngine(
        deals=deals_df,
        schedule=schedule_df,
        wirp=wirp_df,
        irs_stock=irs_stock_df,
        date_run=datetime(2026, 3, 26),
    )
    result = engine.run(shocks=["0", "50"])
"""

from pnl_engine.orchestrator import PnlEngine
from pnl_engine.engine import (
    compute_daily_pnl,
    aggregate_to_monthly,
    compute_strategy_pnl,
    compute_book2_mtm,
    merge_results,
    run_all_shocks,
    weighted_average,
    _month_columns,
    _resolve_rate_ref,
)
from pnl_engine.curves import CurveCache, load_daily_curves, overlay_wirp
from pnl_engine.matrices import (
    build_date_grid,
    expand_nominal_to_daily,
    build_alive_nominal_daily,
    build_alive_mask,
    build_mm_vector,
    build_accrual_days,
    build_rate_matrix,
    build_funding_matrix,
)
from pnl_engine.report import export_excel
from pnl_engine.repricing import compute_repricing_gap
from pnl_engine.eve import compute_eve, compute_eve_scenarios, compute_key_rate_durations
from pnl_engine.nmd import apply_nmd_decay, apply_deposit_beta, get_behavioral_maturity
from pnl_engine.scenarios import (
    interpolate_scenario_shifts,
    apply_scenario_to_curves,
    BCBS_SCENARIOS,
    TENOR_YEARS,
)
from pnl_engine.strategy_consolidated import (
    compute_strategy_consolidated,
    EFFECTIVE_LOW,
    EFFECTIVE_HIGH,
)

__all__ = [
    # Main entry point
    "PnlEngine",
    # Engine functions
    "compute_daily_pnl",
    "aggregate_to_monthly",
    "compute_strategy_pnl",
    "compute_book2_mtm",
    "merge_results",
    "run_all_shocks",
    "weighted_average",
    # Curves
    "CurveCache",
    "load_daily_curves",
    "overlay_wirp",
    # Matrices
    "build_date_grid",
    "expand_nominal_to_daily",
    "build_alive_nominal_daily",
    "build_alive_mask",
    "build_mm_vector",
    "build_accrual_days",
    "build_rate_matrix",
    "build_funding_matrix",
    # Report
    "export_excel",
    # Repricing
    "compute_repricing_gap",
    # EVE
    "compute_eve",
    "compute_eve_scenarios",
    "compute_key_rate_durations",
    # NMD
    "apply_nmd_decay",
    "apply_deposit_beta",
    "get_behavioral_maturity",
    # Scenarios
    "interpolate_scenario_shifts",
    "apply_scenario_to_curves",
    "BCBS_SCENARIOS",
    "TENOR_YEARS",
    # Strategy IAS consolidation (cross-book hedge effectiveness)
    "compute_strategy_consolidated",
    "EFFECTIVE_LOW",
    "EFFECTIVE_HIGH",
]
