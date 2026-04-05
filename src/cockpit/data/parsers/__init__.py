from cockpit.data.parsers.mtd import parse_mtd, parse_deals
from cockpit.data.parsers.echeancier import parse_echeancier, parse_schedule
from cockpit.data.parsers.wirp import parse_wirp, parse_wirp_ideal
from cockpit.data.parsers.irs_stock import parse_irs_stock
from cockpit.data.parsers.reference_table import parse_reference_table
from pnl_engine.engine import _month_columns

__all__ = [
    # Ideal format parsers
    "parse_deals",
    "parse_schedule",
    "parse_wirp_ideal",
    # Legacy format parsers (auto-detect ideal format and delegate)
    "parse_mtd",
    "parse_echeancier",
    "parse_wirp",
    # Utilities
    "_month_columns",
    # Kept for backward compat (IRS now in deals.xlsx for ideal format)
    "parse_irs_stock",
    "parse_reference_table",
]
