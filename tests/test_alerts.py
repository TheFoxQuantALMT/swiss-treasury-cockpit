from cockpit.engine.alerts.alerts import check_alerts


def test_check_alerts_returns_list():
    current = {
        "usd_chf_latest": {"value": 0.90},  # above USD_CHF high of 0.85
        "eur_chf_latest": {"value": 0.93},
        "gbp_chf_latest": {"value": 1.12},
        "energy": {"brent": {"value": 85.0}, "eu_gas": {"value": 35.0}},
        "sight_deposits": {"domestic": {"value": 450.0}},
    }
    deltas = {
        "usd_chf": {"current": 0.90, "1d": {"pct": 0.5}},
        "eur_chf": {"current": 0.93, "1d": {"pct": 0.2}},
        "gbp_chf": {"current": 1.12, "1d": {"pct": 0.1}},
        "brent": {"current": 85.0, "1d": {"pct": 1.0}},
        "eu_gas": {"current": 35.0, "1d": {"pct": 0.5}},
        "vix": {"current": 18.0, "1d": {"pct": 2.0}},
    }
    alerts = check_alerts(current, deltas)
    assert isinstance(alerts, list)
    # USD/CHF at 0.90 is above the 0.85 high band — should trigger
    fx_alerts = [a for a in alerts if a.get("type") == "fx_breach"]
    assert len(fx_alerts) > 0
