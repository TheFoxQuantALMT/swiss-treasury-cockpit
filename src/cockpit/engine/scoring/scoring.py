"""Deterministic scoring engine for per-currency treasury risk assessment.

Converts raw market data into composite scores (0-100) with Calm/Watch/Action
labels for USD, EUR, CHF, and GBP. No LLM involvement — pure Python + config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from cockpit.config import SCORING_LABELS


@dataclass
class FamilyScore:
    """Score for one indicator family (inflation, policy, liquidity, growth)."""
    name: str
    score: float              # 0-100
    label: str                # "Calm", "Watch", "Action"
    confidence: str           # "high", "low"
    indicators: dict[str, float | None] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)


@dataclass
class CurrencyScore:
    """Composite score for one currency."""
    currency: str
    composite: float          # 0-100
    label: str                # "Calm", "Watch", "Action"
    families: dict[str, FamilyScore] = field(default_factory=dict)
    driver: str = ""          # name of highest-scoring family


def _assign_label(score: float, config: dict[str, Any]) -> str:
    """Map a 0-100 score to Calm/Watch/Action."""
    calm_max = config.get("calm_max", SCORING_LABELS["calm_max"])
    watch_max = config.get("watch_max", SCORING_LABELS["watch_max"])
    if score <= calm_max:
        return "Calm"
    elif score <= watch_max:
        return "Watch"
    else:
        return "Action"


def normalize(value: float | None, breakpoints: list[tuple[float, float]]) -> float | None:
    """Map a raw value to 0-100 using piecewise linear interpolation.

    Args:
        value: Raw indicator value. Returns None if value is None.
        breakpoints: [(raw_value, score), ...] sorted by raw_value ascending.
            Values below first breakpoint get first score.
            Values above last breakpoint get last score.

    Returns:
        Score between 0-100, or None if value is None.
    """
    if value is None:
        return None

    if not breakpoints:
        return 50.0

    # Below first breakpoint
    if value <= breakpoints[0][0]:
        return breakpoints[0][1]

    # Above last breakpoint
    if value >= breakpoints[-1][0]:
        return breakpoints[-1][1]

    # Interpolate between breakpoints
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return y0
            t = (value - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)

    return breakpoints[-1][1]


# ---------------------------------------------------------------------------
# Indicator breakpoint tables
# ---------------------------------------------------------------------------
# Each maps: (raw_value, score_0_to_100)
# Higher score = more stress / more attention needed

_BP_VIX = [(15, 0), (18, 25), (25, 50), (30, 65), (35, 80), (40, 100)]
_BP_BREAKEVEN_DISTANCE = [(0, 0), (0.5, 12), (1.0, 25), (2.0, 50), (4.0, 100)]
_BP_BREAKEVEN_LEVEL = [(1.5, 0), (2.0, 25), (2.5, 50), (3.0, 75), (4.0, 100)]
_BP_BREAKEVEN_SLOPE = [(-0.25, 0), (0, 25), (0.25, 50), (0.5, 75), (0.75, 100)]
_BP_FED_RATE = [(0, 0), (2, 25), (3.5, 50), (5, 75), (6, 100)]
_BP_CURVE_2S10S = [(-1.0, 100), (-0.5, 75), (0, 50), (0.5, 25), (1.0, 0)]
_BP_REAL_RATE = [(-0.5, 0), (0, 10), (1.0, 25), (2.0, 50), (3.0, 75), (4.0, 100)]
_BP_CARRY_FED_BNS = [(0, 0), (1, 10), (2, 25), (3, 50), (4, 75), (5, 100)]
_BP_RATE_VOL = [(0, 0), (0.05, 25), (0.10, 50), (0.15, 75), (0.20, 100)]
_BP_UNEMPLOYMENT = [(3.5, 0), (4.0, 25), (4.5, 50), (5.0, 75), (5.5, 100)]
_BP_ECB_RATE = [(0, 0), (1, 20), (2, 40), (3, 60), (4, 80), (5, 100)]
_BP_SPREAD_FED_ECB = [(0, 0), (0.5, 25), (1.0, 50), (1.5, 75), (2.0, 100)]
_BP_EUR_CHF_STRESS = [(0.95, 0), (0.93, 25), (0.91, 50), (0.90, 75), (0.89, 100)]
_BP_CARRY_ECB_BNS = [(0, 0), (0.5, 10), (1.0, 25), (2.0, 50), (3.0, 75), (4.0, 100)]
_BP_FX_MOMENTUM = [(-2, 100), (-1, 75), (0, 50), (1, 25), (2, 0)]
_BP_SNB_RATE = [(-0.75, 0), (0, 10), (0.25, 25), (0.5, 50), (1.0, 100)]
_BP_INTERVENTION = [(0, 0), (1, 10), (2, 25), (5, 50), (10, 75), (15, 100)]
_BP_USD_CHF_STRESS = [(0.85, 0), (0.82, 25), (0.80, 50), (0.78, 75), (0.76, 100)]
_BP_DEPOSIT_CUMULATIVE = [(0, 0), (2, 10), (5, 25), (10, 50), (20, 75), (30, 100)]
_BP_USD_CHF_MOMENTUM = [(2, 0), (1, 25), (0, 50), (-1, 75), (-2, 100)]
_BP_BRENT_ENERGY = [(70, 0), (80, 25), (100, 50), (120, 75), (140, 100)]
_BP_GBP_CHF_STRESS = [(1.15, 0), (1.12, 25), (1.10, 50), (1.08, 75), (1.06, 100)]


def _safe_get(data: dict, *keys: str) -> float | None:
    """Safely extract a nested numeric value."""
    current: Any = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    return float(current) if current is not None else None


def _pct_change_30d(history: list[dict]) -> float | None:
    """Compute 30d % change from a history list."""
    if not history or len(history) < 2:
        return None
    first = history[0].get("value")
    last = history[-1].get("value")
    if first is not None and last is not None and first != 0:
        return ((last - first) / abs(first)) * 100
    return None


def _wow_change(data: dict) -> float | None:
    """Get latest week-over-week sight deposit change in B CHF."""
    deposits = data.get("sight_deposits", [])
    if len(deposits) < 2:
        return None
    last = deposits[-1].get("domestic")
    prev = deposits[-2].get("domestic")
    if last is not None and prev is not None:
        return abs(last - prev) / 1000  # M to B
    return None


def _cumulative_deposits(data: dict) -> float | None:
    """Cumulative domestic deposit change over available window in B CHF."""
    deposits = data.get("sight_deposits", [])
    if len(deposits) < 2:
        return None
    first_dom = None
    last_dom = None
    for d in deposits:
        dom = d.get("domestic")
        if dom is not None:
            if first_dom is None:
                first_dom = dom
            last_dom = dom
    if first_dom is not None and last_dom is not None:
        return abs(last_dom - first_dom) / 1000
    return None


# ---------------------------------------------------------------------------
# Per-currency indicator definitions
# ---------------------------------------------------------------------------

def _indicators_usd(data: dict) -> dict[str, tuple[float | None, list[tuple[float, float]]]]:
    """Return USD indicators as {name: (raw_value, breakpoints)}."""
    be_5y = _safe_get(data, "daily_indicators", "breakeven_5y", "value")
    be_10y = _safe_get(data, "daily_indicators", "breakeven_10y", "value")
    us_2y = _safe_get(data, "daily_indicators", "us_2y", "value")
    us_10y = _safe_get(data, "daily_indicators", "us_10y", "value")
    vix = _safe_get(data, "daily_indicators", "vix", "value")
    fed_eff = _safe_get(data, "fed_rates", "effective")
    snb_val = _safe_get(data, "snb_rate", "value") or 0.0
    unemployment = _safe_get(data, "macro_indicators", "unemployment", "value")

    be_distance = abs(be_5y - 2.0) if be_5y is not None else None
    curve_2s10s = (us_10y - us_2y) if us_2y is not None and us_10y is not None else None
    real_rate = (us_10y - be_10y) if us_10y is not None and be_10y is not None else None
    be_slope = (be_5y - be_10y) if be_5y is not None and be_10y is not None else None
    carry = (fed_eff - snb_val) if fed_eff is not None else None

    # Rate volatility: use daily_history if available
    rate_vol = None
    hist_2y = data.get("daily_history", {}).get("us_2y", [])
    if len(hist_2y) >= 2:
        last = hist_2y[-1].get("value")
        prev = hist_2y[-2].get("value")
        if last is not None and prev is not None:
            rate_vol = abs(last - prev)

    return {
        "inflation": {
            "breakeven_5y_distance": (be_distance, _BP_BREAKEVEN_DISTANCE),
            "breakeven_5y_level": (be_5y, _BP_BREAKEVEN_LEVEL),
            "breakeven_slope": (be_slope, _BP_BREAKEVEN_SLOPE),
        },
        "policy": {
            "fed_rate_level": (fed_eff, _BP_FED_RATE),
            "curve_slope_2s10s": (curve_2s10s, _BP_CURVE_2S10S),
            "real_rate": (real_rate, _BP_REAL_RATE),
        },
        "liquidity": {
            "vix_level": (vix, _BP_VIX),
            "fed_bns_carry": (carry, _BP_CARRY_FED_BNS),
            "rate_volatility": (rate_vol, _BP_RATE_VOL),
        },
        "growth": {
            "curve_shape_signal": (curve_2s10s, _BP_CURVE_2S10S),
            "unemployment_level": (unemployment, _BP_UNEMPLOYMENT),
        },
    }


def _indicators_eur(data: dict) -> dict[str, dict[str, tuple[float | None, list]]]:
    """Return EUR indicators."""
    ecb_deposit = _safe_get(data, "ecb_rates", "deposit_facility")
    fed_eff = _safe_get(data, "fed_rates", "effective")
    vix = _safe_get(data, "daily_indicators", "vix", "value")
    eur_chf = _safe_get(data, "eur_chf_latest", "value")
    snb_val = _safe_get(data, "snb_rate", "value") or 0.0
    brent_hist = data.get("brent_history", [])
    brent = brent_hist[-1]["value"] if brent_hist else None
    eur_chf_hist = data.get("eur_chf_history", [])
    eur_momentum = _pct_change_30d(eur_chf_hist)

    spread_fed_ecb = (fed_eff - ecb_deposit) if fed_eff is not None and ecb_deposit is not None else None
    carry_ecb_bns = (ecb_deposit - snb_val) if ecb_deposit is not None else None

    return {
        "inflation": {
            "ecb_rate_vs_neutral": (abs(ecb_deposit - 2.0) if ecb_deposit is not None else None, _BP_BREAKEVEN_DISTANCE),
            "brent_energy_pressure": (brent, _BP_BRENT_ENERGY),
        },
        "policy": {
            "ecb_rate_level": (ecb_deposit, _BP_ECB_RATE),
            "fed_ecb_spread": (spread_fed_ecb, _BP_SPREAD_FED_ECB),
            "eur_chf_level": (eur_chf, _BP_EUR_CHF_STRESS),
        },
        "liquidity": {
            "vix_level": (vix, _BP_VIX),
            "ecb_bns_carry": (carry_ecb_bns, _BP_CARRY_ECB_BNS),
        },
        "growth": {
            "eur_chf_momentum": (eur_momentum, _BP_FX_MOMENTUM),
        },
    }


def _indicators_chf(data: dict) -> dict[str, dict[str, tuple[float | None, list]]]:
    """Return CHF indicators."""
    snb_val = _safe_get(data, "snb_rate", "value")
    if snb_val is None:
        snb_val = 0.0
    vix = _safe_get(data, "daily_indicators", "vix", "value")
    usd_chf_hist = data.get("usd_chf_history", [])
    usd_chf = usd_chf_hist[-1]["value"] if usd_chf_hist else None
    eur_chf = _safe_get(data, "eur_chf_latest", "value")
    usd_momentum = _pct_change_30d(usd_chf_hist)
    wow = _wow_change(data)
    cumulative = _cumulative_deposits(data)

    return {
        "inflation": {
            "snb_rate_level": (snb_val, _BP_SNB_RATE),
        },
        "policy": {
            "snb_rate_policy": (snb_val, _BP_SNB_RATE),
            "intervention_signal": (wow, _BP_INTERVENTION),
        },
        "liquidity": {
            "usd_chf_level": (usd_chf, _BP_USD_CHF_STRESS),
            "eur_chf_level": (eur_chf, _BP_EUR_CHF_STRESS),
            "sight_deposit_cumulative": (cumulative, _BP_DEPOSIT_CUMULATIVE),
        },
        "growth": {
            "usd_chf_momentum": (usd_momentum, _BP_USD_CHF_MOMENTUM),
        },
    }


def _indicators_gbp(data: dict) -> dict[str, dict[str, tuple[float | None, list]]]:
    """Return GBP indicators."""
    vix = _safe_get(data, "daily_indicators", "vix", "value")
    fed_eff = _safe_get(data, "fed_rates", "effective")
    ecb_deposit = _safe_get(data, "ecb_rates", "deposit_facility")
    brent_hist = data.get("brent_history", [])
    brent = brent_hist[-1]["value"] if brent_hist else None
    gbp_chf_hist = data.get("gbp_chf_history", [])
    gbp_chf = gbp_chf_hist[-1]["value"] if gbp_chf_hist else None
    gbp_momentum = _pct_change_30d(gbp_chf_hist)
    uk_unemployment = _safe_get(data, "macro_indicators", "uk_unemployment", "value")
    spread = (fed_eff - ecb_deposit) if fed_eff is not None and ecb_deposit is not None else None

    return {
        "inflation": {
            "brent_energy_pressure": (brent, _BP_BRENT_ENERGY),
        },
        "policy": {
            "gbp_chf_level": (gbp_chf, _BP_GBP_CHF_STRESS),
            "fed_ecb_spread": (spread, _BP_SPREAD_FED_ECB),
        },
        "liquidity": {
            "vix_level": (vix, _BP_VIX),
            "gbp_chf_momentum": (gbp_momentum, _BP_FX_MOMENTUM),
        },
        "growth": {
            "uk_unemployment": (uk_unemployment, _BP_UNEMPLOYMENT),
        },
    }


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _score_family(
    name: str,
    indicators: dict[str, tuple[float | None, list[tuple[float, float]]]],
    config: dict[str, Any],
) -> FamilyScore:
    """Score one indicator family."""
    scores: dict[str, float | None] = {}
    missing: list[str] = []

    for ind_name, (raw_value, breakpoints) in indicators.items():
        score = normalize(raw_value, breakpoints)
        scores[ind_name] = score
        if score is None:
            missing.append(ind_name)

    # Average non-None scores
    valid_scores = [s for s in scores.values() if s is not None]
    if valid_scores:
        avg = sum(valid_scores) / len(valid_scores)
    else:
        avg = 50.0  # neutral if all missing

    # Confidence check
    total_indicators = len(indicators)
    threshold = config.get("low_confidence_threshold", 0.5)
    confidence = "low" if total_indicators > 0 and len(missing) / total_indicators > threshold else "high"

    label = _assign_label(avg, config)

    return FamilyScore(
        name=name,
        score=round(avg, 1),
        label=label,
        confidence=confidence,
        indicators={k: round(v, 1) if v is not None else None for k, v in scores.items()},
        missing=missing,
    )


def _score_currency(
    currency: str,
    family_indicators: dict[str, dict[str, tuple[float | None, list]]],
    config: dict[str, Any],
) -> CurrencyScore:
    """Score all families for one currency and compute composite."""
    families: dict[str, FamilyScore] = {}

    for family_name, indicators in family_indicators.items():
        families[family_name] = _score_family(family_name, indicators, config)

    # Composite: average of family scores
    family_scores = [f.score for f in families.values()]
    composite = sum(family_scores) / len(family_scores) if family_scores else 50.0
    label = _assign_label(composite, config)

    # Driver: highest-scoring family
    driver = max(families.values(), key=lambda f: f.score).name if families else ""

    return CurrencyScore(
        currency=currency,
        composite=round(composite, 1),
        label=label,
        families=families,
        driver=driver,
    )


def compute_scores(data: dict[str, Any]) -> dict[str, CurrencyScore]:
    """Compute per-currency scores from market data.

    Args:
        data: Latest snapshot data (from latest_snapshot.json).

    Returns:
        Dict mapping currency code to CurrencyScore.
        Keys: "USD", "EUR", "CHF", "GBP".
    """
    config = SCORING_LABELS

    extractors = {
        "USD": _indicators_usd,
        "EUR": _indicators_eur,
        "CHF": _indicators_chf,
        "GBP": _indicators_gbp,
    }

    scores: dict[str, CurrencyScore] = {}
    for currency, extractor in extractors.items():
        try:
            family_indicators = extractor(data)
            scores[currency] = _score_currency(currency, family_indicators, config)
        except Exception as e:
            logger.warning(f"Scoring failed for {currency}: {e}")
            scores[currency] = CurrencyScore(
                currency=currency, composite=50.0, label="Watch",
                driver="error",
            )

    logger.info(
        "Scores: " + " | ".join(
            f"{c}: {s.label} ({s.composite:.0f})" for c, s in scores.items()
        )
    )
    return scores
