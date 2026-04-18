"""WASP preflight: verify the bank's market-data library works before any P&L run.

Run this as the FIRST step of every production pipeline. If it exits non-zero,
abort the day — do not try to compute P&L. Failure reasons go to stderr;
success prints a short summary to stdout.

Usage:
    python scripts/wasp_preflight.py --date 2026-04-14

Exit codes:
    0 = OK, safe to run the daily pipeline
    1 = WASP unreachable or a required call failed; operations must investigate

The script touches the same WASP entry points that the engine uses, so a green
preflight means every part of the pipeline has a fighting chance.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--date",
        required=True,
        help="Calc date in YYYY-MM-DD (same as the daily --date flag)",
    )
    p.add_argument(
        "--currency",
        default="CHF",
        help="Probe currency for curve / carry checks (default: CHF)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true", help="Show DEBUG logs during probes",
    )
    return p.parse_args()


def _fail(msg: str) -> None:
    print(f"WASP PREFLIGHT FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        calc_date = datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError as exc:
        _fail(f"bad --date {args.date!r}: {exc}")

    currency = args.currency.upper()

    # 1. Import — fails if the WASP binaries are unreachable.
    try:
        from pnl_engine import wasptools as wt
    except Exception as exc:
        _fail(f"cannot import wasptools ({type(exc).__name__}: {exc})")

    # 2. Curve load — exercises LoadMarketRamp + dailyFwdRate.
    try:
        from pnl_engine.curves import load_daily_curves
        ois_indices = ["CHFSON", "EUREST", "USSOFR", "GBPOIS"]
        curves = load_daily_curves(date=calc_date, indices=ois_indices, shock="0")
    except Exception as exc:
        _fail(f"load_daily_curves failed ({type(exc).__name__}: {exc})")

    missing = [i for i in ois_indices if i not in set(curves["Indice"].unique())]
    if missing:
        _fail(f"curves missing indices: {missing}")

    if curves["value"].isna().all():
        _fail("all curve values are NaN — market data is broken")

    # 3. Carry compounded — exercises the MESA ALMT ramp (separate from AGG).
    try:
        from pnl_engine.curves import load_carry_compounded
        month_start = calc_date.replace(day=1)
        cc = load_carry_compounded(month_start, calc_date, currency)
    except Exception as exc:
        _fail(f"load_carry_compounded failed ({type(exc).__name__}: {exc})")

    # Success banner — log to stdout so the daily pipeline captures it.
    print(
        "WASP PREFLIGHT OK | "
        f"calcDate={calc_date:%Y-%m-%d} "
        f"waspVersion={getattr(wt, 'WASP_VERSION', '?')} "
        f"indices={len(ois_indices)} "
        f"rows={len(curves)} "
        f"{currency}_carry={cc:.6f}"
    )


if __name__ == "__main__":
    main()
