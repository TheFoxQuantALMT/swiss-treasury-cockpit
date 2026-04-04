import numpy as np
import pandas as pd
import pytest

from cockpit.engine.pnl.engine import compute_daily_pnl, aggregate_to_monthly, weighted_average, compute_strategy_pnl


def test_compute_daily_pnl_simple():
    nominal = np.array([[1_000_000.0, 1_000_000.0, 0.0]])
    ois = np.array([[0.05, 0.04, 0.04]])
    rate_ref = np.array([[0.02, 0.02, 0.02]])
    mm = np.array([[360]])
    pnl = compute_daily_pnl(nominal, ois, rate_ref, mm)
    assert pnl.shape == (1, 3)
    np.testing.assert_almost_equal(pnl[0, 0], 1_000_000 * (0.05 - 0.02) / 360, decimal=2)
    np.testing.assert_almost_equal(pnl[0, 1], 1_000_000 * (0.04 - 0.02) / 360, decimal=2)
    assert pnl[0, 2] == 0.0


def test_compute_daily_pnl_gbp_365():
    nominal = np.array([[1_000_000.0]])
    ois = np.array([[0.05]])
    rate_ref = np.array([[0.02]])
    mm = np.array([[365]])
    pnl = compute_daily_pnl(nominal, ois, rate_ref, mm)
    np.testing.assert_almost_equal(pnl[0, 0], 1_000_000 * 0.03 / 365, decimal=2)


def test_aggregate_to_monthly_pnl_sums():
    days = pd.date_range("2026-04-01", "2026-04-30")
    daily_pnl = np.full((1, 30), 100.0)
    nominal = np.full((1, 30), 1_000_000.0)
    ois = np.full((1, 30), 0.05)
    rate = np.full((1, 30), 0.02)
    result = aggregate_to_monthly(daily_pnl, nominal, ois, rate, days)
    assert result["PnL"].iloc[0] == 3000.0


def test_aggregate_to_monthly_rate_wavg():
    days = pd.date_range("2026-04-01", "2026-04-02")
    daily_pnl = np.array([[100.0, 200.0]])
    nominal = np.array([[1_000_000.0, 2_000_000.0]])
    ois = np.array([[0.04, 0.06]])
    rate = np.array([[0.02, 0.02]])
    result = aggregate_to_monthly(daily_pnl, nominal, ois, rate, days)
    np.testing.assert_almost_equal(result["OISfwd"].iloc[0], 0.05333, decimal=4)


def test_weighted_average():
    df = pd.DataFrame({
        "group": ["A", "A", "B"],
        "rate": [0.05, 0.03, 0.04],
        "nominal": [2_000_000.0, 1_000_000.0, 5_000_000.0],
    })
    result = weighted_average(df, ["rate"], "nominal", "group")
    np.testing.assert_almost_equal(result.loc["A", "rate"], 0.04333, decimal=4)
    np.testing.assert_almost_equal(result.loc["B", "rate"], 0.04, decimal=4)


def test_strategy_pivot_builds_four_legs():
    """Strategy with IAM/LD + HCD should produce IAM/LD-NHCD + IAM/LD-HCD legs.
    No BND → no BND legs (cond_col guard)."""
    monthly = pd.DataFrame({
        "Strategy IAS": ["FV001", "FV001", "FV001"],
        "Product": ["IAM/LD", "HCD", "IRS"],
        "Currency": ["CHF", "CHF", "CHF"],
        "Direction": ["L", "L", "L"],
        "Month": [pd.Period("2026-04")] * 3,
        "Nominal": [-50_000_000.0, -12_000_000.0, -12_000_000.0],
        "Amount": [-50_000_000.0, -12_000_000.0, -12_000_000.0],
        "PnL": [1000.0, 500.0, 200.0],
        "Clientrate": [0.008, 0.002, 0.002],
        "EqOisRate": [0.005, 0.0, 0.0],
        "YTM": [0.0, 0.0, 0.0],
        "OISfwd": [0.045, 0.045, 0.045],
        "Days in Month": [30, 30, 30],
        "Périmètre TOTAL": ["CC"] * 3,
    })
    result = compute_strategy_pnl(monthly)
    products = set(result["Product2BuyBack"].unique())
    assert "IAM/LD-NHCD" in products
    assert "IAM/LD-HCD" in products
    # No BND in strategy → no BND legs (C2: cond_col guard)
    assert "BND-NHCD" not in products
    assert "BND-HCD" not in products


def test_strategy_hcd_no_ois_subtraction():
    """HCD legs: PnL = Nominal_HCD × marginRate × DIM / MM (no OIS subtraction)."""
    monthly = pd.DataFrame({
        "Strategy IAS": ["FV001", "FV001"],
        "Product": ["IAM/LD", "HCD"],
        "Currency": ["CHF", "CHF"],
        "Direction": ["L", "L"],
        "Month": [pd.Period("2026-04")] * 2,
        "Nominal": [-50_000_000.0, -12_000_000.0],
        "Amount": [-50_000_000.0, -12_000_000.0],
        "PnL": [1000.0, 500.0],
        "Clientrate": [0.008, 0.002],
        "EqOisRate": [0.005, 0.0],
        "YTM": [0.0, 0.0],
        "OISfwd": [0.045, 0.045],
        "Days in Month": [30, 30],
        "Périmètre TOTAL": ["CC"] * 2,
    })
    result = compute_strategy_pnl(monthly)
    hcd = result[result["Product2BuyBack"] == "IAM/LD-HCD"]
    assert len(hcd) > 0
    # marginRate = 0.005 + 0 - 0.002 = 0.003
    # PnL = -12M × 0.003 × 30/360 = -3000
    assert abs(hcd.iloc[0]["PnL"] - (-3000.0)) < 1.0


def test_run_all_shocks_smoke(mtd_path, echeancier_path, wirp_path, irs_path):
    pytest.importorskip("openpyxl")
    if not mtd_path.exists():
        pytest.skip("Sample data not available")

    from cockpit.engine.pnl.engine import run_all_shocks
    from cockpit.engine.pnl.curves import CurveCache
    from cockpit.data.parsers import parse_mtd, parse_echeancier, parse_wirp, parse_irs_stock

    deals = parse_mtd(mtd_path)
    echeancier = parse_echeancier(echeancier_path)
    wirp = parse_wirp(wirp_path)
    irs_stock = parse_irs_stock(irs_path)
    cache = CurveCache()

    result = run_all_shocks(
        deals=deals,
        echeancier=echeancier,
        wirp=wirp,
        irs_stock=irs_stock,
        cache=cache,
        date_rates=None,
        shocks=["0"],
    )
    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0
    assert "Shock" in result.columns


# --- Issue #12: Floating rate matrix test ---

def test_build_rate_matrix_floating():
    """Floating deals should use ref_curves forward + spread."""
    from cockpit.engine.pnl.matrices import build_rate_matrix

    days = pd.date_range("2026-04-01", periods=3)
    deals = pd.DataFrame({
        "RateRef": [0.0],  # ignored for floating
        "is_floating": [True],
        "ref_index": ["ERIBO3"],
        "Spread": [0.007],  # 70 bps
    })
    ref_curves = pd.DataFrame({
        "Indice": ["ERIBO3"] * 3,
        "Date": days,
        "value": [0.032, 0.033, 0.034],
    })
    result = build_rate_matrix(deals, days, ref_curves)
    assert result.shape == (1, 3)
    # Day 1: 0.032 + 0.007 = 0.039
    np.testing.assert_almost_equal(result[0, 0], 0.039, decimal=4)
    # Day 3: 0.034 + 0.007 = 0.041
    np.testing.assert_almost_equal(result[0, 2], 0.041, decimal=4)


# --- Issue #13: Direction filtering test ---

def test_merge_results_direction_filtering():
    """BND legs exclude L/D; IAM/LD legs exclude B."""
    from cockpit.engine.pnl.engine import merge_results

    strategy = pd.DataFrame({
        "Product2BuyBack": ["BND-HCD", "BND-NHCD", "IAM/LD-HCD", "IAM/LD-NHCD",
                            "BND-HCD", "IAM/LD-HCD"],
        "Direction": ["B", "L", "L", "B", "D", "B"],
        # B=bond, L=lender, D=deposit
        "Value": [100, 200, 300, 400, 500, 600],
    })
    result = merge_results(pd.DataFrame(), strategy, pd.DataFrame())

    # BND-NHCD with Direction=L should be excluded
    assert len(result[
        (result["Product2BuyBack"] == "BND-NHCD") & (result["Direction"] == "L")
    ]) == 0
    # BND-HCD with Direction=D should be excluded
    assert len(result[
        (result["Product2BuyBack"] == "BND-HCD") & (result["Direction"] == "D")
    ]) == 0
    # IAM/LD-NHCD with Direction=B should be excluded
    assert len(result[
        (result["Product2BuyBack"] == "IAM/LD-NHCD") & (result["Direction"] == "B")
    ]) == 0
    # IAM/LD-HCD with Direction=B should be excluded
    assert len(result[
        (result["Product2BuyBack"] == "IAM/LD-HCD") & (result["Direction"] == "B")
    ]) == 0
    # BND-HCD with Direction=B should survive
    assert len(result[
        (result["Product2BuyBack"] == "BND-HCD") & (result["Direction"] == "B")
    ]) == 1
    # IAM/LD-HCD with Direction=L should survive
    assert len(result[
        (result["Product2BuyBack"] == "IAM/LD-HCD") & (result["Direction"] == "L")
    ]) == 1


# --- Issue #14: BOOK2 MTM test ---

def test_compute_book2_mtm_mock():
    """BOOK2 MTM falls back to deterministic mock when WASP unavailable."""
    from cockpit.engine.pnl.engine import compute_book2_mtm

    irs_stock = pd.DataFrame({
        "Deal Number KND": ["IRS@300157"],
        "Amount": [10_000_000.0],
        "Rate": [0.22],
    })
    result = compute_book2_mtm(irs_stock, "2026-03-26", "0")
    assert "MTM" in result.columns
    assert len(result) == 1


# --- T2: Alive mask with date_run ---

def test_build_alive_mask_with_date_run():
    """Active range capped at max(Valuedate, first_of_month(dateRun))."""
    from cockpit.engine.pnl.matrices import build_alive_mask
    days = pd.date_range("2026-03-01", "2026-04-30")
    deals = pd.DataFrame({
        "Valuedate": [pd.Timestamp("2020-01-01")],  # old deal
        "Maturitydate": [pd.Timestamp("2028-12-31")],
    })
    # Without date_run: alive from first day of grid
    mask_no_cap = build_alive_mask(deals, days)
    assert mask_no_cap[0, :].all()

    # With date_run April 15: capped at first_of_month(April) = April 1
    # So March days are dead, April days are alive
    mask_capped = build_alive_mask(deals, days, date_run=pd.Timestamp("2026-04-15"))
    assert not mask_capped[0, :31].any()  # all March days dead (before April 1)
    assert mask_capped[0, 31:].all()      # all April days alive


# --- T3: _resolve_rate_ref product mapping ---

def test_resolve_rate_ref_product_mapping():
    """Each product maps to the correct rate column."""
    from cockpit.engine.pnl.engine import _resolve_rate_ref
    deals = pd.DataFrame({
        "Product": ["IAM/LD", "BND", "IRS", "HCD", "FXS"],
        "EqOisRate": [0.03, 0.0, 0.0, 0.0, 0.025],
        "YTM": [0.0, -0.05, 0.0, 0.0, 0.0],
        "Clientrate": [0.02, 0.01, 0.015, 0.008, 0.01],
        "Floating Rates Short Name": ["", "", "", "", ""],
    })
    result = _resolve_rate_ref(deals)
    assert result.iloc[0]["RateRef"] == 0.03    # IAM/LD → EqOisRate
    assert result.iloc[1]["RateRef"] == -0.05   # BND → YTM
    assert result.iloc[2]["RateRef"] == 0.015   # IRS → Clientrate
    assert result.iloc[3]["RateRef"] == 0.008   # HCD → Clientrate
    assert result.iloc[4]["RateRef"] == 0.025   # FXS → EqOisRate


# --- T4: Mock curves shock application ---

def test_mock_curves_shock_applied():
    """Mock curves from WIRP should have shock shift applied."""
    from cockpit.engine.pnl.engine import _mock_curves_from_wirp
    wirp = pd.DataFrame({
        "Indice": ["CHFSON"],
        "Meeting": [pd.Timestamp("2026-04-01")],
        "Rate": [0.0486],
        "Hike / Cut": [0],
    })
    days = pd.date_range("2026-04-01", periods=3)

    base = _mock_curves_from_wirp(wirp, days, shock="0")
    shifted = _mock_curves_from_wirp(wirp, days, shock="50")

    # Shock=50 should add 0.005 (50 bps)
    np.testing.assert_almost_equal(
        shifted["value"].iloc[0] - base["value"].iloc[0], 0.005, decimal=6
    )


# --- T7: compare_pnl output format ---

def test_compare_pnl_format(mtd_path, echeancier_path, wirp_path, irs_path):
    """compare_pnl should produce wide format with Level/Level_date columns."""
    pytest.importorskip("openpyxl")
    if not mtd_path.exists():
        pytest.skip("Sample data not available")

    from cockpit.engine.pnl.forecast import ForecastRatePnL, compare_pnl
    from datetime import datetime

    pnl1 = ForecastRatePnL(
        dateRun=datetime(2026, 3, 26), export=False,
        input_dir=mtd_path.parent, output_dir=mtd_path.parent.parent / "output",
    )
    pnl2 = ForecastRatePnL(
        dateRun=datetime(2026, 3, 26), export=False,
        input_dir=mtd_path.parent, output_dir=mtd_path.parent.parent / "output",
    )
    comp = compare_pnl(pnl1, pnl2, output_path=mtd_path.parent.parent / "output" / "test_comp.xlsx")

    assert "Level" in comp.columns
    assert "Level_date" in comp.columns
    assert set(comp["Level"].unique()) == {"Value_new", "Value_prev", "Delta"}
    # Delta should be 0 (same data)
    month_cols = [c for c in comp.columns if c not in ["Périmètre TOTAL", "Deal currency", "Product2BuyBack", "Direction", "Shock", "Indice", "Level", "Level_date"]]
    delta_rows = comp[comp["Level"] == "Delta"]
    if month_cols and len(delta_rows) > 0:
        assert delta_rows[month_cols].abs().sum().sum() < 0.01


# --- T1: Credit spread subtraction correctness ---

@pytest.mark.xfail(
    reason="Credit spread subtraction not yet implemented in parse_mtd (pre-existing in source)",
    strict=False,
)
def test_parse_mtd_credit_spread_value(mtd_path):
    """YTM should equal YTM_gross - CreditSpread_FIFO (both in pct, then /100)."""
    if not mtd_path.exists():
        pytest.skip("Sample data not available")

    from cockpit.data.parsers import parse_mtd
    df = parse_mtd(mtd_path)
    bnd = df[df["Product"] == "BND"]
    if len(bnd) > 0:
        # BND 313104: YTM_gross=2.8929, CreditSpread=10.9289 → net=-8.0360 → /100=-0.080360
        row = bnd[bnd["Dealid"].astype(str) == "313104"]
        if len(row) > 0:
            np.testing.assert_almost_equal(row.iloc[0]["YTM"], -0.080360, decimal=4)
