import pandas as pd
from cockpit.engine.snapshot.enrichment import enrich_deals


def _sample_deals() -> pd.DataFrame:
    return pd.DataFrame({
        "Dealid": [1, 2, 3],
        "Product": ["IAM/LD", "BND", "HCD"],
        "Currency": ["CHF", "EUR", "USD"],
        "Direction": ["L", "B", "D"],
        "Amount": [10_000_000.0, 5_000_000.0, 8_000_000.0],
        "Counterparty": ["THCCBFIGE", "CLI-MT-CIB", "UNKNOWN-X"],
    })


def _sample_ref() -> pd.DataFrame:
    return pd.DataFrame({
        "counterparty": ["THCCBFIGE", "CLI-MT-CIB"],
        "rating": ["AA+", "BBB-"],
        "hqla_level": ["L1", "L2B"],
        "country": ["CH", "FR"],
    })


def test_enrich_deals_joins_reference_data():
    enriched = enrich_deals(_sample_deals(), _sample_ref())
    row0 = enriched[enriched["Dealid"] == 1].iloc[0]
    assert row0["rating"] == "AA+"
    assert row0["hqla_level"] == "L1"
    assert row0["country"] == "CH"


def test_enrich_deals_defaults_unmatched():
    enriched = enrich_deals(_sample_deals(), _sample_ref())
    row2 = enriched[enriched["Dealid"] == 3].iloc[0]
    assert row2["rating"] == "NR"
    assert row2["hqla_level"] == "Non-HQLA"
    assert row2["country"] == "XX"
