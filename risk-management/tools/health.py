"""Health summary command (P01-T08).

`risk health` generates HEALTH.md and prints a summary to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import report  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]


def run_health(repo_root: Path | None = None) -> int:
    """Generate HEALTH.md and print a summary. Returns 0 on success."""
    if repo_root is None:
        repo_root = _REPO_ROOT
    risk_dir = repo_root / "risk-management"
    health_path = risk_dir / "report" / "HEALTH.md"
    content = report.generate_health(risk_dir, repo_root)
    health_path.parent.mkdir(parents=True, exist_ok=True)
    health_path.write_text(content, encoding="utf-8")
    print(content)
    return 0
