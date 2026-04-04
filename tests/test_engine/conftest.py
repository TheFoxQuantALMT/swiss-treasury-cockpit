from pathlib import Path

import pytest

# Re-use the sample data from the economic-pnl-v2 worktree if available.
_ECONOMIC_PNL_SAMPLE = Path(
    "/mnt/Projects/Projects/Treasury Macro Cockpit Design"
    "/.worktrees/economic-pnl-v2/202603/20260326"
)


@pytest.fixture
def sample_dir():
    return _ECONOMIC_PNL_SAMPLE


@pytest.fixture
def mtd_path(sample_dir):
    return sample_dir / "20260326_MTD Standard Liquidity PnL Report v1.2.xlsx"


@pytest.fixture
def echeancier_path(sample_dir):
    return sample_dir / "20260326_Echeancier Requête - Soldes mensuels - Pour projection PnL.xlsx"


@pytest.fixture
def wirp_path(sample_dir):
    return sample_dir / "20260326_WIRP.xlsx"


@pytest.fixture
def irs_path(sample_dir):
    return sample_dir / "20260326_IRS.xlsx"
