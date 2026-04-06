"""CLI command: export to Notion."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cockpit.config import OUTPUT_DIR


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
