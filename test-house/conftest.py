"""Shared pytest configuration for the Control Tower test house (P00-T04)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TEST_HOUSE = Path(__file__).resolve().parent
if str(_TEST_HOUSE) not in sys.path:
    sys.path.insert(0, str(_TEST_HOUSE))


@pytest.fixture
def repo_root() -> Path:
    """The project repository root."""
    return _TEST_HOUSE.parent
