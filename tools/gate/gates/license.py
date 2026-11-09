"""License gate — checks every dependency licence against the allowlist (P00-T06).

Allowed licences: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0,
MPL-2.0 (unmodified use only).  MIT-0, 0BSD, Zlib, CC0-1.0 are admitted only
for the two named transitive packages of decision D-37 (cffi, numpy).

The gate checks every package in the lock, direct and transitive.  A package
whose licence expression has any component outside the allowlist fails.
``docs/THIRD_PARTY_NOTICES.txt`` is generated from the lock and the vendored
assets; a stale file fails the gate.

When a ``lock.json`` file exists in the current directory the gate reads the
package list from it instead of introspecting the installed environment.
This allows the selftest and unit tests to exercise the licence logic without
network access.

Invokable as ``python -m tools.gate.gates.license``.

Spec: Part 4 §4.12, Part 6 §6.13.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

__all__ = [
    "ALLOWED_LICENSES",
    "D37_EXTRA_LICENSES",
    "D37_PACKAGES",
    "LicenseError",
    "check_licenses",
    "generate_notices",
    "load_lock",
    "main",
]


class LicenseError(Exception):
    """A license gate error."""


ALLOWED_LICENSES: frozenset[str] = frozenset(
    {
        "MIT",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "Apache-2.0",
        "ISC",
        "PSF-2.0",
        "MPL-2.0",
    }
)

D37_PACKAGES: frozenset[str] = frozenset({"cffi", "numpy"})
D37_EXTRA_LICENSES: frozenset[str] = frozenset({"MIT-0", "0BSD", "Zlib", "CC0-1.0"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _split_license_expression(expr: str) -> list[str]:
    """Split a licence expression like ``MIT OR Apache-2.0`` into components."""
    import re

    tokens = re.split(r"[\s/]+OR[\s/]+|[\s/]+AND[\s/]+", expr)
    return [t.strip() for t in tokens if t.strip()]


def _is_license_allowed(license_expr: str, package: str) -> bool:
    """Check whether *license_expr* is allowed for *package*."""
    if not license_expr:
        return False
    components = _split_license_expression(license_expr)
    if not components:
        components = [license_expr.strip()]
    allowed = set(ALLOWED_LICENSES)
    if package in D37_PACKAGES:
        allowed = allowed | D37_EXTRA_LICENSES
    return all(comp in allowed for comp in components)


def load_lock(path: Path) -> list[dict[str, str]]:
    """Load a ``lock.json`` file and return a list of package dicts.

    Each dict has: name, version, license.
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LicenseError(f"cannot load lock.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise LicenseError("lock.json is not an object")
    packages_raw = raw.get("packages")
    if not isinstance(packages_raw, list):
        raise LicenseError("lock.json missing 'packages' list")
    packages: list[dict[str, str]] = []
    for pkg in packages_raw:
        if isinstance(pkg, dict):
            packages.append(
                {
                    "name": str(pkg.get("name", "")),
                    "version": str(pkg.get("version", "")),
                    "license": str(pkg.get("license", "")),
                }
            )
    return packages


def check_licenses(packages: list[dict[str, str]]) -> list[str]:
    """Return a list of violation descriptions (empty = clean)."""
    violations: list[str] = []
    for pkg in packages:
        name = pkg.get("name", "")
        license_expr = pkg.get("license", "")
        if not license_expr:
            violations.append(f"{name}: missing or unrecorded license")
            continue
        if not _is_license_allowed(license_expr, name):
            violations.append(f"{name}: licence '{license_expr}' not on allowlist")
    return violations


def generate_notices(packages: list[dict[str, str]]) -> str:
    """Generate ``THIRD_PARTY_NOTICES.txt`` content from the package list."""
    lines: list[str] = ["# Third-party notices", ""]
    for pkg in sorted(packages, key=lambda p: p.get("name", "")):
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        license_id = pkg.get("license", "")
        lines.append(f"{name} {version} — {license_id}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Entry point for the license gate."""
    cwd = Path.cwd()
    lock_file = cwd / "lock.json"
    notices_path = cwd / "docs" / "THIRD_PARTY_NOTICES.txt"

    # When no lock.json is in the cwd, use the project root's pyproject.toml
    # metadata to build the package list (P00: pyyaml only).
    if lock_file.is_file():
        try:
            packages = load_lock(lock_file)
        except LicenseError as exc:
            print(f"license: ERROR {exc}", file=sys.stderr)
            return 2
    else:
        # Fallback: introspect installed packages.
        try:
            import importlib.metadata as ilm
        except ImportError:
            print("license: ERROR cannot introspect installed packages", file=sys.stderr)
            return 2
        packages = []
        for dist in ilm.distributions():
            name = dist.metadata.get("Name", "")
            version = dist.version
            license_expr = dist.metadata.get("License", "")
            if name:
                packages.append({"name": name, "version": version, "license": license_expr})

    violations = check_licenses(packages)
    if violations:
        for v in violations:
            print(f"license: FAIL {v}")
        return 1

    # Stale notices check.
    expected = generate_notices(packages)
    if notices_path.is_file():
        actual = notices_path.read_text(encoding="utf-8")
        if actual != expected:
            print("license: FAIL stale THIRD_PARTY_NOTICES.txt")
            return 1
    else:
        # Generate the notices file.
        notices_path.parent.mkdir(parents=True, exist_ok=True)
        notices_path.write_text(expected, encoding="utf-8")

    print("license: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
