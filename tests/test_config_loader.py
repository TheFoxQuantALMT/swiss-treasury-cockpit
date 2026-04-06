"""Tests for cockpit.config_loader."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cockpit.config_loader import DEFAULTS, load_config, reset_cache, _deep_merge


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level cache before each test."""
    reset_cache()
    yield
    reset_cache()


class TestDeepMerge:
    def test_flat_override(self):
        assert _deep_merge({"a": 1, "b": 2}, {"b": 3}) == {"a": 1, "b": 3}

    def test_nested_override(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 99}}
        assert _deep_merge(base, override) == {"x": {"a": 1, "b": 99}}

    def test_new_key(self):
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_non_destructive(self):
        base = {"a": {"nested": 1}}
        _deep_merge(base, {"a": {"nested": 2}})
        assert base["a"]["nested"] == 1  # original unchanged


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "nonexistent.yaml", use_cache=False)
        assert cfg == DEFAULTS

    def test_empty_file_returns_defaults(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        cfg = load_config(f, use_cache=False)
        assert cfg == DEFAULTS

    def test_partial_override(self, tmp_path):
        f = tmp_path / "partial.yaml"
        f.write_text(textwrap.dedent("""\
            cds_alert_threshold_bps: 300
            scoring_labels:
              calm_max: 50
        """))
        cfg = load_config(f, use_cache=False)
        assert cfg["cds_alert_threshold_bps"] == 300
        assert cfg["scoring_labels"]["calm_max"] == 50
        # Non-overridden keys keep defaults
        assert cfg["scoring_labels"]["watch_max"] == 70
        assert cfg["fx_alert_bands"] == DEFAULTS["fx_alert_bands"]

    def test_full_override(self, tmp_path):
        f = tmp_path / "full.yaml"
        f.write_text(textwrap.dedent("""\
            analyst_model: "gpt-4"
            reviewer_model: "gpt-4"
            ollama_host: "http://remote:11434"
            max_review_retries: 5
        """))
        cfg = load_config(f, use_cache=False)
        assert cfg["analyst_model"] == "gpt-4"
        assert cfg["max_review_retries"] == 5

    def test_nested_fx_override(self, tmp_path):
        f = tmp_path / "fx.yaml"
        f.write_text(textwrap.dedent("""\
            fx_alert_bands:
              EUR_CHF: { low: 0.88, high: 0.98 }
        """))
        cfg = load_config(f, use_cache=False)
        assert cfg["fx_alert_bands"]["EUR_CHF"]["low"] == 0.88
        # Other pairs keep defaults
        assert cfg["fx_alert_bands"]["USD_CHF"] == DEFAULTS["fx_alert_bands"]["USD_CHF"]

    def test_cache_returns_same_object(self):
        cfg1 = load_config(use_cache=True)
        cfg2 = load_config(use_cache=True)
        assert cfg1 is cfg2

    def test_no_cache_returns_fresh(self):
        cfg1 = load_config(use_cache=False)
        cfg2 = load_config(use_cache=False)
        assert cfg1 == cfg2
        assert cfg1 is not cfg2


class TestConfigIntegration:
    """Verify that config.py successfully loads from the YAML."""

    def test_config_module_uses_loader(self):
        from cockpit import config
        # These should now come from config_loader
        assert isinstance(config.FX_ALERT_BANDS, dict)
        assert "EUR_CHF" in config.FX_ALERT_BANDS
        assert isinstance(config.SCORING_LABELS, dict)
        assert isinstance(config.ANALYST_MODEL, str)
        assert isinstance(config.CDS_ALERT_THRESHOLD_BPS, int)

    def test_config_values_match_yaml(self):
        from cockpit import config
        cfg = load_config(use_cache=False)
        assert config.FX_ALERT_BANDS == cfg["fx_alert_bands"]
        assert config.SCENARIOS == cfg["scenarios"]
        assert config.ANALYST_MODEL == cfg["analyst_model"]
