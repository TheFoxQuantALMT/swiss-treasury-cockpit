"""Chart data builders for the P&L dashboard.

Transforms PnlEngine output (pnlAll / pnlAllS DataFrames) into Chart.js-ready
dicts that Jinja2 templates embed as inline JSON.
"""
# Re-export the main entry point
from cockpit.pnl_dashboard.charts.orchestrator import build_pnl_dashboard_data

# Re-export constants
from cockpit.pnl_dashboard.charts.constants import (
    CURRENCY_COLORS,
    LEG_COLORS,
    PRODUCT_COLORS,
    PERIMETER_COLORS,
)

# Re-export helpers
from cockpit.pnl_dashboard.charts.helpers import (
    _safe_stacked,
    _month_labels,
    _auto_pnl_explain,
    _filter_total,
)

# Re-export all _build_* functions for backward compatibility
from cockpit.pnl_dashboard.charts.core import (
    _build_summary,
    _build_coc,
    _build_pnl_series,
    _build_sensitivity,
    _build_strategy,
    _build_book2,
    _build_curves,
)

from cockpit.pnl_dashboard.charts.risk import (
    _build_currency_mismatch,
    _build_repricing_gap,
    _build_counterparty_pnl,
    _build_pnl_alerts,
    _build_eve,
    _build_limit_utilization,
)

from cockpit.pnl_dashboard.charts.attribution import (
    _build_ftp,
    _build_liquidity,
    _build_nmd_audit,
    _build_alco,
    _build_budget,
    _build_attribution,
    _build_forecast_tracking,
)

from cockpit.pnl_dashboard.charts.profitability import (
    _build_hedge_effectiveness,
    _parse_deal_ids,
    _build_nii_at_risk,
    _build_deal_explorer,
    _build_fixed_float,
    _build_nim,
)

from cockpit.pnl_dashboard.charts.structure import (
    _build_maturity_wall,
    _build_trends,
    _build_regulatory,
)

from cockpit.pnl_dashboard.charts.scenarios import (
    _build_risk_cube,
    _build_deposit_behavior,
    _build_scenario_studio,
    _build_hedge_strategy,
)

from cockpit.pnl_dashboard.charts.monitoring import (
    _build_alco_decision_pack,
    _build_data_quality,
    _build_basis_risk,
    _build_snb_reserves,
    _build_peer_benchmark,
    _build_nmd_backtest,
)

__all__ = [
    "build_pnl_dashboard_data",
    "CURRENCY_COLORS",
    "LEG_COLORS",
    "PRODUCT_COLORS",
    "PERIMETER_COLORS",
    "_safe_stacked",
    "_month_labels",
    "_auto_pnl_explain",
    "_filter_total",
    "_build_summary",
    "_build_coc",
    "_build_pnl_series",
    "_build_sensitivity",
    "_build_strategy",
    "_build_book2",
    "_build_curves",
    "_build_currency_mismatch",
    "_build_repricing_gap",
    "_build_counterparty_pnl",
    "_build_pnl_alerts",
    "_build_eve",
    "_build_limit_utilization",
    "_build_ftp",
    "_build_liquidity",
    "_build_nmd_audit",
    "_build_alco",
    "_build_budget",
    "_build_attribution",
    "_build_forecast_tracking",
    "_build_hedge_effectiveness",
    "_parse_deal_ids",
    "_build_nii_at_risk",
    "_build_deal_explorer",
    "_build_fixed_float",
    "_build_nim",
    "_build_maturity_wall",
    "_build_trends",
    "_build_regulatory",
    "_build_risk_cube",
    "_build_deposit_behavior",
    "_build_scenario_studio",
    "_build_hedge_strategy",
    "_build_alco_decision_pack",
    "_build_data_quality",
    "_build_basis_risk",
    "_build_snb_reserves",
    "_build_peer_benchmark",
    "_build_nmd_backtest",
]
