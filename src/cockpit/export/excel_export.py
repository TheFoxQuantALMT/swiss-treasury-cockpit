"""Excel export for the P&L dashboard data.

Exports dashboard data to a multi-sheet Excel workbook using openpyxl.
Each dashboard tab becomes a worksheet with formatted tables.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def export_dashboard_to_excel(
    dashboard_data: dict,
    output_path: Path | str,
    date_run: str = "",
) -> Path | None:
    """Export dashboard data dict to Excel workbook.

    Creates sheets for: Summary, Sensitivity, EVE, Alerts, Limits, FTP.

    Args:
        dashboard_data: Dict from build_pnl_dashboard_data().
        output_path: Output .xlsx path.
        date_run: Date string for metadata.

    Returns:
        Path to generated file, or None on failure.
    """
    output_path = Path(output_path)

    try:
        with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
            # Summary KPIs
            summary = dashboard_data.get("summary", {})
            kpis = summary.get("kpis", {})
            if kpis:
                rows = []
                for shock, data in kpis.items():
                    if isinstance(data, dict):
                        rows.append({"shock": shock, **data})
                if rows:
                    pd.DataFrame(rows).to_excel(writer, sheet_name="Summary", index=False)

            # Summary: Simple vs Compounded YTD totals
            coc_ytd = summary.get("coc_ytd")
            if coc_ytd:
                pd.DataFrame([coc_ytd]).to_excel(writer, sheet_name="PnL Simple vs Compounded", index=False)

            # Sensitivity
            sensitivity = dashboard_data.get("sensitivity", {})
            if sensitivity.get("rows"):
                pd.DataFrame(sensitivity["rows"]).to_excel(writer, sheet_name="Sensitivity", index=False)

            # EVE
            eve = dashboard_data.get("eve", {})
            if eve.get("has_data") and eve.get("by_currency"):
                rows = [{"currency": k, **v} for k, v in eve["by_currency"].items()]
                pd.DataFrame(rows).to_excel(writer, sheet_name="EVE", index=False)

            # Alerts
            alerts = dashboard_data.get("pnl_alerts", {})
            if alerts.get("alerts"):
                pd.DataFrame(alerts["alerts"]).to_excel(writer, sheet_name="Alerts", index=False)

            # Limits
            limits = dashboard_data.get("limits", {})
            if limits.get("has_data") and limits.get("limit_items"):
                pd.DataFrame(limits["limit_items"]).to_excel(writer, sheet_name="Limits", index=False)

            # CoC Decomposition (Simple & Compounded P&L)
            coc = dashboard_data.get("coc", {})
            if coc.get("has_data") and coc.get("table"):
                pd.DataFrame(coc["table"]).to_excel(writer, sheet_name="CoC", index=False)

            # CoC by currency (one sheet per shock=0 currency)
            if coc.get("has_data") and coc.get("by_currency") and coc.get("months"):
                coc_months = coc["months"]
                coc_ccy_rows = []
                for ccy, by_shock in coc["by_currency"].items():
                    shock_data = by_shock.get("shock_0", {})
                    if not shock_data:
                        continue
                    for indice, values in shock_data.items():
                        for i, m in enumerate(coc_months):
                            if i < len(values):
                                coc_ccy_rows.append({
                                    "Currency": ccy,
                                    "Measure": indice,
                                    "Month": m,
                                    "Value": values[i],
                                })
                if coc_ccy_rows:
                    pd.DataFrame(coc_ccy_rows).to_excel(writer, sheet_name="CoC by Currency", index=False)

            # FTP
            ftp = dashboard_data.get("ftp", {})
            if ftp.get("has_data") and ftp.get("by_perimeter"):
                pd.DataFrame(ftp["by_perimeter"]).to_excel(writer, sheet_name="FTP", index=False)

            # Metadata
            meta = pd.DataFrame([{"date_run": date_run, "export_type": "dashboard"}])
            meta.to_excel(writer, sheet_name="Metadata", index=False)

        return output_path
    except Exception as e:
        print(f"[excel-export] Failed: {e}")
        return None
