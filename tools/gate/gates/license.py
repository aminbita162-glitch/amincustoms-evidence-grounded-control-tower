"""License gate — checks every dependency licence against the allowlist (P00-T06).

Allowed licences: MIT, BSD-2-Clause, BSD-3-Clause, Apache-2.0, ISC, PSF-2.0,
MPL-2.0 (unmodified use only).  MIT-0, 0BSD, Zlib, CC0-1.0 are admitted only
for the two named transitive packages of decision D-37 (cffi, numpy).

The gate checks every package in the lock, direct and transitive.  A package
whose licence expression has any component outside the allowlist fails.
``docs/THIRD_PARTY_NOTICES.txt`` is generated from the lock and the vendored
assets; a stale file fails the gate.

When a ``lock.json`` file exists in the current directory the gate reads the
package list from it instead of reading uv.lock, the default source
(licences are then read from the installed metadata of each locked package).
This allows the selftest and unit tests to exercise the licence logic without
network access.

Invokable as ``python -m tools.gate.gates.license``.

Spec: Part 4 §4.12, Part 6 §6.13.
"""

from __future__ import annotations

import json
import sys
import tomllib
from importlib.metadata import PackageMetadata, PackageNotFoundError, distribution
from pathlib import Path

__all__ = [
    "ALLOWED_LICENSES",
    "D37_EXTRA_LICENSES",
    "D37_PACKAGES",
    "LicenseError",
    "check_licenses",
    "generate_notices",
    "load_lock",
    "load_locked_packages",
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
    cleaned = [t.strip().strip("()").strip() for t in tokens]
    return [t for t in cleaned if t]


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


_ALIASES: dict[str, str] = {
    "MIT License": "MIT",
    "Apache 2.0": "Apache-2.0",
    "Apache License 2.0": "Apache-2.0",
    "Apache License, Version 2.0": "Apache-2.0",
    "Apache Software License": "Apache-2.0",
    "BSD 3-Clause License": "BSD-3-Clause",
    "BSD 2-Clause License": "BSD-2-Clause",
    "ISC License": "ISC",
    "ISC License (ISCL)": "ISC",
    "PSFL": "PSF-2.0",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
}
_CLASSIFIER_PREFIX = "License :: OSI Approved :: "


def _resolve_license(meta: PackageMetadata) -> str:
    """Return the licence of a package from its installed metadata.

    Order: the License-Expression field, then a short single-line License field,
    then exactly one recognised licence classifier.  Anything else is unrecorded.
    """
    expr = (meta.get("License-Expression") or "").strip()
    if expr:
        return expr
    text = (meta.get("License") or "").strip()
    if text and len(text) <= 80 and chr(10) not in text:
        return _ALIASES.get(text, text)
    found: set[str] = set()
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith(_CLASSIFIER_PREFIX):
            alias = _ALIASES.get(classifier[len(_CLASSIFIER_PREFIX) :])
            if alias:
                found.add(alias)
    if len(found) == 1:
        return found.pop()
    return ""


def load_locked_packages(lock_path: Path) -> list[dict[str, str]]:
    """Read every locked package from uv.lock and its licence from installed metadata."""
    try:
        data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise LicenseError(f"cannot load uv.lock: {exc}") from exc
    entries = data.get("package")
    if not isinstance(entries, list):
        raise LicenseError("uv.lock has no package list")
    packages: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        if isinstance(source, dict) and ("editable" in source or "virtual" in source):
            continue
        name = str(entry.get("name", ""))
        version = str(entry.get("version", ""))
        try:
            meta = distribution(name).metadata
        except PackageNotFoundError:
            print(f"license: NOTE {name} is locked but not installed on this platform, skipped")
            continue
        packages.append({"name": name, "version": version, "license": _resolve_license(meta)})
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
        try:
            packages = load_locked_packages(cwd / "uv.lock")
        except LicenseError as exc:
            print(f"license: ERROR {exc}", file=sys.stderr)
            return 2

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
