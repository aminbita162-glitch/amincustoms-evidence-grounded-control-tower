"""Dependency audit gate — runs the pinned audit tool (P00-T06).

Runs ``pip-audit`` (pinned 2.10.1) on the project's dependencies and fails on
any finding without an unexpired exception in ``tools/gate/exceptions.toml``.

When a ``deps_audit.json`` file exists in the current directory the gate
reads findings from it instead of invoking the audit tool.  This allows the
selftest and unit tests to exercise the gate's exception logic without
network access.

Invokable as ``python -m tools.gate.gates.deps``.

Spec: Part 4 §4.12, Part 6 §6.13.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
import tomllib
from pathlib import Path

__all__ = [
    "DepsError",
    "load_exceptions",
    "parse_audit",
    "run_pip_audit",
    "is_expired",
    "main",
]


class DepsError(Exception):
    """A deps gate error."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def load_exceptions(path: Path) -> list[dict[str, str]]:
    """Load exception entries from ``exceptions.toml``.

    Each entry has: package, vulnerability_id, reason, owner_decision_id, expiry.
    Returns an empty list when the file has no entries (P00 default).
    """
    if not path.is_file():
        return []
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise DepsError(f"cannot load exceptions.toml: {exc}") from exc
    if not isinstance(raw, dict):
        return []
    entries_raw = raw.get("exceptions")
    if not isinstance(entries_raw, list):
        return []
    entries: list[dict[str, str]] = []
    for entry in entries_raw:
        if isinstance(entry, dict):
            entries.append(
                {
                    "package": str(entry.get("package", "")),
                    "vulnerability_id": str(entry.get("vulnerability_id", "")),
                    "reason": str(entry.get("reason", "")),
                    "owner_decision_id": str(entry.get("owner_decision_id", "")),
                    "expiry": str(entry.get("expiry", "")),
                }
            )
    return entries


def is_expired(expiry: str, today: _dt.date | None = None) -> bool:
    """Return True if *expiry* (YYYY-MM-DD) is on or before *today*."""
    if not expiry:
        return True
    if today is None:
        today = _dt.date.today()
    try:
        exp_date = _dt.date.fromisoformat(expiry)
    except ValueError:
        return True
    return exp_date <= today


def parse_audit(raw: object) -> list[dict[str, object]]:
    """Parse a pip-audit JSON report into a flat list of dependency dicts.

    Each dict has: name, version, vulns (list of {id, fix_versions}).
    """
    if not isinstance(raw, dict):
        return []
    deps_raw = raw.get("dependencies") or raw.get("Dependencies")
    if not isinstance(deps_raw, list):
        return []
    deps: list[dict[str, object]] = []
    for dep in deps_raw:
        if not isinstance(dep, dict):
            continue
        vulns_raw = dep.get("vulns") or dep.get("Vulns") or []
        vulns: list[dict[str, object]] = []
        if isinstance(vulns_raw, list):
            for v in vulns_raw:
                if isinstance(v, dict):
                    vulns.append(
                        {
                            "id": str(v.get("id") or v.get("vuln_id") or ""),
                            "fix_versions": list(
                                v.get("fix_versions") or v.get("FixVersions") or []
                            ),
                        }
                    )
        deps.append(
            {
                "name": str(dep.get("name") or dep.get("Name") or ""),
                "version": str(dep.get("version") or dep.get("Version") or ""),
                "vulns": vulns,
            }
        )
    return deps


def run_pip_audit(cwd: Path) -> tuple[int, list[dict[str, object]], str | None]:
    """Run ``pip-audit`` on the project in *cwd*.

    Returns ``(exit_code, deps, error_message)``.
    """
    cmd: list[str] = [sys.executable, "-m", "pip_audit", "--format", "json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(cwd),
        )
    except FileNotFoundError:
        return 2, [], "pip-audit not found"
    except subprocess.TimeoutExpired:
        return 2, [], "pip-audit timed out"
    if proc.returncode not in (0, 1):
        return 2, [], proc.stderr.strip() or "pip-audit error"
    try:
        raw: object = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return 2, [], "invalid pip-audit JSON output"
    deps = parse_audit(raw)
    return (1 if deps else 0, deps, None)


def _has_unexpired_exception(
    package: str,
    vuln_id: str,
    exceptions: list[dict[str, str]],
) -> bool:
    """Check whether *package*/*vuln_id* has an unexpired exception."""
    for exc in exceptions:
        if (
            exc["package"] == package
            and exc["vulnerability_id"] == vuln_id
            and not is_expired(exc["expiry"])
        ):
            return True
    return False


def main() -> int:
    """Entry point for the deps gate."""
    cwd = Path.cwd()
    exceptions_path = _gate_dir() / "exceptions.toml"
    try:
        exceptions = load_exceptions(exceptions_path)
    except DepsError as exc:
        print(f"deps: ERROR {exc}", file=sys.stderr)
        return 2

    # Pre-computed result file (for selftest / unit tests).
    result_file = cwd / "deps_audit.json"
    if result_file.is_file():
        try:
            raw: object = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("deps: invalid deps_audit.json", file=sys.stderr)
            return 2
        deps = parse_audit(raw)
    else:
        exit_code, deps, error = run_pip_audit(cwd)
        if exit_code == 2:
            print(f"deps: ERROR {error}", file=sys.stderr)
            return 2

    unexcepted: list[str] = []
    for dep in deps:
        package = str(dep.get("name", ""))
        vulns: list[dict[str, object]] = dep.get("vulns", [])  # type: ignore[assignment]
        if not isinstance(vulns, list):
            vulns = []
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            vid = str(vuln.get("id", ""))
            if not _has_unexpired_exception(package, vid, exceptions):
                unexcepted.append(f"{package}@{dep.get('version', '')}:{vid}")

    if unexcepted:
        for item in unexcepted:
            print(f"deps: FAIL {item}")
        return 1
    print("deps: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
