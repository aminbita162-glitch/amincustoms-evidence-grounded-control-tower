"""Security gate — runs the pinned static analyzer (P00-T06).

Runs ``bandit`` (pinned 1.9.4) on the current directory with the project's
rule configuration.  No rules are downloaded at run time — only bandit's
built-in rules and the local ``tools/gate/bandit.yaml`` config are used.

A seeded ``yaml.unsafe_load`` fixture must fail the gate.

Invokable as ``python -m tools.gate.gates.security``.

Spec: Part 4 §4.12, Part 6 §6.13.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

__all__ = [
    "run_bandit",
    "main",
]


class SecurityError(Exception):
    """A security gate tool error."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def run_bandit(cwd: Path) -> tuple[int, list[dict[str, object]], str | None]:
    """Run ``bandit -r .`` in *cwd* with the project config.

    Returns ``(exit_code, findings, error_message)``.
    *exit_code* is 0 (clean), 1 (issues found) or 2 (tool error).
    """
    config = _gate_dir() / "bandit.yaml"
    cmd: list[str] = [sys.executable, "-m", "bandit", "-r", str(cwd), "-f", "json"]
    if config.is_file():
        cmd.extend(["-c", str(config)])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(_repo_root()),
        )
    except FileNotFoundError:
        return 2, [], "bandit not found"
    except subprocess.TimeoutExpired:
        return 2, [], "bandit timed out"
    if proc.returncode not in (0, 1):
        return 2, [], proc.stderr.strip() or "bandit error"
    try:
        raw: object = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return 2, [], "invalid bandit JSON output"
    results: list[dict[str, object]] = []
    if isinstance(raw, dict):
        raw_results = raw.get("results", [])
        if isinstance(raw_results, list):
            results = [r for r in raw_results if isinstance(r, dict)]
    return (1 if results else 0, results, None)


def main() -> int:
    """Entry point for the security gate."""
    cwd = Path.cwd()
    exit_code, findings, error = run_bandit(cwd)
    if exit_code == 2:
        print(f"security: ERROR {error}", file=sys.stderr)
        return 2
    if findings:
        for f in findings:
            file_path = f.get("filename") or "<unknown>"
            print(f"security: FAIL {file_path}")
        return 1
    print("security: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
