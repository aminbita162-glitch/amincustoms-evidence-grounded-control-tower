"""Risk management CLI for the Customs and Transit Control Tower.

Subcommands:
    risk validate scales       validate methodology/SCALES.yaml
    risk check-phrases <path>  scan a file for forbidden compliance phrases
    risk validate registers    validate all register files
    risk validate reviews      validate review records
    risk validate controls     validate the control catalogue
    risk validate all          run every validation
    risk report                generate RESIDUAL.md, HEALTH.md, INDEX.md
    risk review --phase NN     create a phase risk review record
    risk health                print process-health summary

Exit codes: 0 success, 1 validation failure, 2 misconfiguration.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import validator  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RISK_DIR = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> object:
    """Load a YAML file and return its contents."""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_scales(scales_path: Path | None = None) -> int:
    """Validate the scales configuration.

    Checks that the likelihood and severity scales each have values 1 to 5
    with anchors, the score rule is likelihood_times_severity, the range is
    [1, 25], bands cover the full range without gaps or overlaps, the
    register threshold is present, and the review cadence is present.
    """
    if scales_path is None:
        env_path = os.environ.get("SCALES_PATH")
        scales_path = Path(env_path) if env_path else _RISK_DIR / "methodology" / "SCALES.yaml"
    if not scales_path.exists():
        print(f"scales: file not found at {scales_path}", file=sys.stderr)
        return 2
    data = _load_yaml(scales_path)
    if not isinstance(data, dict):
        print("scales: top-level must be a mapping", file=sys.stderr)
        return 1
    errors: list[str] = []
    for section in ("likelihood", "severity"):
        section_data = data.get(section)
        if not isinstance(section_data, dict):
            errors.append(f"{section}: missing or not a mapping")
            continue
        scale = section_data.get("scale")
        if not isinstance(scale, list) or len(scale) != 5:
            errors.append(f"{section}.scale: must be a list of 5 entries")
            continue
        values = [entry.get("value") for entry in scale]
        if values != [1, 2, 3, 4, 5]:
            errors.append(f"{section}.scale: values must be [1, 2, 3, 4, 5], got {values}")
        for entry in scale:
            if not entry.get("label"):
                errors.append(f"{section}.scale[{entry.get('value')}]: missing label")
            if not entry.get("anchor"):
                errors.append(f"{section}.scale[{entry.get('value')}]: missing anchor")
    score = data.get("score")
    if not isinstance(score, dict):
        errors.append("score: missing or not a mapping")
    else:
        if score.get("rule") != "likelihood_times_severity":
            errors.append(
                f"score.rule: must be 'likelihood_times_severity', got {score.get('rule')}"
            )
        if score.get("range") != [1, 25]:
            errors.append(f"score.range: must be [1, 25], got {score.get('range')}")
    bands = data.get("bands")
    if not isinstance(bands, list) or len(bands) != 4:
        errors.append("bands: must be a list of 4 entries")
    else:
        expected_names = ["low", "medium", "high", "critical"]
        expected_ranges = [[1, 4], [5, 9], [10, 14], [15, 25]]
        for i, (band, exp_name, exp_range) in enumerate(
            zip(bands, expected_names, expected_ranges, strict=False)
        ):
            if band.get("name") != exp_name:
                errors.append(f"bands[{i}].name: must be '{exp_name}', got {band.get('name')}")
            if band.get("range") != exp_range:
                errors.append(f"bands[{i}].range: must be {exp_range}, got {band.get('range')}")
    threshold = data.get("register_threshold")
    if not isinstance(threshold, dict):
        errors.append("register_threshold: missing or not a mapping")
    else:
        if not isinstance(threshold.get("min_residual_score"), int):
            errors.append("register_threshold.min_residual_score: must be an integer")
        if not isinstance(threshold.get("max_residual_severity_requiring_acceptance"), int):
            errors.append(
                "register_threshold.max_residual_severity_requiring_acceptance: must be an integer"
            )
    if not isinstance(data.get("review_cadence"), dict):
        errors.append("review_cadence: missing or not a mapping")
    if not isinstance(data.get("treatment_order"), list):
        errors.append("treatment_order: missing or not a list")
    if not isinstance(data.get("control_lifecycle"), list):
        errors.append("control_lifecycle: missing or not a list")
    if errors:
        for e in errors:
            print(f"scales: {e}", file=sys.stderr)
        return 1
    return 0


FORBIDDEN_PHRASES: tuple[str, ...] = (
    "compliant with",
    "in compliance with",
    "certified",
    "conforms to",
    "conformant",
    "meets the requirements of",
    "guarantees",
    "guaranteed",
    "risk-free",
    "no risk",
    "fully mitigated",
    "eliminates all",
)


def check_forbidden_phrases(text: str) -> list[str]:
    """Return a list of forbidden phrases found in *text* (case-insensitive)."""
    lower = text.lower()
    found: list[str] = []
    for phrase in FORBIDDEN_PHRASES:
        if phrase in lower:
            found.append(phrase)
    return found


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("usage: risk <command> [args]", file=sys.stderr)
        return 2
    command = argv[0]
    if command == "validate":
        if len(argv) < 2:
            print("usage: risk validate <what>", file=sys.stderr)
            return 2
        what = argv[1]
        if what == "scales":
            return validate_scales()
        if what == "all":
            rc_scales = validate_scales()
            rc_all = validator.validate_all(_REPO_ROOT)
            return rc_scales if rc_scales else rc_all
        if what == "registers":
            return validator.validate_all(_REPO_ROOT)
        if what == "controls":
            return validator.validate_all(_REPO_ROOT)
        if what == "reviews":
            return validator.validate_all(_REPO_ROOT)
        print(f"validate: unknown target '{what}'", file=sys.stderr)
        return 2
    if command == "check-phrases":
        if len(argv) < 2:
            print("usage: risk check-phrases <path>", file=sys.stderr)
            return 2
        path = Path(argv[1])
        if not path.exists():
            print(f"check-phrases: file not found at {path}", file=sys.stderr)
            return 2
        text = path.read_text(encoding="utf-8")
        found = check_forbidden_phrases(text)
        if found:
            for phrase in found:
                print(f"check-phrases: forbidden phrase '{phrase}' in {path}", file=sys.stderr)
            return 1
        return 0
    if command == "report":
        import report  # noqa: E402

        return report.generate_all(_REPO_ROOT)
    if command == "review":
        import review  # noqa: E402

        if len(argv) < 3 or argv[1] != "--phase":
            print("usage: risk review --phase NN", file=sys.stderr)
            return 2
        return review.run_review(argv[2], _REPO_ROOT)
    if command == "health":
        import health  # noqa: E402

        return health.run_health(_REPO_ROOT)
    print(f"risk: unknown command '{command}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
