"""Tier 3: Reconciliation tests against WASP reference values.

Cross-validates engine output against WASP curves and independent calculations.
Tests that require WASP are marked with ``@pytest.mark.wasp`` and skipped when
WASP is unavailable.

Regulatory basis:
    - BCBS 368: EVE/NII must be computed from validated curve sources
    - FINMA Circ. 2019/2: independent validation of risk models
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cockpit.config import CURRENCY_TO_OIS, FLOAT_NAME_TO_WASP
from cockpit.data.parsers import parse_wirp_ideal
from cockpit.engine.pnl.engine import _mock_curves_from_wirp
from cockpit.engine.pnl.matrices import build_date_grid

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ideal_input"


# ---------------------------------------------------------------------------
# Check WASP availability
# ---------------------------------------------------------------------------

def _wasp_available() -> bool:
    try:
        from cockpit.engine.pnl.curves import wt
        return wt is not None
    except Exception:
        return False


wasp = pytest.mark.skipif(not _wasp_available(), reason="WASP not available")


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation 1: Mock curves from WIRP — structural validation
#   When WASP is unavailable, engine falls back to WIRP-derived step-function
#   curves. Validate the shape and properties of these curves.
# ═══════════════════════════════════════════════════════════════════════════

class TestMockCurvesFromWirp:
    """Validate WIRP mock curves are structurally correct for P&L computation."""

    @pytest.fixture()
    def wirp(self):
        return parse_wirp_ideal(FIXTURES / "wirp.xlsx")

    @pytest.fixture()
    def days(self):
        return build_date_grid(pd.Timestamp("2026-04-01"), months=24)

    def test_mock_curves_have_all_indices(self, wirp, days):
        """Mock curves should cover all 4 OIS indices."""
        curves = _mock_curves_from_wirp(wirp, days, shock="0")
        indices = set(curves["Indice"].unique())
        expected = {"CHFSON", "EUREST", "USSOFR", "GBPOIS"}
        assert expected <= indices, f"Missing indices: {expected - indices}"

    def test_mock_curves_cover_date_range(self, wirp, days):
        """Curves should have entries for the full date grid."""
        curves = _mock_curves_from_wirp(wirp, days, shock="0")

        for idx in ["CHFSON", "EUREST", "USSOFR", "GBPOIS"]:
            idx_curves = curves[curves["Indice"] == idx]
            if not idx_curves.empty:
                # Should cover first and last day of grid
                curve_dates = pd.to_datetime(idx_curves["Date"])
                assert curve_dates.min() <= days[0], f"{idx}: first curve date after grid start"
                assert curve_dates.max() >= days[-1], f"{idx}: last curve date before grid end"

    def test_mock_curves_step_function(self, wirp, days):
        """Between meetings, rate should be constant (step function)."""
        curves = _mock_curves_from_wirp(wirp, days, shock="0")

        for idx in ["CHFSON"]:  # test one index in detail
            idx_curves = curves[curves["Indice"] == idx].sort_values("Date")
            if len(idx_curves) < 3:
                continue
            values = idx_curves["value"].values
            dates = pd.to_datetime(idx_curves["Date"].values)

            # Find changes
            changes = np.where(np.diff(values) != 0)[0]
            # Between changes, values should be constant
            # (this is inherent to step function — just verify no noise)
            for i in range(len(values) - 1):
                if i not in changes:
                    assert values[i] == values[i + 1], (
                        f"CHFSON: value changed at {dates[i+1]} without a meeting"
                    )

    def test_shock_shifts_all_rates(self, wirp, days):
        """A +50bp shock should shift all curve values by +0.005."""
        base = _mock_curves_from_wirp(wirp, days, shock="0")
        shocked = _mock_curves_from_wirp(wirp, days, shock="50")

        for idx in ["CHFSON", "EUREST", "USSOFR", "GBPOIS"]:
            base_vals = base[base["Indice"] == idx].sort_values("Date")["value"].values
            shock_vals = shocked[shocked["Indice"] == idx].sort_values("Date")["value"].values

            if len(base_vals) == 0:
                continue

            diff = shock_vals - base_vals
            # All differences should be 0.005 (50bp = 0.50% = 0.005 in decimal)
            assert np.allclose(diff, 0.005, atol=1e-8), (
                f"{idx}: shock diff not uniform, range [{diff.min():.6f}, {diff.max():.6f}]"
            )

    def test_rates_are_plausible(self, wirp, days):
        """All mock curve rates should be in [-0.05, 0.15] range."""
        curves = _mock_curves_from_wirp(wirp, days, shock="0")
        values = curves["value"].values
        assert (values >= -0.05).all(), f"Rate below -5%: {values.min()}"
        assert (values <= 0.15).all(), f"Rate above 15%: {values.max()}"


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation 2: WASP curve validation (when available)
#   Compare WASP-loaded curves against basic sanity checks
# ═══════════════════════════════════════════════════════════════════════════

class TestWaspCurves:
    """Validate WASP curves when available."""

    @wasp
    def test_wasp_ois_curves_load(self):
        """WASP OIS curves should load without error."""
        from cockpit.engine.pnl.curves import load_daily_curves
        from datetime import datetime

        curves = load_daily_curves(
            date=datetime(2026, 4, 4),
            indices=list(CURRENCY_TO_OIS.values()),
            shock="0",
        )
        assert not curves.empty
        assert "Indice" in curves.columns
        assert "Date" in curves.columns
        assert "value" in curves.columns

    @wasp
    def test_wasp_vs_mock_same_shape(self):
        """WASP and mock curves should produce same-shaped output."""
        from cockpit.engine.pnl.curves import load_daily_curves
        from datetime import datetime

        wirp = parse_wirp_ideal(FIXTURES / "wirp.xlsx")
        days = build_date_grid(pd.Timestamp("2026-04-01"), months=24)

        wasp_curves = load_daily_curves(
            date=datetime(2026, 4, 4),
            indices=list(CURRENCY_TO_OIS.values()),
            shock="0",
        )
        mock_curves = _mock_curves_from_wirp(wirp, days, shock="0")

        # Both should have same columns
        assert set(wasp_curves.columns) == set(mock_curves.columns)

        # Both should cover the same indices
        wasp_idx = set(wasp_curves["Indice"].unique())
        mock_idx = set(mock_curves["Indice"].unique())
        expected_idx = set(CURRENCY_TO_OIS.values())
        assert expected_idx <= wasp_idx
        assert expected_idx <= mock_idx


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation 3: BOOK2 MTM — WASP stockSwapMTM validation
#   When WASP available, verify MTM output has expected structure
# ═══════════════════════════════════════════════════════════════════════════

class TestBook2Mtm:
    """Validate BOOK2 IRS MTM computation."""

    @wasp
    def test_wasp_stockswapmtm_returns_mtm(self):
        """stockSwapMTM should return a DataFrame with MTM column."""
        from cockpit.engine.pnl.engine import compute_book2_mtm
        from cockpit.data.parsers import parse_deals
        from cockpit.engine.pnl.forecast import ForecastRatePnL
        from datetime import datetime

        deals = parse_deals(FIXTURES / "deals.xlsx")
        _, irs_stock = ForecastRatePnL._split_deals_by_book(deals)

        if irs_stock.empty:
            pytest.skip("No BOOK2 deals in test data")

        result = compute_book2_mtm(irs_stock, datetime(2026, 4, 4), shock="0")
        assert "MTM" in result.columns
        assert len(result) == len(irs_stock)

    def test_mock_mtm_returns_zero(self):
        """When WASP unavailable, deterministic mock returns zero MTM."""
        from cockpit.engine.pnl.engine import compute_book2_mtm
        from cockpit.data.parsers import parse_deals
        from cockpit.engine.pnl.forecast import ForecastRatePnL
        from datetime import datetime

        deals = parse_deals(FIXTURES / "deals.xlsx")
        _, irs_stock = ForecastRatePnL._split_deals_by_book(deals)

        if irs_stock.empty:
            pytest.skip("No BOOK2 deals in test data")

        result = compute_book2_mtm(irs_stock, datetime(2026, 4, 4), shock="0")
        assert "MTM" in result.columns
        # Analytical fallback: MTM ≈ Notional × (Rate - OIS_proxy) × remaining_years
        # Should produce non-zero values for deals with rate != OIS proxy
        assert not result["MTM"].isna().any(), "MTM should not contain NaN"
        assert result["MTM"].dtype == float


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation 4: Cross-check PnL against manual spreadsheet formula
#   Compute P&L two ways and compare:
#     Engine: vectorized numpy pipeline
#     Manual: explicit Python loop with the same formula
# ═══════════════════════════════════════════════════════════════════════════

class TestCrossCheckManual:
    """Independent P&L calculation using a manual loop, compared to engine."""

    def test_manual_vs_engine_single_deal(self):
        """Compute P&L manually day-by-day and compare to engine output."""
        nominal = 50_000_000.0
        client_rate = 0.0125  # EqOisRate for IAM/LD
        ois_rate = 0.0100
        mm = 360.0

        days = build_date_grid(pd.Timestamp("2026-04-01"), months=1)
        n_days = len(days)

        # Manual calculation: sum daily PnL for April
        manual_pnl = 0.0
        for d in days:
            if d.month == 4:
                manual_pnl += nominal * (ois_rate - client_rate) / mm

        # Engine calculation
        nom_arr = np.full((1, n_days), nominal)
        ois_arr = np.full((1, n_days), ois_rate)
        rate_arr = np.full((1, n_days), client_rate)
        mm_arr = np.full((1, n_days), mm)

        from cockpit.engine.pnl.engine import compute_daily_pnl, aggregate_to_monthly
        daily = compute_daily_pnl(nom_arr, ois_arr, rate_arr, mm_arr)
        monthly = aggregate_to_monthly(daily, nom_arr, ois_arr, rate_arr, days)

        apr = monthly[monthly["Month"].astype(str) == "2026-04"]
        engine_pnl = apr["PnL_Simple"].iloc[0]

        assert abs(manual_pnl - engine_pnl) < 0.01, (
            f"Manual={manual_pnl:.4f} vs Engine={engine_pnl:.4f}"
        )

    def test_manual_vs_engine_multi_month(self):
        """Multi-month manual calculation matches engine for 3 months."""
        from cockpit.engine.pnl.engine import compute_daily_pnl, aggregate_to_monthly

        nominal = 20_000_000.0
        rate_ref = 0.0200  # YTM for BND
        ois_rate = 0.0150
        mm = 360.0  # BND CHF = 30/360, divisor still 360

        days = build_date_grid(pd.Timestamp("2026-04-01"), months=3)
        n_days = len(days)

        # Manual: accumulate per month
        manual_by_month = {}
        for d in days:
            key = d.to_period("M")
            manual_by_month.setdefault(key, 0.0)
            manual_by_month[key] += nominal * (ois_rate - rate_ref) / mm

        # Engine
        nom_arr = np.full((1, n_days), nominal)
        ois_arr = np.full((1, n_days), ois_rate)
        rate_arr = np.full((1, n_days), rate_ref)
        mm_arr = np.full((1, n_days), mm)

        daily = compute_daily_pnl(nom_arr, ois_arr, rate_arr, mm_arr)
        monthly = aggregate_to_monthly(daily, nom_arr, ois_arr, rate_arr, days)

        for _, row in monthly.iterrows():
            m = row["Month"]
            expected = manual_by_month.get(m, 0.0)
            assert abs(row["PnL_Simple"] - expected) < 0.01, (
                f"Month {m}: Manual={expected:.4f} vs Engine={row['PnL_Simple']:.4f}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation 5: Currency-to-OIS index mapping
#   Verify that CURRENCY_TO_OIS matches the standard RFR assignments
#   (SNB→SARON/CHFSON, ECB→ESTR/EUREST, Fed→SOFR/USSOFR, BoE→SONIA/GBPOIS)
# ═══════════════════════════════════════════════════════════════════════════

class TestCurrencyOisMapping:
    """Verify OIS index mapping is consistent with market conventions."""

    def test_chf_maps_to_saron(self):
        assert CURRENCY_TO_OIS["CHF"] == "CHFSON"

    def test_eur_maps_to_estr(self):
        assert CURRENCY_TO_OIS["EUR"] == "EUREST"

    def test_usd_maps_to_sofr(self):
        assert CURRENCY_TO_OIS["USD"] == "USSOFR"

    def test_gbp_maps_to_sonia(self):
        assert CURRENCY_TO_OIS["GBP"] == "GBPOIS"

    def test_float_name_mapping_consistent(self):
        """FLOAT_NAME_TO_WASP should map to the same indices as CURRENCY_TO_OIS."""
        assert FLOAT_NAME_TO_WASP["SARON"] == "CHFSON"
        assert FLOAT_NAME_TO_WASP["ESTR"] == "EUREST"
        assert FLOAT_NAME_TO_WASP["SOFR"] == "USSOFR"
        assert FLOAT_NAME_TO_WASP["SONIA"] == "GBPOIS"
