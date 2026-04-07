"""CLI commands: render cockpit and P&L dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR
from cockpit.commands._helpers import load_json


def _derive_hedge_pairs_safe(deals):
    """Derive hedge pairs from strategy_ias, returning None on failure."""
    try:
        from cockpit.data.parsers.hedge_pairs import derive_hedge_pairs
        hp = derive_hedge_pairs(deals)
        if hp is not None:
            print(f"[render-pnl] Derived {len(hp)} hedge pair(s) from Strategy IAS")
        return hp
    except Exception as e:
        print(f"[render-pnl] Warning: could not derive hedge pairs: {e}")
        return None


def cmd_render(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Render HTML cockpit from available JSON intermediates."""
    from cockpit.render.renderer import render_cockpit

    macro_data = load_json(data_dir / f"{date}_macro_snapshot.json")
    pnl_data = load_json(data_dir / f"{date}_pnl.json")
    portfolio_data = load_json(data_dir / f"{date}_portfolio.json")
    scores_data = load_json(data_dir / f"{date}_scores.json")
    brief_data = load_json(data_dir / f"{date}_brief.json")

    output_path = output_dir / f"{date}_cockpit.html"

    print(f"[render] Rendering cockpit for {date}...")
    available = []
    if macro_data:
        available.append("macro")
    if pnl_data:
        available.append("pnl")
    if portfolio_data:
        available.append("portfolio")
    if scores_data:
        available.append("scores")
    if brief_data:
        available.append("brief")
    print(f"[render] Available data: {', '.join(available) or 'none'}")

    render_cockpit(
        macro_data=macro_data,
        pnl_data=pnl_data,
        portfolio_data=portfolio_data,
        scores_data=scores_data,
        brief_data=brief_data,
        date=date,
        output_path=output_path,
    )
    print(f"[render] Output: {output_path}")


def cmd_render_pnl(
    *,
    date: str,
    input_dir: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    funding_source: str = "ois",
    budget_file: str | None = None,
    prev_date: str | None = None,
    prev_input_dir: str | None = None,
    shocks: str | None = None,
    format: str = "html",
    custom_scenarios: str | None = None,
) -> None:
    """Render dedicated P&L dashboard from Excel inputs."""
    from cockpit.engine.pnl.forecast import ForecastRatePnL
    from cockpit.pnl_dashboard.renderer import render_pnl_dashboard

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    # Configure shocks
    if shocks:
        import pnl_engine.config as pnl_cfg
        if shocks.lower() == "extended":
            pnl_cfg.SHOCKS = list(pnl_cfg.EXTENDED_SHOCKS)
        else:
            pnl_cfg.SHOCKS = [s.strip() for s in shocks.split(",")]
        print(f"[render-pnl] Using shocks: {pnl_cfg.SHOCKS}")

    print(f"[render-pnl] Step 1/4: Building P&L for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt,
        dateRates=date_dt,
        export=False,
        input_dir=input_dir,
        output_dir=str(output_dir),
        funding_source=funding_source,
    )

    # Load optional ALM inputs
    budget = None
    scenarios_data = None
    alert_thresholds = None
    prev_pnl_all_s = None
    forecast_history = None
    eve_results = None
    eve_scenarios = None
    eve_krd = None
    limits = None
    liquidity_schedule = None
    nmd_profiles = None

    _optional_loaded = 0
    _optional_warnings = 0

    if input_dir:
        input_path = Path(input_dir)
        # Auto-discover budget file
        budget_path = Path(budget_file) if budget_file else None
        if budget_path is None:
            candidates = list(input_path.glob("*budget*"))
            if candidates:
                budget_path = candidates[0]
        if budget_path and budget_path.exists():
            try:
                from cockpit.data.parsers.budget import parse_budget
                budget = parse_budget(budget_path)
                print(f"[render-pnl] Loaded budget from {budget_path}")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse budget: {e}")
                _optional_warnings += 1

        # Auto-discover scenarios file
        import pandas as pd
        scenarios_def = None
        sc_candidates = [p for p in input_path.glob("*scenario*") if "custom" not in p.stem.lower()]
        if sc_candidates:
            try:
                from cockpit.data.parsers.scenarios import parse_scenarios
                scenarios_def = parse_scenarios(sc_candidates[0])
                print(f"[render-pnl] Loaded BCBS 368 scenarios from {sc_candidates[0]}")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse scenarios: {e}")
                _optional_warnings += 1

        # Fall back to currency-specific BCBS magnitudes (Table 2)
        if scenarios_def is None:
            try:
                from cockpit.data.parsers.scenarios import get_currency_specific_scenarios
                scenarios_def = get_currency_specific_scenarios()
                print("[render-pnl] Using BCBS 368 currency-specific shock magnitudes")
            except Exception as e:
                print(f"[render-pnl] Warning: could not load default scenarios: {e}")

        # Append FINMA scenarios + SNB reversal
        if scenarios_def is not None:
            try:
                from cockpit.data.parsers.scenarios import get_finma_scenarios, get_snb_reversal_scenario
                finma = get_finma_scenarios()
                snb_rev = get_snb_reversal_scenario()
                scenarios_def = pd.concat([scenarios_def, finma, snb_rev], ignore_index=True)
                print(f"[render-pnl] Added {finma['scenario'].nunique()} FINMA + SNB reversal scenarios")
            except Exception as e:
                print(f"[render-pnl] Warning: could not add FINMA scenarios: {e}")

        # Load custom scenarios (user-defined) and merge before running
        custom_sc_path = Path(custom_scenarios) if custom_scenarios else None
        if custom_sc_path is None:
            custom_candidates = list(input_path.glob("*custom_scenario*"))
            if custom_candidates:
                custom_sc_path = custom_candidates[0]
        if custom_sc_path and custom_sc_path.exists():
            try:
                from cockpit.data.parsers.custom_scenarios import parse_custom_scenarios
                custom_sc = parse_custom_scenarios(custom_sc_path)
                if custom_sc is not None and not custom_sc.empty:
                    n_custom = custom_sc["scenario"].nunique()
                    scenarios_def = pd.concat([scenarios_def, custom_sc], ignore_index=True)
                    print(f"[render-pnl] Merged {n_custom} custom scenarios from {custom_sc_path}")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse custom scenarios: {e}")
                _optional_warnings += 1

        # Run all scenarios (BCBS + FINMA + custom)
        print("[render-pnl] Step 2/4: Running scenarios & EVE...")
        if scenarios_def is not None and pnl._engine:
            try:
                scenarios_data = pnl._engine.run_scenarios(scenarios_def)
                if scenarios_data is not None and not scenarios_data.empty:
                    print(f"[render-pnl] Computed {scenarios_data['Shock'].nunique()} scenarios")
            except Exception as e:
                print(f"[render-pnl] Warning: could not run scenarios: {e}")

        # Auto-discover NMD profiles
        nmd_candidates = list(input_path.glob("*nmd*"))
        if nmd_candidates:
            try:
                from cockpit.data.parsers.nmd_profiles import parse_nmd_profiles
                nmd_profiles = parse_nmd_profiles(nmd_candidates[0])
                # Inject into engine for EVE computation
                if pnl._engine:
                    pnl._engine._nmd_profiles = nmd_profiles
                    print(f"[render-pnl] Loaded NMD profiles from {nmd_candidates[0]} ({len(nmd_profiles)} profiles)")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse NMD profiles: {e}")
                _optional_warnings += 1

        # Run EVE computation (uses scenarios if available)
        if pnl._engine:
            try:
                eve_results = pnl._engine.run_eve(scenarios=scenarios_def)
                eve_scenarios = pnl._engine.eve_scenarios
                eve_krd = pnl._engine.eve_krd
                print(f"[render-pnl] EVE computed (total={eve_results['eve'].sum():,.0f})")
            except Exception as e:
                print(f"[render-pnl] Warning: could not compute EVE: {e}")

        # Auto-discover limits
        limits_candidates = list(input_path.glob("*limits*")) + list(input_path.glob("*limit*"))
        # Exclude alert_thresholds files
        limits_candidates = [p for p in limits_candidates if "threshold" not in p.stem.lower() and "alert" not in p.stem.lower()]
        if limits_candidates:
            try:
                from cockpit.data.parsers.limits import parse_limits
                limits = parse_limits(limits_candidates[0])
                print(f"[render-pnl] Loaded limits from {limits_candidates[0]} ({len(limits)} metrics)")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse limits: {e}")
                _optional_warnings += 1

        # Auto-discover alert thresholds
        threshold_candidates = list(input_path.glob("*threshold*")) + list(input_path.glob("*alert_config*"))
        if threshold_candidates:
            try:
                from cockpit.data.parsers.alert_thresholds import parse_alert_thresholds
                alert_thresholds = parse_alert_thresholds(threshold_candidates[0])
                print(f"[render-pnl] Loaded alert thresholds from {threshold_candidates[0]}")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse alert thresholds: {e}")
                _optional_warnings += 1

        # Auto-discover liquidity schedule
        liq_candidates = list(input_path.glob("*liquidity*"))
        if liq_candidates:
            try:
                from cockpit.data.parsers.liquidity_schedule import parse_liquidity_schedule
                liquidity_schedule = parse_liquidity_schedule(liq_candidates[0])
                print(f"[render-pnl] Loaded liquidity schedule from {liq_candidates[0]} ({len(liquidity_schedule)} deals)")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse liquidity schedule: {e}")
                _optional_warnings += 1

        # Auto-discover production plan for dynamic balance sheet
        prod_candidates = list(input_path.glob("*production_plan*")) + list(input_path.glob("*production*plan*"))
        # Deduplicate
        prod_candidates = list(dict.fromkeys(prod_candidates))
        if prod_candidates and pnl._engine:
            try:
                from cockpit.data.parsers.production_plan import parse_production_plan
                production_plans = parse_production_plan(prod_candidates[0])
                pnl._engine._production_plans = production_plans
                print(f"[render-pnl] Loaded production plan from {prod_candidates[0]} ({len(production_plans)} plans)")
                _optional_loaded += 1
            except Exception as e:
                print(f"[render-pnl] Warning: could not parse production plan: {e}")
                _optional_warnings += 1

        print(f"[render-pnl] Loaded {_optional_loaded} optional inputs, {_optional_warnings} warnings")

    # Load previous day's P&L for attribution / explain
    pnl_explain = None
    prev_input = prev_input_dir or input_dir
    if prev_date:
        try:
            prev_dt = datetime.strptime(prev_date, "%Y-%m-%d")
            prev_pnl_obj = ForecastRatePnL(
                dateRun=prev_dt, dateRates=prev_dt,
                export=False, input_dir=prev_input,
                output_dir=str(output_dir), funding_source=funding_source,
            )
            prev_pnl_all_s = prev_pnl_obj.pnlAllS
            print(f"[render-pnl] Loaded previous P&L from {prev_date}")

            # Compute full P&L explain if deal-level data available
            prev_pnl_by_deal = getattr(prev_pnl_obj, 'pnl_by_deal', None)
            curr_pnl_by_deal = getattr(pnl, 'pnl_by_deal', None)
            if curr_pnl_by_deal is not None and prev_pnl_by_deal is not None:
                from cockpit.engine.pnl.pnl_explain import compute_pnl_explain
                pnl_explain = compute_pnl_explain(
                    curr_pnl_by_deal=curr_pnl_by_deal,
                    prev_pnl_by_deal=prev_pnl_by_deal,
                    curr_pnl_all_s=pnl.pnlAllS,
                    prev_pnl_all_s=prev_pnl_all_s,
                    deals=pnl.pnlData,
                    date_run=date_dt,
                    prev_date_run=prev_dt,
                )
                if pnl_explain and pnl_explain.get("has_data"):
                    s = pnl_explain["summary"]
                    print(f"[render-pnl] P&L explain: dNII={s['delta']:+,.0f} "
                          f"(time={s['time_effect']:+,.0f}, new={s['new_deal_effect']:+,.0f}, "
                          f"matured={s['matured_deal_effect']:+,.0f}, rate={s['rate_effect']:+,.0f})")
        except Exception as e:
            print(f"[render-pnl] Warning: could not load previous P&L: {e}")

    # Load forecast history from snapshots
    snapshot_dir = DATA_DIR / "pnl_snapshots"
    if snapshot_dir.exists():
        try:
            from cockpit.engine.pnl.forecast_tracking import load_forecast_history
            forecast_history = load_forecast_history(snapshot_dir)
            if forecast_history is not None and not forecast_history.empty:
                print(f"[render-pnl] Loaded {len(forecast_history)} forecast history records")
        except Exception as e:
            print(f"[render-pnl] Warning: could not load forecast history: {e}")

    # Load KPI history for Trends tab
    kpi_history = None
    try:
        from cockpit.engine.pnl.kpi_store import load_kpi_history
        kpi_history = load_kpi_history(DATA_DIR)
        if kpi_history is not None and not kpi_history.empty:
            print(f"[render-pnl] Loaded {len(kpi_history)} KPI history records")
    except Exception as e:
        print(f"[render-pnl] Warning: could not load KPI history: {e}")

    output_path = output_dir / f"{date}_pnl_dashboard.html"

    print("[render-pnl] Step 3/4: Computing enrichment data...")
    # Compute enrichment data (locked-in NII, beta sensitivity) from engine matrices
    locked_in_nii_data = None
    beta_sensitivity_data = None
    if pnl._engine is not None:
        try:
            enrichment = pnl._engine.compute_enrichment_data()
            locked_in_nii_data = enrichment.get("locked_in_nii")
            beta_sensitivity_data = enrichment.get("beta_sensitivity")
            if locked_in_nii_data and locked_in_nii_data.get("has_data"):
                print(f"[render-pnl] Locked-in NII: {locked_in_nii_data.get('locked_pct', 0):.1f}%")
            if beta_sensitivity_data and beta_sensitivity_data.get("by_currency"):
                print(f"[render-pnl] Beta sensitivity computed for {len(beta_sensitivity_data['by_currency'])} currencies")
        except Exception as e:
            print(f"[render-pnl] Warning: enrichment computation failed: {e}")

    # Common kwargs for building dashboard data
    dashboard_kwargs = dict(
        pnl_all=pnl.pnlAll,
        pnl_all_s=pnl.pnlAllS,
        ois_curves=pnl.fwdOIS0,
        wirp_curves=pnl.fwdWIRP,
        irs_stock=pnl.irsStock,
        date_run=date_dt,
        date_rates=date_dt,
        deals=pnl.pnlData,
        pnl_by_deal=getattr(pnl, 'pnl_by_deal', None),
        budget=budget,
        hedge_pairs=_derive_hedge_pairs_safe(pnl.pnlData),
        prev_pnl_all_s=prev_pnl_all_s,
        forecast_history=forecast_history,
        scenarios_data=scenarios_data,
        alert_thresholds=alert_thresholds,
        eve_results=eve_results,
        eve_scenarios=eve_scenarios,
        eve_krd=eve_krd,
        limits=limits,
        pnl_explain=pnl_explain,
        liquidity_schedule=liquidity_schedule,
        nmd_profiles=nmd_profiles,
        kpi_history=kpi_history,
        locked_in_nii_data=locked_in_nii_data,
        beta_sensitivity_data=beta_sensitivity_data,
    )

    print("[render-pnl] Step 4/4: Rendering P&L dashboard...")
    render_pnl_dashboard(
        **dashboard_kwargs,
        output_path=output_path,
    )
    print(f"[render-pnl] Output: {output_path}")

    # Build dashboard data once for KPI saving + export
    dashboard_data = None
    try:
        from cockpit.pnl_dashboard.charts import build_pnl_dashboard_data
        dashboard_data = build_pnl_dashboard_data(**dashboard_kwargs)
    except Exception as e:
        print(f"[render-pnl] Warning: could not build dashboard data for KPI/export: {e}")

    # Save daily KPI snapshot for Trends tab
    if dashboard_data:
        try:
            from cockpit.engine.pnl.kpi_store import save_daily_kpis
            kpi_path = save_daily_kpis(dashboard_data, date, DATA_DIR)
            if kpi_path:
                print(f"[render-pnl] Saved KPI snapshot to {kpi_path}")
        except Exception as e:
            print(f"[render-pnl] Warning: could not save KPI snapshot: {e}")

    # Export to additional formats
    if format in ("xlsx", "all") and dashboard_data:
        try:
            from cockpit.export.excel_export import export_dashboard_to_excel
            xlsx_path = output_dir / f"{date}_pnl_dashboard.xlsx"
            export_dashboard_to_excel(dashboard_data, xlsx_path, date)
            print(f"[render-pnl] Excel export: {xlsx_path}")
        except Exception as e:
            print(f"[render-pnl] Warning: Excel export failed: {e}")

    if format in ("pdf", "all"):
        try:
            from cockpit.export.pdf_export import export_html_to_pdf
            pdf_path = output_dir / f"{date}_pnl_dashboard.pdf"
            export_html_to_pdf(output_path, pdf_path)
            print(f"[render-pnl] PDF export: {pdf_path}")
        except Exception as e:
            print(f"[render-pnl] Warning: PDF export failed: {e}")
