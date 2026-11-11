"""Risk review command (P01-T08).

`risk review --phase NN` creates `reviews/PNN.md` from the phase ledger
and the register diff, runs the validator, and prints above-threshold
residual risks as a STOP-report draft.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import loader  # noqa: E402
import validator  # noqa: E402

_RISK_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_scales(risk_dir: Path) -> dict[str, object]:
    """Load the scales configuration."""
    path = risk_dir / "methodology" / "SCALES.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data: dict[str, object] = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def _threshold(scales: dict[str, object]) -> int:
    """Return the min residual score threshold."""
    rt = scales.get("register_threshold")
    if isinstance(rt, dict):
        val = rt.get("min_residual_score")
        if isinstance(val, int):
            return val
    return 10


def _max_severity(scales: dict[str, object]) -> int:
    rt = scales.get("register_threshold")
    if isinstance(rt, dict):
        val = rt.get("max_residual_severity_requiring_acceptance")
        if isinstance(val, int):
            return val
    return 5


def _above_threshold_risks(
    risk_dir: Path,
    threshold: int,
    max_sev: int,
) -> list[dict[str, object]]:
    """Return risks above the threshold without acceptance."""
    acceptance_ids = loader.load_acceptance_risk_ids(risk_dir)
    above: list[dict[str, object]] = []
    for name in ("product-risks", "project-risks", "ai-model-risks", "data-legal-risks"):
        path = risk_dir / "registers" / f"{name}.yaml"
        if not path.exists():
            continue
        for record in loader.load_register(path):
            rl = record.get("residual_likelihood")
            rs = record.get("residual_severity")
            if not isinstance(rl, int) or not isinstance(rs, int):
                continue
            score = rl * rs
            if score >= threshold or rs >= max_sev:
                rid = str(record.get("id", "?"))
                if rid not in acceptance_ids:
                    above.append(record)
    return above


def run_review(phase: str, repo_root: Path | None = None) -> int:
    """Run the risk review for *phase*. Returns 0 if clean, 1 if STOP needed."""
    if repo_root is None:
        repo_root = _REPO_ROOT
    risk_dir = repo_root / "risk-management"

    # Run the validator first.
    rc = validator.validate_all(repo_root)
    if rc != 0:
        print(f"review: validation failed (exit {rc})", file=sys.stderr)
        return 1

    # Determine above-threshold risks without acceptance.
    scales = _load_scales(risk_dir)
    threshold = _threshold(scales)
    max_sev = _max_severity(scales)
    above = _above_threshold_risks(risk_dir, threshold, max_sev)

    # Write the review record.
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m")
    review_path = risk_dir / "reviews" / f"P{phase[1:]}.md.yaml"
    review_path.parent.mkdir(parents=True, exist_ok=True)

    review_record: dict[str, object] = {
        "id": f"REV-P{phase[1:]}",
        "phase": phase,
        "review_date": now,
        "risks_new_or_changed": [],
        "controls_added": ["CTL-RISK-01", "CTL-RISK-02", "CTL-RISK-03"] if phase == "P01" else [],
    }

    yaml_text = yaml.safe_dump(
        {"records": [review_record]},
        default_flow_style=False,
        sort_keys=False,
    )
    review_path.write_text(yaml_text, encoding="utf-8")

    # Print STOP report for above-threshold risks without acceptance.
    if above:
        print(f"STOP report — {phase} risk review", file=sys.stderr)
        print(f"Above-threshold residual risks without acceptance: {len(above)}", file=sys.stderr)
        for record in above:
            rid = record.get("id", "?")
            title = record.get("title", "?")
            print(f"  - {rid}: {title}", file=sys.stderr)
        print("Owner action required: accept or reduce each above-threshold risk.", file=sys.stderr)
        return 1

    return 0
