"""CLI command: validate input files."""

from __future__ import annotations

import sys


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
            from pnl_engine.config import VALID_PRODUCTS
            known_products = set(VALID_PRODUCTS)
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
