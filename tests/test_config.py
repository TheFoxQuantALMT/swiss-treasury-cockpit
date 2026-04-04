from cockpit.config import (
    # From economic-pnl
    CURRENCY_TO_OIS,
    PRODUCT_RATE_COLUMN,
    SUPPORTED_CURRENCIES,
    MM_BY_CURRENCY,
    SHOCKS,
    LIQUIDITY_BUCKETS,
    RATING_BUCKETS,
    HQLA_LEVELS,
    CURRENCY_CLASSES,
    CDS_ALERT_THRESHOLD_BPS,
    # From cbwatch
    FX_ALERT_BANDS,
    ENERGY_THRESHOLDS,
    DEPOSIT_THRESHOLDS,
    DAILY_MOVE_THRESHOLDS,
    SCORING_LABELS,
    SCENARIOS,
    DATA_DIR,
    OUTPUT_DIR,
)


def test_currency_to_ois():
    assert CURRENCY_TO_OIS["CHF"] == "CHFSON"
    assert CURRENCY_TO_OIS["EUR"] == "EUREST"
    assert CURRENCY_TO_OIS["USD"] == "USSOFR"
    assert CURRENCY_TO_OIS["GBP"] == "GBPOIS"


def test_product_rate_column():
    assert PRODUCT_RATE_COLUMN["IAM/LD"] == "EqOisRate"
    assert PRODUCT_RATE_COLUMN["BND"] == "YTM"
    assert PRODUCT_RATE_COLUMN["HCD"] == "Clientrate"


def test_supported_currencies():
    assert SUPPORTED_CURRENCIES == {"CHF", "EUR", "USD", "GBP"}


def test_mm_by_currency():
    assert MM_BY_CURRENCY["CHF"] == 360
    assert MM_BY_CURRENCY["GBP"] == 365


def test_shocks():
    assert SHOCKS == ["0", "50", "wirp"]


def test_liquidity_buckets_count():
    assert len(LIQUIDITY_BUCKETS) == 24


def test_liquidity_buckets_daily_detail():
    labels = [b[0] for b in LIQUIDITY_BUCKETS]
    assert labels[0] == "O/N"
    assert labels[1] == "D+1"
    assert labels[15] == "D+15"
    assert labels[16] == "16-30d"


def test_rating_buckets_cover_all_grades():
    all_ratings = []
    for ratings in RATING_BUCKETS.values():
        all_ratings.extend(ratings)
    assert "AAA" in all_ratings
    assert "NR" in all_ratings
    assert "D" in all_ratings


def test_hqla_levels():
    assert HQLA_LEVELS == ["L1", "L2A", "L2B", "Non-HQLA"]


def test_currency_classes():
    assert CURRENCY_CLASSES == ["Total", "CHF", "USD", "EUR", "GBP", "Others"]


def test_cds_threshold():
    assert CDS_ALERT_THRESHOLD_BPS == 200


def test_fx_alert_bands():
    assert FX_ALERT_BANDS["EUR_CHF"]["low"] == 0.90
    assert FX_ALERT_BANDS["EUR_CHF"]["high"] == 0.96
    assert FX_ALERT_BANDS["USD_CHF"]["low"] == 0.78
    assert FX_ALERT_BANDS["USD_CHF"]["high"] == 0.85
    assert FX_ALERT_BANDS["GBP_CHF"]["low"] == 1.08
    assert FX_ALERT_BANDS["GBP_CHF"]["high"] == 1.16


def test_energy_thresholds():
    assert ENERGY_THRESHOLDS["brent_high"] == 120.0
    assert ENERGY_THRESHOLDS["brent_low"] == 65.0
    assert ENERGY_THRESHOLDS["eu_gas_high"] == 80.0


def test_deposit_thresholds():
    assert DEPOSIT_THRESHOLDS["weekly_change_threshold_bln"] == 2.0


def test_daily_move_thresholds():
    assert DAILY_MOVE_THRESHOLDS["brent_pct"] == 5.0
    assert DAILY_MOVE_THRESHOLDS["fx_pct"] == 1.0
    assert DAILY_MOVE_THRESHOLDS["vix_pct"] == 10.0


def test_scoring_labels():
    assert SCORING_LABELS["calm_max"] == 45
    assert SCORING_LABELS["watch_max"] == 70


def test_scenarios():
    assert "ceasefire_rapid" in SCENARIOS
    assert "conflict_contained" in SCENARIOS
    assert "escalation_major" in SCENARIOS


def test_data_dir():
    assert DATA_DIR.name == "data"


def test_output_dir():
    assert OUTPUT_DIR.name == "output"
