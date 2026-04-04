"""Parser for Echeancier (forward balance schedule) Excel files."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _month_columns(df: pd.DataFrame) -> list[str]:
    """Return column names that look like 'YYYY/MM' date strings."""
    return [c for c in df.columns if isinstance(c, str) and "/" in c and c[:4].isdigit()]


def parse_echeancier(path: Path) -> pd.DataFrame:
    """Parse Echeancier → wide DataFrame with monthly balances, V-legs carried forward."""
    df = pd.read_excel(path, sheet_name="Operations Propres EoM", skiprows=2, engine="openpyxl")

    # Drop leading unnamed column
    first_col = df.columns[0]
    if str(first_col).startswith("Unnamed"):
        df = df.drop(columns=first_col)

    deal_col = df.columns[0]  # Deal Number KND
    df = df.dropna(subset=[deal_col])

    # Parse deal type and ID
    df[["Deal Type", "Dealid"]] = df[deal_col].astype(str).str.split("@", expand=True)
    df["Dealid"] = pd.to_numeric(df["Dealid"], errors="coerce")

    rate_type_col = [c for c in df.columns if "Rate Type" in str(c)]
    post_flag_col = [c for c in df.columns if "Post-counted" in str(c)]

    # Filter: drop RFR V-legs.  Two sub-cases:
    #   (a) Post-counted interest flag == 1  (standard RFR reset leg)
    #   (b) Post-counted flag is NaN but Rate index Code is "RFR"
    # Both represent floating-rate resets that are not forecast-able and must
    # be excluded before carry-forward.
    rate_code_col = [c for c in df.columns if "level 1 Code" in str(c)]
    if rate_type_col:
        rt = df[rate_type_col[0]]
        pf = df[post_flag_col[0]].fillna(0) if post_flag_col else pd.Series(0, index=df.index)
        rc = df[rate_code_col[0]] if rate_code_col else pd.Series("", index=df.index)
        is_rfr_v = (rt == "V") & ((pf == 1) | (rc == "RFR"))
        df = df[~is_rfr_v].copy()

    # Filter: drop reverse repo V-legs
    level5_col = [c for c in df.columns if "level 5" in str(c)]
    if rate_type_col and level5_col:
        rt = df[rate_type_col[0]]
        l5 = df[level5_col[0]].fillna("")
        df = df[~((rt == "V") & (l5 == "Reverse repos"))].copy()

    # Direction: BD@ = Bond → B, else from balance sign (L if negative, D if positive)
    month_cols = _month_columns(df)
    is_bond = df["Deal Type"] == "BD"
    balance_sum = df[month_cols].sum(axis=1)
    df["Direction"] = np.where(is_bond, "B", np.where(balance_sum < 0, "L", "D"))

    # Currency (optional — column may not exist in all versions)
    curr_cols = [c for c in df.columns if "currency" in str(c).lower()]
    if curr_cols:
        df["Currency"] = df[curr_cols[0]]

    # V-leg carry-forward: fill NaN months forward with last known balance
    if rate_type_col:
        rt_col = rate_type_col[0]
        v_mask = df[rt_col] == "V"
        if v_mask.any():
            df.loc[v_mask, month_cols] = df.loc[v_mask, month_cols].ffill(axis=1)

    return df.reset_index(drop=True)
