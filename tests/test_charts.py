from cockpit.render.charts import (
    build_macro_charts,
    build_fx_energy_charts,
    build_pnl_charts,
    build_portfolio_charts,
)


def test_build_macro_charts_empty_data():
    result = build_macro_charts({})
    assert isinstance(result, dict)
    assert "score_cards" in result


def test_build_fx_energy_charts_empty_data():
    result = build_fx_energy_charts({})
    assert isinstance(result, dict)
    assert "fx_series" in result
    assert "energy_series" in result


def test_build_pnl_charts_empty_data():
    result = build_pnl_charts({})
    assert isinstance(result, dict)
    assert "monthly_pnl" in result


def test_build_portfolio_charts_empty_data():
    result = build_portfolio_charts({})
    assert isinstance(result, dict)
    assert "liquidity_ladder" in result


def test_build_fx_energy_charts_with_history():
    data = {
        "usd_chf_history": [
            {"date": "2026-03-01", "value": 0.79},
            {"date": "2026-03-02", "value": 0.80},
        ],
        "eur_chf_history": [
            {"date": "2026-03-01", "value": 0.90},
            {"date": "2026-03-02", "value": 0.91},
        ],
        "gbp_chf_history": [
            {"date": "2026-03-01", "value": 1.11},
            {"date": "2026-03-02", "value": 1.12},
        ],
        "energy": {
            "brent_history": [{"date": "2026-03-01", "value": 85.0}],
            "eu_gas_history": [{"date": "2026-03-01", "value": 35.0}],
        },
    }
    result = build_fx_energy_charts(data)
    assert len(result["fx_series"]["usd_chf"]["dates"]) == 2
    assert result["fx_series"]["usd_chf"]["values"] == [0.79, 0.80]


def test_build_pnl_charts_with_data():
    pnl_data = {
        "months": ["2026/04", "2026/05", "2026/06"],
        "by_currency": {
            "CHF": {"shock_0": [100, 200, 150], "shock_50": [80, 180, 130]},
            "EUR": {"shock_0": [50, 60, 70], "shock_50": [40, 50, 60]},
        },
    }
    result = build_pnl_charts(pnl_data)
    assert result["monthly_pnl"]["labels"] == ["2026/04", "2026/05", "2026/06"]
    assert "CHF" in result["monthly_pnl"]["datasets"]


def test_build_portfolio_charts_with_data():
    portfolio_data = {
        "exposure": {
            "buckets": [
                {"label": "O/N", "inflows": 1000, "outflows": 500, "net": 500, "cumulative": 500},
                {"label": "D+1", "inflows": 800, "outflows": 900, "net": -100, "cumulative": 400},
            ],
            "survival_days": 45,
        },
        "positions": {
            "currencies": {
                "CHF": {"assets": 5e9, "liabilities": 4e9, "net": 1e9},
            },
        },
        "counterparty": {
            "concentration": {
                "top_10": [{"counterparty": "A", "nominal": 500e6, "pct_total": 12.5}],
                "hhi": 850,
            },
            "rating": {
                "AAA-AA": {"nominal": 2e9, "pct": 50.0},
                "A": {"nominal": 1e9, "pct": 25.0},
            },
        },
    }
    result = build_portfolio_charts(portfolio_data)
    assert len(result["liquidity_ladder"]["labels"]) == 2
    assert result["liquidity_ladder"]["inflows"] == [1000, 800]
