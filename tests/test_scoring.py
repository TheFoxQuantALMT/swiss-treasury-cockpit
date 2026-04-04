from cockpit.engine.scoring.scoring import compute_scores, normalize


def test_normalize_within_range():
    breakpoints = [(0.0, 0.0), (100.0, 100.0)]
    assert normalize(50.0, breakpoints) == 50.0


def test_normalize_none_input():
    breakpoints = [(0.0, 0.0), (100.0, 100.0)]
    assert normalize(None, breakpoints) is None


def test_compute_scores_returns_four_currencies():
    # Minimal data dict with required keys
    data = {
        "fed_rates": {"mid": 3.625, "upper": 3.75, "lower": 3.50},
        "ecb_rates": {"deposit_facility": 2.00, "main_refinancing": 2.40},
        "snb_rate": 0.00,
        "daily_indicators": {
            "vix": {"value": 18.0},
            "us_2y": {"value": 4.20},
            "us_10y": {"value": 4.35},
            "breakeven_5y": {"value": 2.30},
            "breakeven_10y": {"value": 2.20},
        },
        "macro_indicators": {
            "pce": {"value": 2.5},
            "core_pce": {"value": 2.8},
            "unemployment": {"value": 4.1},
            "uk_unemployment": {"value": 4.3},
            "uk_10y_yield": {"value": 4.50},
        },
        "usd_chf_latest": {"value": 0.7950},
        "eur_chf_latest": {"value": 0.9040},
        "gbp_chf_latest": {"value": 1.1200},
        "energy": {"brent": {"value": 85.0}, "eu_gas": {"value": 35.0}},
        "sight_deposits": {"domestic": {"value": 450.0}},
        "saron": {"value": 0.0043},
    }
    scores = compute_scores(data)
    assert "USD" in scores
    assert "EUR" in scores
    assert "CHF" in scores
    assert "GBP" in scores
    for ccy, score in scores.items():
        assert 0 <= score.composite <= 100
        assert score.label in ("Calm", "Watch", "Action")
