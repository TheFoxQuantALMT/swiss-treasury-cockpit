import pandas as pd
from cockpit.data.parsers import parse_reference_table
from pathlib import Path
import tempfile


def _write_ref_excel(path: Path) -> None:
    df = pd.DataFrame({
        "counterparty": ["THCCBFIGE", "WM-CLI-GE", "CLI-MT-CIB", "UNKNOWN-X"],
        "rating": ["AA+", "A", "BBB-", "NR"],
        "hqla_level": ["L1", "L2A", "L2B", "Non-HQLA"],
        "country": ["CH", "CH", "FR", "US"],
    })
    df.to_excel(path, index=False, engine="openpyxl")


def test_parse_reference_table():
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp = Path(f.name)
    _write_ref_excel(tmp)
    result = parse_reference_table(tmp)
    assert len(result) == 4
    assert list(result.columns) == ["counterparty", "rating", "hqla_level", "country"]
    assert result.iloc[0]["counterparty"] == "THCCBFIGE"
    assert result.iloc[0]["rating"] == "AA+"
    tmp.unlink()


def test_parse_reference_table_fills_missing():
    df = pd.DataFrame({
        "counterparty": ["ABC"],
        "rating": [None],
        "hqla_level": [None],
        "country": [None],
    })
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp = Path(f.name)
    df.to_excel(tmp, index=False, engine="openpyxl")
    result = parse_reference_table(tmp)
    assert result.iloc[0]["rating"] == "NR"
    assert result.iloc[0]["hqla_level"] == "Non-HQLA"
    assert result.iloc[0]["country"] == "XX"
    tmp.unlink()
