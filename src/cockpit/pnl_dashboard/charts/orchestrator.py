"""Orchestrator: main entry point that calls all chart data builders."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import pandas as pd

from cockpit.pnl_dashboard.charts.helpers import _safe_stacked, _auto_pnl_explain
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


def build_pnl_dashboard_data(
    pnl_all: pd.DataFrame,
    pnl_all_s: pd.DataFrame,
    ois_curves: Optional[pd.DataFrame] = None,
    wirp_curves: Optional[pd.DataFrame] = None,
    irs_stock: Optional[pd.DataFrame] = None,
    date_run: Optional[datetime] = None,
    date_rates: Optional[datetime] = None,
    # Wave 1 optional inputs
    deals: Optional[pd.DataFrame] = None,
    pnl_by_deal: Optional[pd.DataFrame] = None,
    # Wave 2 optional inputs
    budget: Optional[pd.DataFrame] = None,
    hedge_pairs: Optional[pd.DataFrame] = None,
    # Wave 3 optional inputs
    prev_pnl_all_s: Optional[pd.DataFrame] = None,
    forecast_history: Optional[pd.DataFrame] = None,
    scenarios_data: Optional[pd.DataFrame] = None,
    # Configuration
    alert_thresholds: Optional[dict] = None,
    # EVE data
    eve_results: Optional[pd.DataFrame] = None,
    eve_scenarios: Optional[pd.DataFrame] = None,
    eve_krd: Optional[pd.DataFrame] = None,
    # Limits
    limits: Optional[pd.DataFrame] = None,
    # P&L Explain
    pnl_explain: Optional[dict] = None,
    prev_pnl_by_deal: Optional[pd.DataFrame] = None,
    prev_date_run: Optional[datetime] = None,
    # Liquidity & FTP
    liquidity_schedule: Optional[pd.DataFrame] = None,
    # NMD profiles (for audit trail)
    nmd_profiles: Optional[pd.DataFrame] = None,
    # KPI history (for trends tab)
    kpi_history: Optional[pd.DataFrame] = None,
    # Echeancier (for data quality)
    echeancier: Optional[pd.DataFrame] = None,
    # Pre-computed enrichment data (from engine, needs matrices not available here)
    locked_in_nii_data: Optional[dict] = None,
    beta_sensitivity_data: Optional[dict] = None,
) -> dict:
    """Build all chart data for the P&L dashboard."""
    df = _safe_stacked(pnl_all_s)
    dr = date_rates or date_run or datetime.now()

    result = {
        # Original 7 tabs
        "summary": _build_summary(df, dr, _safe_stacked(prev_pnl_all_s) if prev_pnl_all_s is not None else None),
        "coc": _build_coc(df),
        "pnl_series": _build_pnl_series(df, dr),
        "sensitivity": _build_sensitivity(df),
        "strategy": _build_strategy(df),
        "book2": _build_book2(df, irs_stock),
        "curves": _build_curves(ois_curves, wirp_curves),
        # Wave 1
        "currency_mismatch": _build_currency_mismatch(df),
        "repricing_gap": _build_repricing_gap(df, deals, date_run),
        "counterparty_pnl": _build_counterparty_pnl(df, pnl_by_deal),
        "pnl_alerts": _build_pnl_alerts(df, alert_thresholds),
        # Wave 2
        "budget": _build_budget(df, budget),
        "hedge": _build_hedge_effectiveness(df, hedge_pairs, pnl_by_deal, scenarios_data),
        # Wave 3
        "nii_at_risk": _build_nii_at_risk(df, scenarios_data),
        "forecast_tracking": _build_forecast_tracking(forecast_history),
        "attribution": _build_attribution(
            df, prev_pnl_all_s,
            pnl_explain or _auto_pnl_explain(
                pnl_by_deal, prev_pnl_by_deal, pnl_all_s, prev_pnl_all_s,
                deals, date_run, prev_date_run,
            ),
        ),
        # EVE (Phase 2)
        "eve": _build_eve(eve_results, eve_scenarios, eve_krd, limits),
        # FTP & Liquidity
        "ftp": _build_ftp(df, deals, pnl_by_deal, date_run=date_run),
        "liquidity": _build_liquidity(liquidity_schedule, deals),
        # NMD audit trail
        "nmd_audit": _build_nmd_audit(deals, nmd_profiles),
        # Phase 1: Deal Explorer, Fixed/Float, NIM
        "deal_explorer": _build_deal_explorer(df, pnl_by_deal, deals),
        "fixed_float": _build_fixed_float(df, deals),
        "nim": _build_nim(df, deals),
        # Phase 2: Maturity Wall, Trends
        "maturity_wall": _build_maturity_wall(deals, df),
        "trends": _build_trends(kpi_history),
        # Phase 3: Risk Cube, Deposit Behavior
        "risk_cube": _build_risk_cube(df, pnl_by_deal),
        "deposit_behavior": _build_deposit_behavior(deals, nmd_profiles, df),
        # Data Quality (Phase 2)
        "data_quality": _build_data_quality(date_run, deals, echeancier, ois_curves),
        # Phase 3: Basis Risk
        "basis_risk": _build_basis_risk(deals, pnl_by_deal),
        # Phase 4: SNB Reserves
        "snb_reserves": _build_snb_reserves(deals, limits=limits),
        # NMD Backtest (placeholder)
        "nmd_backtest": _build_nmd_backtest(deals, nmd_profiles),
    }

    # Limit utilization (needs eve + nii_at_risk computed first)
    result["limits"] = _build_limit_utilization(
        df, limits, result["eve"], result["nii_at_risk"],
    )

    # Inject FTP & liquidity alerts into existing alerts tab
    extra_alerts = []
    if result["liquidity"].get("has_data"):
        liq_sum = result["liquidity"]["summary"]
        if liq_sum.get("survival_days") is not None:
            extra_alerts.append({
                "type": "liquidity_deficit",
                "severity": "critical",
                "metric": "Liquidity Survival",
                "current": liq_sum["survival_days"],
                "threshold": 0,
                "message": f"Cumulative liquidity deficit in {liq_sum['survival_days']} days",
                "recommendation": "Review funding maturities and arrange contingent liquidity",
            })
        if liq_sum.get("net_30d", 0) < 0:
            extra_alerts.append({
                "type": "liquidity_30d",
                "severity": "high",
                "metric": "30-Day Net Outflow",
                "current": round(float(liq_sum["net_30d"]), 0),
                "threshold": 0,
                "message": f"Net cash outflow of {liq_sum['net_30d']:,.0f} in next 30 days",
                "recommendation": "Secure funding to cover upcoming maturities",
            })

    if result["ftp"].get("has_data"):
        ftp_totals = result["ftp"]["totals"]
        if ftp_totals.get("alm_margin", 0) < 0:
            extra_alerts.append({
                "type": "ftp_alm_negative",
                "severity": "high",
                "metric": "ALM Margin (FTP - OIS)",
                "current": round(float(ftp_totals["alm_margin"]), 0),
                "threshold": 0,
                "message": f"ALM margin is negative ({ftp_totals['alm_margin']:,.0f}): FTP below market funding cost",
                "recommendation": "Review FTP methodology or adjust transfer pricing rates",
            })

    # IRRBB outlier test warning (missing Tier 1 capital)
    eve_warning = result["eve"].get("outlier_warning")
    if eve_warning:
        extra_alerts.append({
            "type": "irrbb_tier1_missing",
            "severity": "high",
            "metric": "IRRBB Outlier Test",
            "current": "N/A",
            "threshold": "Tier 1 capital required",
            "message": eve_warning,
            "recommendation": "Add tier1_capital row to limits.xlsx to enable BCBS 368 outlier test",
        })

    if extra_alerts:
        alerts_data = result["pnl_alerts"]
        alerts_data["alerts"].extend(extra_alerts)
        alerts_data["has_data"] = True
        for a in extra_alerts:
            sev = a.get("severity", "medium")
            if sev in alerts_data["summary"]:
                alerts_data["summary"][sev] += 1

    # Phase 4: Scenario Studio (needs nii_at_risk + eve computed)
    result["scenario_studio"] = _build_scenario_studio(
        df, scenarios_data, eve_scenarios,
        nii_at_risk=result["nii_at_risk"],
        eve_data=result["eve"],
    )

    # Phase 4: Hedge Strategy (needs sensitivity + nii_at_risk computed)
    result["hedge_strategy"] = _build_hedge_strategy(
        df, deals, hedge_pairs, pnl_by_deal,
        sensitivity=result["sensitivity"],
        nii_at_risk=result["nii_at_risk"],
    )

    # ALCO risk summary (reads from all other computed results)
    result["alco"] = _build_alco(result)

    # Phase 4: ALCO Decision Pack (reads from alco + scenario_studio)
    result["alco_decision_pack"] = _build_alco_decision_pack(result)

    # Regulatory scorecard (reads from all other computed results)
    result["regulatory"] = _build_regulatory(result)

    # Peer benchmark (reads from eve + nii_at_risk)
    result["peer_benchmark"] = _build_peer_benchmark(result)

    # --- Enrichment: wire standalone modules into existing tabs ---

    # Locked-in NII → Summary tab (pre-computed in CLI — needs engine matrices)
    if locked_in_nii_data and locked_in_nii_data.get("has_data"):
        result["summary"]["locked_in_nii"] = locked_in_nii_data

    # NMD beta sensitivity → Deposit Behavior tab (pre-computed in CLI — needs engine matrices)
    if beta_sensitivity_data and beta_sensitivity_data.get("by_currency"):
        beta_sensitivity_data["has_data"] = True
        result["deposit_behavior"]["beta_sensitivity"] = beta_sensitivity_data

    # Hedge optimizer → Hedge Strategy tab (derive DV01 from sensitivity totals)
    try:
        from pnl_engine.hedge_optimizer import recommend_hedge
        sens = result.get("sensitivity", {})
        totals_50 = sens.get("totals_50", {})
        if totals_50 and result["hedge_strategy"].get("has_data"):
            # DV01 proxy: NII change per 1bp = total_50bp_change / 50
            portfolio_dv01 = {
                ccy: sum(vals) / 50.0
                for ccy, vals in totals_50.items()
                if isinstance(vals, (list, tuple))
            }
            if portfolio_dv01:
                recs = recommend_hedge(portfolio_dv01)
                if recs.get("has_data"):
                    result["hedge_strategy"]["recommendations"] = recs.get("recommendations", [])
                    result["hedge_strategy"]["has_recommendations"] = True
    except Exception:
        pass

    # Sensitivity explain → Sensitivity tab (extract per-currency dicts)
    try:
        from pnl_engine.sensitivity_explain import explain_sensitivity_change
        sens = result.get("sensitivity", {})
        totals_50 = sens.get("totals_50", {})
        if prev_pnl_all_s is not None and totals_50:
            # Build current sensitivity dict: sum monthly values per currency
            current_sens = {
                ccy: sum(vals) for ccy, vals in totals_50.items()
                if isinstance(vals, (list, tuple))
            }
            # Build previous sensitivity from prev data
            prev_df = _safe_stacked(prev_pnl_all_s)
            prev_sens_data = _build_sensitivity(prev_df)
            prev_totals = prev_sens_data.get("totals_50", {})
            previous_sens = {
                ccy: sum(vals) for ccy, vals in prev_totals.items()
                if isinstance(vals, (list, tuple))
            }
            if current_sens and previous_sens:
                explain = explain_sensitivity_change(current_sens, previous_sens, deals)
                if explain.get("has_data"):
                    result["sensitivity"]["explain"] = explain
    except Exception:
        pass

    # Replication portfolio → NMD Audit tab (generate behavioral cashflows from NMD profiles)
    try:
        from pnl_engine.replication import build_replication_portfolio
        import numpy as np
        nmd_audit = result.get("nmd_audit", {})
        if nmd_audit.get("has_data") and nmd_profiles is not None and not nmd_profiles.empty:
            # Generate aggregate behavioral cashflows from NMD decay profiles
            # cashflow(t) = sum(nominal_i × exp(-decay_i × t))
            day_years = np.linspace(0, 10, 120)  # 10 years, monthly points
            total_cf = np.zeros_like(day_years)
            total_nominal = 0.0
            for _, prof in nmd_profiles.iterrows():
                decay = float(prof.get("decay_rate", 0.1))
                nom = float(prof.get("share", 1.0))
                total_cf += nom * np.exp(-decay * day_years)
                total_nominal += nom
            if total_nominal > 0:
                # Get actual total nominal from audit data
                actual_nominal = 0.0
                for ts in nmd_audit.get("tier_summary", []):
                    actual_nominal += ts.get("total_nominal", 0)
                if actual_nominal == 0:
                    actual_nominal = 1.0
                repl = build_replication_portfolio(total_cf, day_years, total_nominal=actual_nominal)
                if repl.get("has_data"):
                    result["nmd_audit"]["replication"] = repl
    except Exception:
        pass

    return result
