"""End-to-end smoke test: render cockpit with fixture data."""

import json
from pathlib import Path
from cockpit.cli import cmd_render


def test_full_render_with_all_data(tmp_path: Path):
    """Render cockpit with all 4 data files present."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    date = "2026-04-03"

    # Macro snapshot
    macro = {
        "rates": {
            "fed_rates": {"mid": 3.625, "upper": 3.75, "lower": 3.50},
            "ecb_rates": {"deposit_facility": 2.00},
        },
        "snb_rate": 0.00,
        "usd_chf_history": [{"date": "2026-04-01", "value": 0.795}, {"date": "2026-04-02", "value": 0.800}],
        "eur_chf_history": [{"date": "2026-04-01", "value": 0.904}],
        "gbp_chf_history": [{"date": "2026-04-01", "value": 1.120}],
        "energy": {
            "brent_history": [{"date": "2026-04-01", "value": 85.0}],
            "eu_gas_history": [{"date": "2026-04-01", "value": 35.0}],
        },
        "alerts": [],
    }
    (data_dir / f"{date}_macro_snapshot.json").write_text(json.dumps(macro))

    # P&L
    pnl = {
        "months": ["2026/04", "2026/05", "2026/06"],
        "by_currency": {
            "CHF": {"shock_0": [100000, 200000, 150000], "shock_50": [80000, 180000, 130000]},
            "EUR": {"shock_0": [50000, 60000, 70000], "shock_50": [40000, 50000, 60000]},
        },
    }
    (data_dir / f"{date}_pnl.json").write_text(json.dumps(pnl))

    # Portfolio
    portfolio = {
        "exposure": {
            "buckets": [
                {"label": "O/N", "inflows": 1200000, "outflows": 800000, "net": 400000, "cumulative": 400000},
                {"label": "D+1", "inflows": 900000, "outflows": 1000000, "net": -100000, "cumulative": 300000},
            ],
            "survival_days": 45,
        },
        "positions": {
            "currencies": {
                "CHF": {"assets": 5e9, "liabilities": 4e9, "net": 1e9},
                "EUR": {"assets": 2e9, "liabilities": 1.8e9, "net": 0.2e9},
            },
        },
        "counterparty": {
            "concentration": {
                "top_10": [{"counterparty": "THCCBFIGE", "nominal": 500e6, "pct_total": 12.5}],
                "hhi": 850,
            },
            "rating": {
                "AAA-AA": {"nominal": 2e9, "pct": 50.0},
                "A": {"nominal": 1e9, "pct": 25.0},
            },
            "hqla": {
                "L1": {"nominal": 1.8e9, "pct": 45.0},
                "L2A": {"nominal": 0.8e9, "pct": 20.0},
            },
        },
    }
    (data_dir / f"{date}_portfolio.json").write_text(json.dumps(portfolio))

    # Scores
    scores = {
        "USD": {"composite": 55, "label": "Watch", "driver": "policy", "families": {}},
        "EUR": {"composite": 40, "label": "Calm", "driver": "inflation", "families": {}},
        "CHF": {"composite": 30, "label": "Calm", "driver": "liquidity", "families": {}},
        "GBP": {"composite": 65, "label": "Watch", "driver": "growth", "families": {}},
    }
    (data_dir / f"{date}_scores.json").write_text(json.dumps(scores))

    # Brief
    brief = {
        "date": date,
        "reviewed": True,
        "html": "<h2>Executive Summary</h2><p>Markets remain stable with modest CHF strength.</p>",
    }
    (data_dir / f"{date}_brief.json").write_text(json.dumps(brief))

    # Render
    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    html_path = output_dir / f"{date}_cockpit.html"
    assert html_path.exists()

    html = html_path.read_text()

    # Verify all tabs rendered (not placeholder)
    assert "cockpit fetch" not in html  # no fetch placeholder
    assert "cockpit compute" not in html  # no compute placeholder
    assert "cockpit analyze" not in html  # no analyze placeholder

    # Verify key content
    assert "Swiss Treasury Cockpit" in html
    assert "2026-04-03" in html
    assert "Watch" in html  # USD score label
    assert "Calm" in html  # EUR score label
    assert "3.625" in html or "3.63" in html  # Fed rate
    assert "Fact-Checked" in html  # Brief reviewed badge
    assert "Executive Summary" in html  # Brief content


def test_partial_render_missing_pnl(tmp_path: Path):
    """Render with only macro data — P&L/portfolio tabs show placeholders."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    date = "2026-04-03"
    macro = {"rates": {"fed_rates": {"mid": 3.625}}, "alerts": []}
    (data_dir / f"{date}_macro_snapshot.json").write_text(json.dumps(macro))

    cmd_render(date=date, data_dir=data_dir, output_dir=output_dir)

    html = (output_dir / f"{date}_cockpit.html").read_text()
    assert "cockpit compute" in html  # P&L placeholder
    assert "cockpit analyze" in html  # Brief placeholder
