import numpy as np
import pandas as pd

from pnl_engine.matrices import (
    build_date_grid,
    expand_nominal_to_daily,
    build_alive_nominal_daily,
    build_alive_mask,
    build_mm_vector,
    build_rate_matrix,
)


def test_build_date_grid():
    days = build_date_grid(pd.Timestamp("2026-04-01"), months=3)
    assert days[0] == pd.Timestamp("2026-04-01")
    assert days[-1] <= pd.Timestamp("2026-07-01")
    assert len(days) == 91


def test_expand_nominal_to_daily():
    days = pd.date_range("2026-04-01", "2026-05-31")
    nominals = pd.DataFrame({"2026/04": [1_000_000.0], "2026/05": [2_000_000.0]})
    result = expand_nominal_to_daily(nominals, days)
    assert result.shape == (1, len(days))
    assert result[0, 0] == 1_000_000.0
    assert result[0, 29] == 1_000_000.0
    assert result[0, 30] == 2_000_000.0


def test_build_alive_nominal_daily_upscales_boundary_month():
    """Mid-month refix: bucket is pro-rata, engine must upscale so alive-day nominal
    equals the implied full nominal (undoing bank's pro-rata convention)."""
    days = pd.date_range("2026-04-01", "2026-05-31")  # 61 days (April 30 + May 31)
    # Deal alive April 1–April 20 (20 days), dies on April 20 (refix date).
    # Bank bucket for April = full_nominal × 20/30 = 100M × 20/30 ≈ 66.67M.
    nominals = pd.DataFrame({"2026/04": [66_666_666.67], "2026/05": [0.0]})
    deals = pd.DataFrame({
        "Valuedate": [pd.Timestamp("2026-01-01")],
        "Maturitydate": [pd.Timestamp("2026-04-20")],
    })
    alive = build_alive_mask(deals, days)
    nd = build_alive_nominal_daily(nominals, alive, days)
    # Alive days (April 1–20) carry the full implied nominal (≈100M).
    assert nd.shape == (1, 61)
    assert np.isclose(nd[0, 0], 100_000_000.0, rtol=1e-6)
    assert np.isclose(nd[0, 19], 100_000_000.0, rtol=1e-6)
    # Dead days (April 21+ and all of May) are zero.
    assert nd[0, 20:].sum() == 0.0
    # Sum of alive-day nominals = 20 × 100M = 2,000M nominal-days.
    assert np.isclose(nd[0].sum(), 2_000_000_000.0, rtol=1e-6)


def test_build_alive_nominal_daily_full_month_unchanged():
    """Full-alive month: factor == 1, result matches uniform broadcast × mask."""
    days = pd.date_range("2026-04-01", "2026-04-30")
    nominals = pd.DataFrame({"2026/04": [1_000_000.0]})
    deals = pd.DataFrame({
        "Valuedate": [pd.Timestamp("2026-01-01")],
        "Maturitydate": [pd.Timestamp("2026-12-31")],
    })
    alive = build_alive_mask(deals, days)
    nd = build_alive_nominal_daily(nominals, alive, days)
    assert np.allclose(nd[0], 1_000_000.0)


def test_build_alive_mask_mid_month_maturity():
    days = pd.date_range("2026-04-01", "2026-04-30")
    deals = pd.DataFrame({
        "Valuedate": [pd.Timestamp("2026-01-01")],
        "Maturitydate": [pd.Timestamp("2026-04-15")],
    })
    mask = build_alive_mask(deals, days)
    assert mask.shape == (1, 30)
    assert mask[0, :15].all()
    assert not mask[0, 15:].any()


def test_build_mm_vector():
    deals = pd.DataFrame({"Currency": ["CHF", "GBP", "EUR"]})
    mm = build_mm_vector(deals)
    assert mm.tolist() == [360, 365, 360]


def test_build_rate_matrix_fixed():
    days = pd.date_range("2026-04-01", periods=5)
    deals = pd.DataFrame({"RateRef": [0.025], "is_floating": [False]})
    result = build_rate_matrix(deals, days, ref_curves=None)
    assert result.shape == (1, 5)
    assert (result[0] == 0.025).all()


# ---------------------------------------------------------------------------
# Term-floater branch (refixing-aware)
# ---------------------------------------------------------------------------

import pytest

from pnl_engine.engine import _infer_fixing_tenor_days


@pytest.mark.parametrize(
    "short_name, last_fix, next_fix, expected",
    [
        ("SARON",   None,         None,         0),
        ("SARON",   "2026-03-01", "2026-06-01", 92),   # date diff wins (rule 1)
        ("SARON3M", None,         None,         90),   # suffix (rule 2)
        ("EURIBOR6M", None,       None,         180),
        ("ESTR1M",  None,         None,         30),
        ("",        None,         None,         0),
        ("SARON",   "2026-03-01", "2026-03-01", 0),    # zero/negative diff → ignore
        ("SARON3M", "2026-03-01", "2026-06-01", 92),   # date diff overrides suffix
    ],
)
def test_infer_fixing_tenor_days(short_name, last_fix, next_fix, expected):
    lf = pd.Timestamp(last_fix) if last_fix else pd.NaT
    nf = pd.Timestamp(next_fix) if next_fix else pd.NaT
    assert _infer_fixing_tenor_days(short_name, lf, nf) == expected


def _ref_curve(indice: str, dates, values) -> pd.DataFrame:
    return pd.DataFrame({
        "Indice": [indice] * len(dates),
        "Date": pd.to_datetime(dates),
        "value": values,
    })


def test_term_floater_held_constant_in_current_period():
    """3M floater with active fixing: rate held constant at current_fixing_rate."""
    today = pd.Timestamp.today().normalize()
    last_fix = today - pd.Timedelta(days=30)
    next_fix = today + pd.Timedelta(days=60)
    days = pd.date_range(last_fix, next_fix - pd.Timedelta(days=1), freq="D")
    deals = pd.DataFrame([{
        "RateRef": 0.0,
        "is_floating": True,
        "ref_index": "CHFSON3M",
        "Currency": "CHF",
        "Spread": 0.0010,
        "fixing_tenor_days": 90,
        "last_fixing_date": last_fix,
        "next_fixing_date": next_fix,
        "current_fixing_rate": 0.0085,
    }])
    # Curve has arbitrary forward values — should NOT be used in current period.
    curve = _ref_curve("CHFSON3M", [last_fix, next_fix + pd.Timedelta(days=365)], [0.020, 0.030])
    result = build_rate_matrix(deals, days, curve)
    # All days in current period should be 0.0085 + 0.0010
    expected = 0.0085 + 0.0010
    assert np.allclose(result[0], expected)


def test_term_floater_refixes_at_next_period():
    """After next_fixing_date, rate samples the forward curve at the fixing date."""
    today = pd.Timestamp.today().normalize()
    last_fix = today - pd.Timedelta(days=10)
    next_fix = today + pd.Timedelta(days=80)   # 90d tenor
    grid_end = next_fix + pd.Timedelta(days=89)  # one full forward period
    days = pd.date_range(last_fix, grid_end, freq="D")
    deals = pd.DataFrame([{
        "RateRef": 0.0,
        "is_floating": True,
        "ref_index": "CHFSON3M",
        "Currency": "CHF",
        "Spread": 0.0,
        "fixing_tenor_days": 90,
        "last_fixing_date": last_fix,
        "next_fixing_date": next_fix,
        "current_fixing_rate": 0.0085,
    }])
    curve = _ref_curve(
        "CHFSON3M",
        [last_fix - pd.Timedelta(days=365), next_fix, grid_end + pd.Timedelta(days=365)],
        [0.0050, 0.0150, 0.0150],
    )
    result = build_rate_matrix(deals, days, curve)
    # Current period: held at current_fixing_rate
    n_current = (next_fix - last_fix).days
    assert np.allclose(result[0, :n_current], 0.0085)
    # Next period: sampled from curve at next_fix
    assert np.allclose(result[0, n_current:n_current + 89], 0.0150)


def test_rfr_overnight_branch_unchanged():
    """tenor==0 floater behaves as overnight RFR (daily curve interp)."""
    days = pd.date_range("2026-04-01", periods=10, freq="D")
    deals = pd.DataFrame([{
        "RateRef": 0.0,
        "is_floating": True,
        "ref_index": "EUREST",
        "Currency": "EUR",
        "Spread": 0.0,
        "fixing_tenor_days": 0,
    }])
    curve = _ref_curve(
        "EUREST",
        [days[0], days[-1]],
        [0.0200, 0.0200],
    )
    result = build_rate_matrix(deals, days, curve)
    assert np.allclose(result[0], 0.0200)


def test_term_floater_missing_dates_falls_back_to_overnight(caplog):
    """Term short name with NaN fixing dates degrades to overnight + WARNING."""
    days = pd.date_range("2026-04-01", periods=5, freq="D")
    deals = pd.DataFrame([{
        "RateRef": 0.0,
        "is_floating": True,
        "ref_index": "CHFSON3M",
        "Currency": "CHF",
        "Spread": 0.0,
        "fixing_tenor_days": 90,
        "last_fixing_date": pd.NaT,
        "next_fixing_date": pd.NaT,
    }])
    curve = _ref_curve("CHFSON3M", [days[0], days[-1]], [0.0150, 0.0150])
    with caplog.at_level("WARNING"):
        result = build_rate_matrix(deals, days, curve)
    assert np.allclose(result[0], 0.0150)
    assert any("missing fixing dates" in rec.message for rec in caplog.records)


def test_valid_float_indices_tracks_mapping():
    """VALID_FLOAT_INDICES must auto-track FLOAT_NAME_TO_WASP — single source of truth."""
    from pnl_engine.config import FLOAT_NAME_TO_WASP, VALID_FLOAT_INDICES
    assert VALID_FLOAT_INDICES == set(FLOAT_NAME_TO_WASP) | {""}


def test_resolve_rate_ref_term_floater_not_dropped():
    """RFR-drop guard must NOT drop term floaters (tenor>0 + OIS-base ref_index)."""
    from pnl_engine.engine import _resolve_rate_ref
    deals = pd.DataFrame([
        # Overnight SARON IRS — should be dropped (tenor=0, ref=CHFSON)
        {"Dealid": 1, "Product": "IRS", "Currency": "CHF", "Direction": "D",
         "Clientrate": 0.01, "Floating Rates Short Name": "SARON",
         "last_fixing_date": pd.NaT, "next_fixing_date": pd.NaT},
        # Term SARON3M IRS — must SURVIVE (tenor=90)
        {"Dealid": 2, "Product": "IRS", "Currency": "CHF", "Direction": "D",
         "Clientrate": 0.01, "Floating Rates Short Name": "SARON3M",
         "last_fixing_date": pd.Timestamp("2026-03-01"),
         "next_fixing_date": pd.Timestamp("2026-06-01")},
    ])
    out = _resolve_rate_ref(deals)
    surviving_ids = set(out["Dealid"].astype(int).tolist())
    assert 2 in surviving_ids, "Term floater was incorrectly dropped"
    assert 1 not in surviving_ids, "Overnight RFR with OIS base should be dropped"
