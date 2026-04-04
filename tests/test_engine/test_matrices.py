import numpy as np
import pandas as pd

from cockpit.engine.pnl.matrices import (
    build_date_grid,
    expand_nominal_to_daily,
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
