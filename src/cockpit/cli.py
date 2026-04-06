"""CLI entry points for Swiss Treasury Cockpit.

Commands:
    cockpit fetch     — Fetch macro data (FRED, ECB, SNB, yfinance)
    cockpit compute   — Run P&L engine + scoring + alerts + portfolio snapshot
    cockpit analyze   — Generate LLM daily brief (requires Ollama)
    cockpit render    — Render HTML cockpit from available data
    cockpit run-all   — Execute all steps in sequence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, datetime
from pathlib import Path

from cockpit.config import DATA_DIR, OUTPUT_DIR


def _load_json(path: Path) -> dict | None:
    """Load a JSON file, returning None if it doesn't exist."""
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_json(data: dict, path: Path) -> None:
    """Write a dict as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")


def cmd_fetch(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Fetch macro data from FRED, ECB, SNB, yfinance."""
    from cockpit.data.manager import DataManager

    print(f"[fetch] Fetching macro data for {date}...")
    dm = DataManager()
    results = asyncio.run(dm.refresh_all_data())

    if not dry_run:
        output_path = data_dir / f"{date}_macro_snapshot.json"
        _save_json(results, output_path)
        print(f"[fetch] Saved to {output_path}")

        stale = results.get("stale", [])
        if stale:
            print(f"[fetch] Warning: stale sources: {', '.join(stale)}")
    else:
        print("[fetch] Dry run — data not saved.")


def cmd_compute(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    funding_source: str = "ois",
) -> None:
    """Run P&L engine, scoring, alerts, and portfolio snapshot."""
    from cockpit.engine.pnl.forecast import ForecastRatePnL
    from cockpit.engine.snapshot import build_portfolio_snapshot
    from cockpit.data.parsers import parse_mtd, parse_echeancier, parse_reference_table

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    # --- P&L ---
    print(f"[compute] Running P&L engine for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt,
        dateRates=date_dt,
        export=False,
        input_dir=input_dir,
        output_dir=str(output_dir),
        funding_source=funding_source,
    )
    pnl.run()

    # Save NII forecast snapshot for forecast tracking
    if pnl.pnlAllS is not None and not dry_run:
        try:
            from cockpit.engine.pnl.forecast_tracking import save_nii_forecast
            snapshot_path = save_nii_forecast(pnl.pnlAllS, date, data_dir)
            if snapshot_path:
                print(f"[compute] Saved NII forecast snapshot to {snapshot_path}")
        except Exception as e:
            print(f"[compute] Warning: could not save NII forecast snapshot: {e}")

    # Serialize P&L results to JSON
    pnl_result = {}
    if pnl.pnlAllS is not None:
        months = sorted(pnl.pnlAllS.index.get_level_values("Month").unique().tolist())
        pnl_result["months"] = [str(m) for m in months]
        pnl_result["by_currency"] = {}
        for ccy in pnl.pnlAllS.index.get_level_values("Deal currency").unique():
            ccy_data = pnl.pnlAllS.xs(ccy, level="Deal currency")
            pnl_result["by_currency"][ccy] = {}
            for shock in ccy_data.index.get_level_values("Shock").unique():
                shock_data = ccy_data.xs(shock, level="Shock")
                shock_key = f"shock_{shock}"
                if "PnL_Type" in shock_data.index.names:
                    pnl_result["by_currency"][ccy][shock_key] = {}
                    for pnl_type in shock_data.index.get_level_values("PnL_Type").unique():
                        type_data = shock_data.xs(pnl_type, level="PnL_Type")
                        pnl_result["by_currency"][ccy][shock_key][pnl_type] = (
                            type_data.groupby("Month")["PnL"].sum().tolist()
                        )
                else:
                    pnl_result["by_currency"][ccy][shock_key] = shock_data.groupby("Month")["PnL"].sum().tolist()

    # --- Portfolio Snapshot ---
    print("[compute] Building portfolio snapshot...")
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
    fx_rates = {}
    if macro_data:
        for pair, key in [("USD", "usd_chf_latest"), ("EUR", "eur_chf_latest"), ("GBP", "gbp_chf_latest")]:
            latest = macro_data.get(key, {})
            if isinstance(latest, dict) and "value" in latest:
                fx_rates[pair] = latest["value"]

    ref_table_path = Path(input_dir) / "reference_table.xlsx" if input_dir else None
    portfolio_result = {}
    if pnl.pnlData is not None and pnl.scheduleData is not None:
        import pandas as pd
        ref_table = parse_reference_table(ref_table_path) if ref_table_path and ref_table_path.exists() else pd.DataFrame(columns=["counterparty", "rating", "hqla_level", "country"])
        portfolio_result = build_portfolio_snapshot(
            echeancier=pnl.scheduleData,
            deals=pnl.pnlData,
            ref_table=ref_table,
            fx_rates=fx_rates,
            ref_date=date_dt.date(),
        )

    # --- Scoring & Alerts ---
    scores_result = {}
    if macro_data:
        print("[compute] Computing scores and alerts...")
        from cockpit.engine.scoring.scoring import compute_scores
        from cockpit.engine.alerts.alerts import check_alerts
        from cockpit.engine.comparison import compute_deltas

        scores = compute_scores(macro_data)
        scores_result = {
            ccy: {
                "composite": s.composite,
                "label": s.label,
                "driver": s.driver,
                "families": {
                    fname: {"score": f.score, "label": f.label, "confidence": f.confidence}
                    for fname, f in s.families.items()
                },
            }
            for ccy, s in scores.items()
        }

        deltas = compute_deltas(macro_data)
        alerts = check_alerts(macro_data, deltas)
        scores_result["_alerts"] = alerts
        scores_result["_deltas"] = deltas

    if not dry_run:
        if pnl_result:
            _save_json(pnl_result, data_dir / f"{date}_pnl.json")
            print(f"[compute] Saved P&L to {data_dir / f'{date}_pnl.json'}")
        if portfolio_result:
            _save_json(portfolio_result, data_dir / f"{date}_portfolio.json")
            print(f"[compute] Saved portfolio to {data_dir / f'{date}_portfolio.json'}")
        if scores_result:
            _save_json(scores_result, data_dir / f"{date}_scores.json")
            print(f"[compute] Saved scores to {data_dir / f'{date}_scores.json'}")
    else:
        print("[compute] Dry run — data not saved.")


def cmd_analyze(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    dry_run: bool = False,
) -> None:
    """Generate LLM daily brief using Ollama agents."""
    macro_path = data_dir / f"{date}_macro_snapshot.json"
    macro_data = _load_json(macro_path)
    if macro_data is None:
        print(f"[analyze] Error: {macro_path} not found. Run 'cockpit fetch' first.")
        sys.exit(1)

    scores_path = data_dir / f"{date}_scores.json"
    scores_data = _load_json(scores_path) or {}

    from cockpit.engine.comparison import compute_deltas, format_deltas_for_brief
    from cockpit.engine.alerts.alerts import check_alerts
    from cockpit.agents.analyst import _build_template, create_analyst_agent
    from cockpit.agents.reviewer import programmatic_check, create_reviewer_agent
    from cockpit.agents.reporter import generate_html_brief
    from cockpit.config import MAX_REVIEW_RETRIES

    deltas = scores_data.get("_deltas", compute_deltas(macro_data))
    alerts = scores_data.get("_alerts", check_alerts(macro_data, deltas))
    delta_table = format_deltas_for_brief(deltas)

    print(f"[analyze] Building analyst template for {date}...")
    template = _build_template(macro_data, deltas, delta_table, alerts)

    print("[analyze] Running analyst agent...")
    analyst = create_analyst_agent()
    brief_text = asyncio.run(analyst.run(template))

    print("[analyze] Running reviewer agent...")
    reviewer = create_reviewer_agent()
    reviewed = False
    for attempt in range(MAX_REVIEW_RETRIES):
        errors = programmatic_check(brief_text, macro_data)
        if not errors:
            reviewed = True
            break
        print(f"[analyze] Review attempt {attempt + 1}: {len(errors)} issues found, retrying...")
        brief_text = asyncio.run(analyst.run(template))

    brief_html = generate_html_brief(brief_text, macro_data, deltas)

    result = {
        "date": date,
        "reviewed": reviewed,
        "html": brief_html,
        "text": brief_text,
    }

    if not dry_run:
        output_path = data_dir / f"{date}_brief.json"
        _save_json(result, output_path)
        print(f"[analyze] Saved brief to {output_path}")
    else:
        print("[analyze] Dry run — brief not saved.")


def cmd_render(
    *,
    date: str,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """Render HTML cockpit from available JSON intermediates."""
    from cockpit.render.renderer import render_cockpit

    macro_data = _load_json(data_dir / f"{date}_macro_snapshot.json")
    pnl_data = _load_json(data_dir / f"{date}_pnl.json")
    portfolio_data = _load_json(data_dir / f"{date}_portfolio.json")
    scores_data = _load_json(data_dir / f"{date}_scores.json")
    brief_data = _load_json(data_dir / f"{date}_brief.json")

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
    hedge_pairs_file: str | None = None,
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

    print(f"[render-pnl] Running P&L engine for {date}...")
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
    hedge_pairs = None
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
            except Exception as e:
                print(f"[render-pnl] Warning: could not load budget: {e}")

        # Auto-discover hedge pairs file
        hp_path = Path(hedge_pairs_file) if hedge_pairs_file else None
        if hp_path is None:
            candidates = list(input_path.glob("*hedge*"))
            if candidates:
                hp_path = candidates[0]
        if hp_path and hp_path.exists():
            try:
                from cockpit.data.parsers.hedge_pairs import parse_hedge_pairs
                hedge_pairs = parse_hedge_pairs(hp_path)
                print(f"[render-pnl] Loaded hedge pairs from {hp_path}")
            except Exception as e:
                print(f"[render-pnl] Warning: could not load hedge pairs: {e}")

        # Auto-discover scenarios file
        import pandas as pd
        scenarios_def = None
        sc_candidates = [p for p in input_path.glob("*scenario*") if "custom" not in p.stem.lower()]
        if sc_candidates:
            try:
                from cockpit.data.parsers.scenarios import parse_scenarios
                scenarios_def = parse_scenarios(sc_candidates[0])
                print(f"[render-pnl] Loaded BCBS 368 scenarios from {sc_candidates[0]}")
            except Exception as e:
                print(f"[render-pnl] Warning: could not load scenarios: {e}")

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
            except Exception as e:
                print(f"[render-pnl] Warning: could not load custom scenarios: {e}")

        # Run all scenarios (BCBS + FINMA + custom)
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
            except Exception as e:
                print(f"[render-pnl] Warning: could not load NMD profiles: {e}")

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
            except Exception as e:
                print(f"[render-pnl] Warning: could not load limits: {e}")

        # Auto-discover alert thresholds
        threshold_candidates = list(input_path.glob("*threshold*")) + list(input_path.glob("*alert_config*"))
        if threshold_candidates:
            try:
                from cockpit.data.parsers.alert_thresholds import parse_alert_thresholds
                alert_thresholds = parse_alert_thresholds(threshold_candidates[0])
                print(f"[render-pnl] Loaded alert thresholds from {threshold_candidates[0]}")
            except Exception as e:
                print(f"[render-pnl] Warning: could not load alert thresholds: {e}")

        # Auto-discover liquidity schedule
        liq_candidates = list(input_path.glob("*liquidity*"))
        if liq_candidates:
            try:
                from cockpit.data.parsers.liquidity_schedule import parse_liquidity_schedule
                liquidity_schedule = parse_liquidity_schedule(liq_candidates[0])
                print(f"[render-pnl] Loaded liquidity schedule from {liq_candidates[0]} ({len(liquidity_schedule)} deals)")
            except Exception as e:
                print(f"[render-pnl] Warning: could not load liquidity schedule: {e}")

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
        hedge_pairs=hedge_pairs,
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

    print("[render-pnl] Rendering P&L dashboard...")
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


def cmd_run_all(
    *,
    date: str,
    input_dir: str | None = None,
    data_dir: Path = DATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    funding_source: str = "ois",
) -> None:
    """Execute all pipeline steps in sequence."""
    from cockpit.calendar import is_business_day

    run_date = datetime.strptime(date, "%Y-%m-%d")
    if not is_business_day(run_date):
        print(f"[run-all] WARNING: {date} is not a Swiss business day (weekend or holiday).")

    cmd_fetch(date=date, data_dir=data_dir, dry_run=dry_run)
    cmd_compute(date=date, input_dir=input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=dry_run, funding_source=funding_source)

    analyze_ok = False
    try:
        cmd_analyze(date=date, data_dir=data_dir, dry_run=dry_run)
        analyze_ok = True
    except Exception as e:
        print(f"[run-all] WARNING: Analyze step failed (Ollama may be unavailable): {e}")
        print("[run-all] Continuing without daily brief...")

    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    # Also render dedicated P&L dashboard if input_dir provided
    if input_dir:
        try:
            cmd_render_pnl(date=date, input_dir=input_dir, output_dir=output_dir, funding_source=funding_source)
        except Exception as e:
            print(f"[run-all] WARNING: P&L dashboard render failed: {e}")

    if not analyze_ok:
        print("[run-all] Completed with warnings (analyze step failed).")


def cmd_backfill(
    *,
    from_date: str,
    to_date: str,
    input_dir: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    funding_source: str = "ois",
) -> None:
    """Run render-pnl for a date range to populate KPI history and trends."""
    from datetime import timedelta

    start = datetime.strptime(from_date, "%Y-%m-%d")
    end = datetime.strptime(to_date, "%Y-%m-%d")
    current = start
    n_ok = 0
    n_fail = 0

    from cockpit.calendar import is_business_day

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        if not is_business_day(current):
            print(f"[backfill] Skipping {date_str} (not a business day)")
            current += timedelta(days=1)
            continue
        print(f"\n[backfill] === {date_str} ===")
        try:
            cmd_render_pnl(
                date=date_str,
                input_dir=input_dir,
                output_dir=output_dir,
                funding_source=funding_source,
            )
            n_ok += 1
        except Exception as e:
            print(f"[backfill] FAILED {date_str}: {e}")
            n_fail += 1
        current += timedelta(days=1)

    print(f"\n[backfill] Done: {n_ok} succeeded, {n_fail} failed")


def cmd_validate(
    *,
    input_dir: str,
) -> None:
    """Validate input Excel files against expected schemas."""
    from pathlib import Path as _Path

    input_path = _Path(input_dir)
    if not input_path.exists():
        print(f"[validate] Error: {input_path} does not exist")
        sys.exit(1)

    errors = []
    warnings = []

    # Check deals file
    deals_files = list(input_path.glob("*deals*")) + list(input_path.glob("*mtd*"))
    if not deals_files:
        errors.append("No deals/MTD file found")
    else:
        try:
            from cockpit.data.parsers import parse_deals
            deals = parse_deals(deals_files[0])
            print(f"[validate] Deals: {len(deals)} rows from {deals_files[0].name}")
            required_cols = {"Dealid", "Product", "Direction"}
            missing = required_cols - set(deals.columns)
            if missing:
                errors.append(f"Deals missing required columns: {missing}")
            # Check for unknown products
            known_products = {"IAM/LD", "BND", "FXS", "IRS", "IRS-MTM", "HCD"}
            if "Product" in deals.columns:
                unknown = set(deals["Product"].unique()) - known_products
                if unknown:
                    warnings.append(f"Unknown products in deals: {unknown}")
        except Exception as e:
            errors.append(f"Failed to parse deals: {e}")

    # Check schedule file
    schedule_files = list(input_path.glob("*echeancier*")) + list(input_path.glob("*schedule*"))
    if not schedule_files:
        errors.append("No echeancier/schedule file found")
    else:
        try:
            from cockpit.data.parsers import parse_echeancier
            schedule = parse_echeancier(schedule_files[0])
            print(f"[validate] Schedule: {len(schedule)} rows from {schedule_files[0].name}")
        except Exception as e:
            errors.append(f"Failed to parse schedule: {e}")

    # Check optional files
    for pattern, name in [
        ("*budget*", "Budget"), ("*hedge*", "Hedge pairs"),
        ("*scenario*", "Scenarios"), ("*nmd*", "NMD profiles"),
        ("*limits*", "Limits"), ("*liquidity*", "Liquidity schedule"),
        ("*wirp*", "WIRP"), ("*irs*", "IRS stock"),
    ]:
        candidates = list(input_path.glob(pattern))
        if candidates:
            print(f"[validate] {name}: found {candidates[0].name}")
        else:
            warnings.append(f"Optional file not found: {name} ({pattern})")

    # Report
    print(f"\n[validate] === Results ===")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")
    if not errors and not warnings:
        print("  All checks passed.")
    elif not errors:
        print(f"  {len(warnings)} warning(s), no errors.")
    else:
        print(f"  {len(errors)} error(s), {len(warnings)} warning(s).")
        sys.exit(1)


def cmd_what_if(
    *,
    input_dir: str,
    date: str,
    product: str,
    currency: str,
    amount: float,
    rate: float,
    direction: str = "D",
    maturity_years: float = 5.0,
    funding_source: str = "ois",
) -> None:
    """Simulate adding a hypothetical deal and show incremental NII + EVE impact."""
    from cockpit.engine.pnl.forecast import ForecastRatePnL

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    print(f"[what-if] Running base P&L for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt, dateRates=date_dt,
        export=False, input_dir=input_dir,
        funding_source=funding_source,
    )

    # Look up current OIS rate for the currency from engine curves
    ois_rate = 0.0
    if pnl.fwdOIS0 is not None and not pnl.fwdOIS0.empty:
        try:
            ois_ccy = pnl.fwdOIS0[pnl.fwdOIS0["Currency"].str.strip().str.upper() == currency.upper()]
            if not ois_ccy.empty and "Rate" in ois_ccy.columns:
                ois_rate = float(ois_ccy["Rate"].iloc[0])
            elif not ois_ccy.empty and "value" in ois_ccy.columns:
                ois_rate = float(ois_ccy["value"].iloc[0])
        except Exception:
            pass

    # Map CLI direction to what-if direction: D/S (deposit/sell = liability) → L, B (buy) → B
    wif_direction = "L" if direction.upper() in ("D", "S", "L") else "B"

    # Determine day-count convention from currency
    from pnl_engine.config import MM_BY_CURRENCY
    mm = MM_BY_CURRENCY.get(currency.upper(), 360)

    try:
        from pnl_engine.what_if import simulate_deal
        result = simulate_deal(
            notional=amount,
            client_rate=rate,
            ois_rate=ois_rate,
            maturity_years=maturity_years,
            direction=wif_direction,
            mm=mm,
        )
        print(f"\n[what-if] === Incremental Impact ===")
        print(f"  Deal: {direction} {currency} {product} {amount:,.0f} @ {rate:.4%} ({maturity_years}Y)")
        print(f"  OIS rate:     {ois_rate:.4%}")
        print(f"  Spread:       {result.get('spread_bp', 0):+.1f} bp")
        print(f"  Δ NII (12M):  {result.get('annual_nii', 0):+,.0f}")
        print(f"  Δ NII (life): {result.get('total_nii', 0):+,.0f}")
        print(f"  Δ EVE:        {result.get('eve_impact', 0):+,.0f}")
        print(f"  DV01:         {result.get('dv01_contribution', 0):,.0f}")
    except Exception as e:
        print(f"[what-if] Error: {e}")


def cmd_decision(
    *,
    action: str,
    topic: str = "",
    description: str = "",
    priority: str = "medium",
    owner: str = "",
    status: str = "",
    date: str = "",
    month: str = "",
    n: int = 20,
) -> None:
    """Record, list, or update ALCO decisions."""
    from cockpit.decisions import DecisionStore

    store = DecisionStore(DATA_DIR / "decisions")

    if action == "record":
        if not topic:
            print("[decision] Error: --topic is required for recording")
            sys.exit(1)
        dt = datetime.strptime(date, "%Y-%m-%d") if date else datetime.now()
        entry = store.record(
            topic=topic,
            description=description,
            priority=priority,
            owner=owner,
            date=dt,
        )
        print(f"[decision] Recorded: {entry['topic']} ({entry['priority']}) on {entry['date']}")

    elif action == "list":
        if month:
            decisions = store.load(year_month=month)
        else:
            decisions = store.load_recent(n=n)
        if not decisions:
            print("[decision] No decisions found.")
            return
        for d in decisions:
            status_str = f"[{d.get('status', '?')}]"
            print(f"  {d['date']}  {status_str:<10}  {d.get('priority', '?'):<8}  {d['topic']}: {d.get('description', '')[:60]}")
        print(f"\n[decision] {len(decisions)} decision(s)")

    elif action == "update":
        if not topic or not date or not status:
            print("[decision] Error: --topic, --date, and --status required for update")
            sys.exit(1)
        ok = store.update_status(date, topic, status)
        if ok:
            print(f"[decision] Updated: {topic} on {date} → {status}")
        else:
            print(f"[decision] Not found: {topic} on {date}")

    elif action == "summary":
        s = store.summary()
        print(f"[decision] Total: {s['total']}")
        for k, v in s.get("by_status", {}).items():
            print(f"  {k}: {v}")

    else:
        print(f"[decision] Unknown action: {action}. Use record, list, update, or summary.")


def cmd_export_notion(
    *,
    date: str,
    input_dir: str | None = None,
    output_dir: Path = OUTPUT_DIR,
    parent_page_id: str = "",
    funding_source: str = "ois",
) -> None:
    """Export ALCO Decision Pack to Notion."""
    from cockpit.pnl_dashboard.charts import build_pnl_dashboard_data
    from cockpit.engine.pnl.forecast import ForecastRatePnL

    date_dt = datetime.strptime(date, "%Y-%m-%d")

    print(f"[export-notion] Building dashboard data for {date}...")
    pnl = ForecastRatePnL(
        dateRun=date_dt, dateRates=date_dt,
        export=False, input_dir=input_dir,
        funding_source=funding_source,
    )
    data = build_pnl_dashboard_data(
        pnl_all=pnl.pnlAll, pnl_all_s=pnl.pnlAllS,
        date_run=date_dt, date_rates=date_dt,
        deals=pnl.pnlData, pnl_by_deal=getattr(pnl, 'pnl_by_deal', None),
    )

    decision_pack = data.get("alco_decision_pack", {})
    if not decision_pack.get("has_data"):
        print("[export-notion] No ALCO Decision Pack data to export.")
        return

    from cockpit.integrations.notion_export import build_notion_blocks, export_to_notion
    import asyncio

    blocks = build_notion_blocks(decision_pack, date)
    print(f"[export-notion] Built {len(blocks)} Notion blocks")

    if parent_page_id:
        try:
            result = asyncio.run(export_to_notion(decision_pack, date, parent_page_id))
            print(f"[export-notion] Exported to Notion: {result.get('url', 'success')}")
        except Exception as e:
            print(f"[export-notion] Error: {e}")
    else:
        print("[export-notion] No --parent-page-id provided. Blocks built but not pushed.")
        print("[export-notion] Set NOTION_TOKEN env var and provide --parent-page-id to push.")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="cockpit",
        description="Swiss Treasury Cockpit — unified dashboard pipeline",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch macro data")
    p_fetch.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_fetch.add_argument("--dry-run", action="store_true")

    # compute
    p_compute = sub.add_parser("compute", help="Run P&L + scoring + alerts + portfolio")
    p_compute.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_compute.add_argument("--input-dir", help="Path to Excel input files")
    p_compute.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                           help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_compute.add_argument("--dry-run", action="store_true")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Generate LLM daily brief")
    p_analyze.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_analyze.add_argument("--dry-run", action="store_true")

    # render
    p_render = sub.add_parser("render", help="Render HTML cockpit")
    p_render.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")

    # render-pnl
    p_render_pnl = sub.add_parser("render-pnl", help="Render dedicated P&L dashboard")
    p_render_pnl.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_render_pnl.add_argument("--input-dir", help="Path to Excel input files")
    p_render_pnl.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                              help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_render_pnl.add_argument("--budget", dest="budget_file", help="Path to budget.xlsx")
    p_render_pnl.add_argument("--hedge-pairs", dest="hedge_pairs_file", help="Path to hedge_pairs.xlsx")
    p_render_pnl.add_argument("--prev-date", help="Previous date for P&L attribution (YYYY-MM-DD)")
    p_render_pnl.add_argument("--prev-input-dir", help="Directory for previous date's Excel inputs (defaults to --input-dir)")
    p_render_pnl.add_argument("--shocks", help="Comma-separated shock list (e.g. '-200,-100,0,50,100,200,wirp') or 'extended' for full grid")
    p_render_pnl.add_argument("--format", choices=["html", "xlsx", "pdf", "all"], default="html",
                              help="Output format: html (default), xlsx, pdf, or all")
    p_render_pnl.add_argument("--custom-scenarios", dest="custom_scenarios",
                              help="Path to custom_scenarios.xlsx for user-defined stress tests")

    # backfill
    p_backfill = sub.add_parser("backfill", help="Run render-pnl for a date range")
    p_backfill.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    p_backfill.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    p_backfill.add_argument("--input-dir", help="Path to Excel input files")
    p_backfill.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # what-if
    p_whatif = sub.add_parser("what-if", help="Simulate adding a hypothetical deal")
    p_whatif.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_whatif.add_argument("--input-dir", required=True, help="Path to Excel input files")
    p_whatif.add_argument("--product", required=True, help="Product type (IAM/LD, BND, IRS)")
    p_whatif.add_argument("--currency", required=True, help="Currency (CHF, EUR, USD, GBP)")
    p_whatif.add_argument("--amount", required=True, type=float, help="Notional amount")
    p_whatif.add_argument("--rate", required=True, type=float, help="Client rate (decimal, e.g. 0.025)")
    p_whatif.add_argument("--direction", default="D", choices=["D", "L", "S", "B"], help="Direction (D=deposit, L=loan, S=swap, B=bond)")
    p_whatif.add_argument("--maturity", dest="maturity_years", type=float, default=5.0, help="Maturity in years")
    p_whatif.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # decision
    p_decision = sub.add_parser("decision", help="Record/list/update ALCO decisions")
    p_decision.add_argument("action", choices=["record", "list", "update", "summary"], help="Action to perform")
    p_decision.add_argument("--topic", default="", help="Decision topic")
    p_decision.add_argument("--description", default="", help="Decision description")
    p_decision.add_argument("--priority", choices=["critical", "high", "medium", "low"], default="medium")
    p_decision.add_argument("--owner", default="", help="Decision owner")
    p_decision.add_argument("--status", default="", help="Status for update (open/closed/deferred)")
    p_decision.add_argument("--date", default="", help="Date (YYYY-MM-DD)")
    p_decision.add_argument("--month", default="", help="Filter by YYYY-MM")
    p_decision.add_argument("-n", type=int, default=20, help="Number of recent decisions to list")

    # export-notion
    p_notion = sub.add_parser("export-notion", help="Export ALCO Decision Pack to Notion")
    p_notion.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_notion.add_argument("--input-dir", help="Path to Excel input files")
    p_notion.add_argument("--parent-page-id", default="", help="Notion parent page/database ID")
    p_notion.add_argument("--funding-source", choices=["ois", "coc"], default="ois")

    # validate
    p_validate = sub.add_parser("validate", help="Validate input Excel files")
    p_validate.add_argument("--input-dir", required=True, help="Path to Excel input files")

    # run-all
    p_all = sub.add_parser("run-all", help="Execute all steps")
    p_all.add_argument("--date", required=True, help="Date (YYYY-MM-DD)")
    p_all.add_argument("--input-dir", help="Path to Excel input files")
    p_all.add_argument("--funding-source", choices=["ois", "coc"], default="ois",
                       help="Funding rate source: OIS curve (default) or deal-level CocRate")
    p_all.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    data_dir = DATA_DIR
    output_dir = OUTPUT_DIR

    if args.command == "fetch":
        cmd_fetch(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "compute":
        cmd_compute(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
    elif args.command == "analyze":
        cmd_analyze(date=args.date, data_dir=data_dir, dry_run=args.dry_run)
    elif args.command == "render":
        cmd_render(date=args.date, data_dir=data_dir, output_dir=output_dir)
    elif args.command == "render-pnl":
        cmd_render_pnl(date=args.date, input_dir=args.input_dir, output_dir=output_dir, funding_source=args.funding_source, budget_file=args.budget_file, hedge_pairs_file=args.hedge_pairs_file, prev_date=args.prev_date, prev_input_dir=getattr(args, 'prev_input_dir', None), shocks=getattr(args, 'shocks', None), format=getattr(args, 'format', 'html'), custom_scenarios=getattr(args, 'custom_scenarios', None))
    elif args.command == "backfill":
        cmd_backfill(from_date=args.from_date, to_date=args.to_date, input_dir=args.input_dir, output_dir=output_dir, funding_source=args.funding_source)
    elif args.command == "what-if":
        cmd_what_if(input_dir=args.input_dir, date=args.date, product=args.product, currency=args.currency, amount=args.amount, rate=args.rate, direction=args.direction, maturity_years=args.maturity_years, funding_source=args.funding_source)
    elif args.command == "decision":
        cmd_decision(action=args.action, topic=args.topic, description=args.description, priority=args.priority, owner=args.owner, status=args.status, date=args.date, month=args.month, n=args.n)
    elif args.command == "export-notion":
        cmd_export_notion(date=args.date, input_dir=getattr(args, 'input_dir', None), parent_page_id=args.parent_page_id, funding_source=args.funding_source)
    elif args.command == "validate":
        cmd_validate(input_dir=args.input_dir)
    elif args.command == "run-all":
        cmd_run_all(date=args.date, input_dir=args.input_dir, data_dir=data_dir, output_dir=output_dir, dry_run=args.dry_run, funding_source=args.funding_source)
