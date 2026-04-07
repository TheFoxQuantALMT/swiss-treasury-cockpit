"""CLI command: what-if deal simulator."""

from __future__ import annotations

from datetime import datetime


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

    # Map CLI direction to what-if direction: D/S (deposit/sell = liability) -> L, B (bond) -> B
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
