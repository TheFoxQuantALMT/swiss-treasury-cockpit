"""Jinja2 renderer for the dedicated P&L dashboard."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _json_filter(value: object) -> str:
    """Jinja2 filter to safely embed Python objects as inline JSON."""
    return json.dumps(value, default=str)


def render_pnl_dashboard(
    *,
    data: dict,
    date_run: datetime,
    date_rates: datetime,
    output_path: Path,
) -> Path:
    """Render the P&L dashboard HTML from pre-built chart data.

    `data` must be the result of `build_pnl_dashboard_data(...)`. Callers are
    expected to build it once and reuse across HTML/Excel/PDF exports plus KPI
    snapshotting — see `cmd_render_pnl`.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=False,
    )
    env.filters["tojson_safe"] = _json_filter

    context = {
        "date_run": date_run.strftime("%Y-%m-%d"),
        "date_rates": date_rates.strftime("%Y-%m-%d"),
        # Original 7 tabs
        "summary": data["summary"],
        "coc": data["coc"],
        "pnl_series": data["pnl_series"],
        "sensitivity": data["sensitivity"],
        "strategy": data["strategy"],
        "book2": data["book2"],
        "curves": data["curves"],
        "has_coc": bool(data["coc"].get("months")),
        "has_strategy": data["strategy"].get("has_data", False),
        "has_book2": data["book2"].get("has_data", False),
        "has_curves": data["curves"].get("has_data", False),
        # ALM enhancement tabs
        "currency_mismatch": data["currency_mismatch"],
        "has_currency_mismatch": data["currency_mismatch"].get("has_data", False),
        "repricing_gap": data["repricing_gap"],
        "has_repricing_gap": data["repricing_gap"].get("has_data", False),
        "counterparty_pnl": data["counterparty_pnl"],
        "has_counterparty": data["counterparty_pnl"].get("has_data", False),
        "pnl_alerts": data["pnl_alerts"],
        "has_pnl_alerts": data["pnl_alerts"].get("has_data", False),
        "budget": data["budget"],
        "has_budget": data["budget"].get("has_data", False),
        "hedge": data["hedge"],
        "has_hedge": data["hedge"].get("has_data", False),
        "nii_at_risk": data["nii_at_risk"],
        "has_nii_at_risk": data["nii_at_risk"].get("has_data", False),
        "forecast_tracking": data["forecast_tracking"],
        "has_forecast_tracking": data["forecast_tracking"].get("has_data", False),
        "attribution": data["attribution"],
        "has_attribution": data["attribution"].get("has_data", False),
        # EVE tab
        "eve": data["eve"],
        "has_eve": data["eve"].get("has_data", False),
        # Limits
        "limits": data["limits"],
        "has_limits": data["limits"].get("has_data", False),
        # FTP & Liquidity
        "ftp": data["ftp"],
        "has_ftp": data["ftp"].get("has_data", False),
        "liquidity": data["liquidity"],
        "has_liquidity": data["liquidity"].get("has_data", False),
        # NMD audit trail
        "nmd_audit": data["nmd_audit"],
        "has_nmd_audit": data["nmd_audit"].get("has_data", False),
        # ALCO risk summary
        "alco": data["alco"],
        "has_alco": data["alco"].get("has_data", False),
        # Phase 1 tabs
        "deal_explorer": data["deal_explorer"],
        "has_deal_explorer": data["deal_explorer"].get("has_data", False),
        "fixed_float": data["fixed_float"],
        "has_fixed_float": data["fixed_float"].get("has_data", False),
        "nim": data["nim"],
        "has_nim": data["nim"].get("has_data", False),
        # Phase 2 tabs
        "maturity_wall": data["maturity_wall"],
        "has_maturity_wall": data["maturity_wall"].get("has_data", False),
        "trends": data["trends"],
        "has_trends": data["trends"].get("has_data", False),
        # Phase 3 tabs
        "regulatory": data["regulatory"],
        "has_regulatory": data["regulatory"].get("has_data", False),
        "risk_cube": data["risk_cube"],
        "has_risk_cube": data["risk_cube"].get("has_data", False),
        "deposit_behavior": data["deposit_behavior"],
        "has_deposit_behavior": data["deposit_behavior"].get("has_data", False),
        # Phase 4 tabs
        "scenario_studio": data["scenario_studio"],
        "has_scenario_studio": data["scenario_studio"].get("has_data", False),
        "hedge_strategy": data["hedge_strategy"],
        "has_hedge_strategy": data["hedge_strategy"].get("has_data", False),
        "alco_decision_pack": data["alco_decision_pack"],
        "has_alco_decision_pack": data["alco_decision_pack"].get("has_data", False),
        # Data Quality
        "data_quality": data["data_quality"],
        "has_data_quality": data["data_quality"].get("has_data", False),
        # Basis Risk
        "basis_risk": data["basis_risk"],
        "has_basis_risk": data["basis_risk"].get("has_data", False),
        # SNB Reserves
        "snb_reserves": data["snb_reserves"],
        "has_snb_reserves": data["snb_reserves"].get("has_data", False),
        # Peer Benchmark
        "peer_benchmark": data["peer_benchmark"],
        "has_peer_benchmark": data["peer_benchmark"].get("has_data", False),
        # NMD Backtest
        "nmd_backtest": data["nmd_backtest"],
        "has_nmd_backtest": data["nmd_backtest"].get("has_data", False),
    }

    template = env.get_template("pnl_dashboard.html")
    html = template.render(**context)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
