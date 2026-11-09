"""Secrets gate — runs the pinned secret scanner (P00-T06).

Runs ``gitleaks`` (pinned v8.30.1) on the current directory.  Exit codes:
0 if no secrets are found, 1 if secrets are found, 2 if the tool itself
errors (missing binary, invalid config, etc.).

When a ``secrets_result.json`` file exists in the current directory the gate
reads findings from it instead of invoking the scanner.  This allows the
selftest and unit tests to exercise the gate's result logic without
network access or the external binary.

Invokable as ``python -m tools.gate.gates.secrets``.

Spec: Part 4 §4.12, Part 6 §6.13.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

__all__ = [
    "SecretsResult",
    "parse_findings",
    "run_gitleaks",
    "main",
]


class SecretsResult(Exception):
    """A secrets gate tool error."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_findings(raw: object) -> list[dict[str, object]]:
    """Parse a gitleaks JSON report into a list of finding dicts."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return [f for f in raw if isinstance(f, dict)]
    if isinstance(raw, dict):
        findings = raw.get("Results") or raw.get("results") or raw.get("findings")
        if isinstance(findings, list):
            return [f for f in findings if isinstance(f, dict)]
        if findings is None:
            return []
    return []


def run_gitleaks(cwd: Path) -> tuple[int, list[dict[str, object]], str | None]:
    """Run ``gitleaks detect`` in *cwd*.

    Returns ``(exit_code, findings, error_message)``.
    """
    gitleaks = _gate_dir() / ".venv" / "bin" / "gitleaks"
    if not gitleaks.is_file():
        gitleaks = Path("gitleaks")
    cmd: list[str] = [
        str(gitleaks),
        "detect",
        "--source",
        str(cwd),
        "--no-git",
        "--report-format",
        "json",
        "--report-path",
        "/dev/stdout",
        "--no-banner",
        "--exit-code",
        "0",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        return 2, [], "gitleaks not found"
    except subprocess.TimeoutExpired:
        return 2, [], "gitleaks timed out"
    if proc.returncode not in (0, 1):
        return 2, [], proc.stderr.strip() or "gitleaks error"
    try:
        raw = json.loads(proc.stdout) if proc.stdout.strip() else []
    except json.JSONDecodeError:
        return 2, [], "invalid gitleaks JSON output"
    findings = parse_findings(raw)
    return (1 if findings else 0, findings, None)


def main() -> int:
    """Entry point for the secrets gate."""
    cwd = Path.cwd()

    # Pre-computed result file (for selftest / unit tests).
    result_file = cwd / "secrets_result.json"
    if result_file.is_file():
        try:
            raw: object = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("secrets: invalid secrets_result.json", file=sys.stderr)
            return 2
        findings = parse_findings(raw)
        if findings:
            for f in findings:
                file_path = f.get("file") or f.get("File") or "<unknown>"
                print(f"secrets: FAIL {file_path}")
            return 1
        print("secrets: PASS")
        return 0

    exit_code, findings, error = run_gitleaks(cwd)
    if exit_code == 2:
        print(f"secrets: ERROR {error}", file=sys.stderr)
        return 2
    if findings:
        for f in findings:
            file_path = f.get("file") or f.get("File") or "<unknown>"
            print(f"secrets: FAIL {file_path}")
        return 1
    print("secrets: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
