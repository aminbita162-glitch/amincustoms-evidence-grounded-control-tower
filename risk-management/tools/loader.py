"""File loader for the risk management system (P01-T02).

Loads YAML register files and JSON schema files from the risk-management
directory. Provides helpers for parsing the test index.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_RISK_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def load_yaml(path: Path) -> object:
    """Load a YAML file and return its contents."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(name: str) -> dict[str, object]:
    """Load a JSON schema file by name from risk-management/schemas/.

    Args:
        name: schema name without extension (e.g. 'risk', 'control').
    """
    path = _RISK_DIR / "schemas" / f"{name}.json"
    with path.open("r", encoding="utf-8") as f:
        result: dict[str, object] = json.load(f)
        return result


def load_register(path: Path) -> list[dict[str, object]]:
    """Load a YAML register file and return a list of records.

    A register file has a top-level 'records' key containing a list,
    or is itself a list of records.
    """
    if not path.exists():
        return []
    data = load_yaml(path)
    if isinstance(data, dict) and "records" in data:
        records = data["records"]
    elif isinstance(data, list):
        records = data
    else:
        return []
    if not isinstance(records, list):
        return []
    result: list[dict[str, object]] = []
    for r in records:
        if isinstance(r, dict):
            result.append(r)
    return result


def load_test_ids(index_path: Path | None = None) -> set[str]:
    """Parse test ids from the test-house INDEX.md file.

    Extracts the first column (id) from each row of the markdown table.
    """
    if index_path is None:
        index_path = _REPO_ROOT / "test-house" / "INDEX.md"
    if not index_path.exists():
        return set()
    text = index_path.read_text(encoding="utf-8")
    ids: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("| T-"):
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 2 and parts[1].startswith("T-"):
                ids.add(parts[1])
    return ids


def load_all_control_ids() -> set[str]:
    """Load all control ids from the control catalogue."""
    catalogue_path = _RISK_DIR / "controls" / "catalogue.yaml"
    if not catalogue_path.exists():
        return set()
    records = load_register(catalogue_path)
    ids: set[str] = set()
    for r in records:
        rid = r.get("id")
        if isinstance(rid, str) and rid:
            ids.add(rid)
    return ids
