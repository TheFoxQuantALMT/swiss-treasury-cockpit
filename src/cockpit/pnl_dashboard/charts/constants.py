"""Shared constants and imports for chart data builders."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Currency color palette (consistent with cockpit)
CURRENCY_COLORS = {
    "CHF": "#d62828",
    "EUR": "#e67e22",
    "USD": "#002868",
    "GBP": "#6f42c1",
}

LEG_COLORS = {
    "IAM/LD-NHCD": "#58a6ff",
    "IAM/LD-HCD": "#3fb950",
    "BND-NHCD": "#d29922",
    "BND-HCD": "#f0883e",
}

PRODUCT_COLORS = {
    "IAM/LD": "#58a6ff",
    "BND": "#3fb950",
    "FXS": "#d29922",
    "IRS": "#f0883e",
    "IRS-MTM": "#a5d6ff",
    "HCD": "#8b949e",
}

PERIMETER_COLORS = {
    "CC": "#58a6ff",
    "WM": "#3fb950",
    "CIB": "#d29922",
}
