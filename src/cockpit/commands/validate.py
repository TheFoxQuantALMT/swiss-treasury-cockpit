"""CLI command: validate input files."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

_STATUS_PREFIX = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


def cmd_validate(
    *,
    input_dir: str,
) -> None:
    """Validate bank-native input files against expected schemas.

    Auto-discovers the bank-native triple under ``input_dir`` (either flat or
    in a ``YYYYPP/YYYYMMDDVV/`` tree) and runs the centralised checks in
    :func:`cockpit.data.quality.build_quality_report` so the CLI matches what
    the dashboard's Data Quality tab surfaces.
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"[validate] Error: {input_path} does not exist")
        sys.exit(1)

    errors: list[str] = []
    warnings: list[str] = []
    deals = None
    schedule = None
    wirp = None
    inputs = None

    from cockpit.data.parsers import (
        discover_bank_native_input,
        parse_bank_native_deals,
        parse_bank_native_schedule,
        parse_bank_native_wirp,
    )

    try:
        inputs = discover_bank_native_input(input_path)
    except FileNotFoundError as e:
        errors.append(f"No bank-native input triple discovered: {e}")

    if inputs is not None:
        try:
            deals = parse_bank_native_deals(inputs.pnl_workbook, date_run=inputs.position_date)
            print(f"[validate] Deals: {len(deals)} rows from {inputs.pnl_workbook.name}")
            required_cols = {"Dealid", "Product", "Direction"}
            missing = required_cols - set(deals.columns)
            if missing:
                errors.append(f"Deals missing required columns: {missing}")
            from pnl_engine.config import VALID_PRODUCTS
            if "Product" in deals.columns:
                unknown = set(deals["Product"].dropna().unique()) - set(VALID_PRODUCTS)
                if unknown:
                    warnings.append(f"Unknown products in deals: {unknown}")
        except Exception as e:
            errors.append(f"Failed to parse deals: {e}")

        try:
            schedule = parse_bank_native_schedule(inputs.rate_schedule)
            print(f"[validate] Schedule: {len(schedule)} rows from {inputs.rate_schedule.name}")
        except Exception as e:
            errors.append(f"Failed to parse schedule: {e}")

        try:
            wirp = parse_bank_native_wirp(inputs.wirp)
            print(f"[validate] WIRP: {len(wirp)} rows from {inputs.wirp.name}")
        except Exception as e:
            warnings.append(f"Failed to parse WIRP: {e}")

    # Check optional aux files (presence only; parse errors surface at run time)
    discovery_root = inputs.day_dir if inputs is not None else input_path
    for pattern, name in [
        ("*budget*", "Budget"), ("*hedge*", "Hedge pairs"),
        ("*scenario*", "Scenarios"), ("*nmd*", "NMD profiles"),
        ("*limits*", "Limits"), ("*liquidity*", "Liquidity schedule"),
    ]:
        candidates = list(discovery_root.glob(pattern))
        if candidates:
            print(f"[validate] {name}: found {candidates[0].name}")
        else:
            warnings.append(f"Optional file not found: {name} ({pattern})")

    # Run the full quality report
    report = None
    if deals is not None or schedule is not None:
        try:
            from cockpit.data.quality import build_quality_report
            report = build_quality_report(
                date_run=inputs.position_date.to_pydatetime() if inputs is not None else datetime.now(),
                deals=deals,
                echeancier=schedule,
                ois_curves=None,
            )
        except Exception as e:
            warnings.append(f"Quality report failed: {e}")

    # Report
    print("\n[validate] === Results ===")
    if report is not None:
        for check in report.checks:
            prefix = _STATUS_PREFIX.get(check.status, check.status.upper())
            print(f"  [{prefix}] {check.name}: {check.value} — {check.detail}")
            if check.status == "fail":
                errors.append(f"{check.name}: {check.detail}")
            elif check.status == "warn":
                warnings.append(f"{check.name}: {check.detail}")
        if report.coverage:
            print("  Field coverage:")
            for col, pct in sorted(report.coverage.items(), key=lambda kv: kv[1]):
                print(f"    {col}: {pct}%")
        print(
            f"  Quality summary: {report.n_pass} pass, "
            f"{report.n_warn} warn, {report.n_fail} fail "
            f"(overall: {report.overall_status})"
        )

    # Surface file-discovery errors/warnings last so they stand out
    for e in errors:
        print(f"  ERROR: {e}")
    for w in warnings:
        print(f"  WARNING: {w}")

    if not errors and not warnings:
        print("  All checks passed.")
    elif not errors:
        print(f"  {len(warnings)} warning(s), no errors.")
    else:
        print(f"  {len(errors)} error(s), {len(warnings)} warning(s).")
        sys.exit(1)
