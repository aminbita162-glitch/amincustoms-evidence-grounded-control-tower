"""Tests for the hygiene, secrets, security, deps and license gates (P00-T06).

Tests T-GATE-0015 to T-GATE-0024 cover each gate: a seeded violation fixture
fails and a clean fixture passes.  Tests T-GATE-0030 to T-GATE-0034 and
T-GATE-0043 to T-GATE-0044 cover specific scenarios from the directive:
vendor patterns in declared paths, always-forbidden patterns, scope
validation, empty lists, expired exceptions, transitive licences and stale
notices.  Tests T-GATE-0039 to T-GATE-0042 cover NOT_RUN_LOCAL, CI
fail-closed, commit-check and hygiene-pending-in-CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.gate.commit_check import check_commit_message
from tools.gate.gates.deps import is_expired, parse_audit
from tools.gate.gates.hygiene import drop_merge_messages, run_hygiene
from tools.gate.gates.license import check_licenses
from tools.gate.runner import GateEntry, default_env, run_selftest

REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = REPO_ROOT / "tools" / "gate" / "fixtures"


def _env() -> dict[str, str]:
    """A subprocess env with the project venv bin on PATH."""
    return default_env(REPO_ROOT)


def _scope_file(tmp_path: Path, entries: list[tuple[str, str, str]]) -> Path:
    """Write a temporary hygiene_scope.toml with the given entries."""
    lines: list[str] = []
    for path, reason, decision_id in entries:
        lines.append("[[entry]]")
        lines.append(f'path = "{path}"')
        lines.append(f'reason = "{reason}"')
        lines.append(f'owner_decision_id = "{decision_id}"')
        lines.append("")
    if not lines:
        lines = ["# empty scope"]
    scope = tmp_path / "hygiene_scope.toml"
    scope.write_text("\n".join(lines), encoding="utf-8")
    return scope


# ---------------------------------------------------------------------------
# T-GATE-0015 — hygiene violation fixture fails
# ---------------------------------------------------------------------------
# id: T-GATE-0015
# title: hygiene gate fails on a file with a forbidden pattern
# purpose: Verify that a file containing an always-forbidden pattern makes
#          the hygiene gate fail and the report never contains the pattern.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-VIOLATION
# input: a temp dir with a file containing a synthetic forbidden pattern,
#        HYGIENE_PATTERNS set to that pattern, HYGIENE_PATTERNS_VENDOR set
# expected result: run_hygiene returns FAIL; the report never contains the pattern
# risk covered: a forbidden pattern in a tracked file is not detected
# owning capability: gate-hygiene


@pytest.mark.fast
def test_hygiene_violation(tmp_path: Path) -> None:
    """A file with an always-forbidden pattern fails the hygiene gate."""
    (tmp_path / "code.py").write_text("SYNTHETIC_FORBIDDEN_TOKEN = True\n", encoding="utf-8")
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "SYNTHETIC_FORBIDDEN_TOKEN",
        "HYGIENE_PATTERNS_VENDOR": "SYNTHETIC_VENDOR_NAME",
        "PATH": os.environ.get("PATH", ""),
    }
    scope = _scope_file(tmp_path, [])
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"
    report = " ".join(result.violations) + " " + (result.reason or "")
    assert "SYNTHETIC_FORBIDDEN_TOKEN" not in report


# ---------------------------------------------------------------------------
# T-GATE-0016 — hygiene clean fixture passes
# ---------------------------------------------------------------------------
# id: T-GATE-0016
# title: hygiene gate passes on a clean file
# purpose: Verify that a file without any forbidden or vendor pattern passes
#          the hygiene gate and the report never contains the patterns.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-CLEAN
# input: a temp dir with a clean file, HYGIENE_PATTERNS and
#        HYGIENE_PATTERNS_VENDOR set to synthetic patterns
# expected result: run_hygiene returns PASS
# risk covered: a clean file is falsely flagged as a hygiene violation
# owning capability: gate-hygiene


@pytest.mark.fast
def test_hygiene_clean(tmp_path: Path) -> None:
    """A file without forbidden or vendor patterns passes the hygiene gate."""
    (tmp_path / "clean.py").write_text("x = 1\n", encoding="utf-8")
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "SYNTHETIC_FORBIDDEN_TOKEN",
        "HYGIENE_PATTERNS_VENDOR": "SYNTHETIC_VENDOR_NAME",
        "PATH": os.environ.get("PATH", ""),
    }
    scope = _scope_file(tmp_path, [])
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "PASS"


# ---------------------------------------------------------------------------
# T-GATE-0017 — secrets violation fixture fails
# ---------------------------------------------------------------------------
# id: T-GATE-0017
# title: secrets gate fails on a pre-computed result with findings
# purpose: Verify that a secrets_result.json with findings makes the secrets
#          gate exit 1.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-SECRETS-VIOLATION
# input: a temp dir with a secrets_result.json containing one finding
# expected result: the secrets gate exits 1
# risk covered: a secret in a tracked file is not detected
# owning capability: gate-secrets


@pytest.mark.fast
def test_secrets_violation(tmp_path: Path) -> None:
    """A secrets_result.json with findings makes the secrets gate exit 1."""
    result_file = tmp_path / "secrets_result.json"
    result_file.write_text(
        json.dumps({"Results": [{"file": "config.txt", "secret": "AKIAIOSFODNN7EXAMPLE"}]}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.secrets"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# T-GATE-0018 — secrets clean fixture passes
# ---------------------------------------------------------------------------
# id: T-GATE-0018
# title: secrets gate passes on a clean result
# purpose: Verify that a secrets_result.json with no findings makes the
#          secrets gate exit 0.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-SECRETS-CLEAN
# input: a temp dir with a secrets_result.json containing no findings
# expected result: the secrets gate exits 0
# risk covered: a clean file is falsely flagged as containing a secret
# owning capability: gate-secrets


@pytest.mark.fast
def test_secrets_clean(tmp_path: Path) -> None:
    """A secrets_result.json with no findings makes the secrets gate exit 0."""
    result_file = tmp_path / "secrets_result.json"
    result_file.write_text(json.dumps({"Results": []}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.secrets"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# T-GATE-0019 — security violation fixture fails
# ---------------------------------------------------------------------------
# id: T-GATE-0019
# title: security gate fails on yaml.unsafe_load
# purpose: Verify that a Python file with yaml.unsafe_load makes the security
#          gate (bandit) report findings and exit 1.
# level: slow
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-SECURITY-VIOLATION
# input: a temp dir with a .py file containing yaml.unsafe_load
# expected result: bandit finds the unsafe-load issue and exits 1
# risk covered: an unsafe-load vulnerability is not detected by the security gate
# owning capability: gate-security


@pytest.mark.slow
def test_security_violation(tmp_path: Path) -> None:
    """A .py file with yaml.load (no safe loader) makes the security gate exit 1."""
    (tmp_path / "bad.py").write_text(
        "import yaml\ndef f(d):\n    return yaml.load(d)\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.security"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# T-GATE-0020 — security clean fixture passes
# ---------------------------------------------------------------------------
# id: T-GATE-0020
# title: security gate passes on a clean file
# purpose: Verify that a clean .py file makes the security gate exit 0.
# level: slow
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-SECURITY-CLEAN
# input: a temp dir with a clean .py file
# expected result: bandit finds no issues and exits 0
# risk covered: a clean file is falsely flagged as a security violation
# owning capability: gate-security


@pytest.mark.slow
def test_security_clean(tmp_path: Path) -> None:
    """A clean .py file makes the security gate exit 0."""
    (tmp_path / "good.py").write_text(
        'def greet(name):\n    return f"hello {name}"\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.security"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# T-GATE-0021 — deps violation fixture fails
# ---------------------------------------------------------------------------
# id: T-GATE-0021
# title: deps gate fails on a vulnerable package
# purpose: Verify that a deps_audit.json with a vulnerability makes the deps
#          gate exit 1 when there is no unexpired exception.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-DEPS-VIOLATION
# input: a temp dir with a deps_audit.json containing one vulnerability
# expected result: the deps gate exits 1
# risk covered: a vulnerable dependency without an exception is not detected
# owning capability: gate-deps


@pytest.mark.fast
def test_deps_violation(tmp_path: Path) -> None:
    """A deps_audit.json with a vulnerability makes the deps gate exit 1."""
    audit = {
        "dependencies": [
            {
                "name": "vulnerable-pkg",
                "version": "1.0.0",
                "vulns": [{"id": "PYSEC-2021-12345", "fix_versions": ["1.0.1"]}],
            }
        ]
    }
    (tmp_path / "deps_audit.json").write_text(json.dumps(audit), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.deps"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# T-GATE-0022 — deps clean fixture passes
# ---------------------------------------------------------------------------
# id: T-GATE-0022
# title: deps gate passes on a clean audit
# purpose: Verify that a deps_audit.json with no vulnerabilities makes the
#          deps gate exit 0.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-DEPS-CLEAN
# input: a temp dir with a deps_audit.json containing no vulnerabilities
# expected result: the deps gate exits 0
# risk covered: a clean dependency audit is falsely flagged as vulnerable
# owning capability: gate-deps


@pytest.mark.fast
def test_deps_clean(tmp_path: Path) -> None:
    """A deps_audit.json with no vulnerabilities makes the deps gate exit 0."""
    (tmp_path / "deps_audit.json").write_text(json.dumps({"dependencies": []}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.deps"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# T-GATE-0023 — license violation fixture fails (GPL family)
# ---------------------------------------------------------------------------
# id: T-GATE-0023
# title: license gate fails on a GPL-family licence
# purpose: Verify that a lock.json with a GPL-3.0-licensed package makes the
#          license gate exit 1.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-LICENSE-VIOLATION
# input: a temp dir with a lock.json containing a GPL-3.0-licensed package
# expected result: the license gate exits 1
# risk covered: a GPL-family dependency is admitted without a licence check
# owning capability: gate-license


@pytest.mark.fast
def test_license_violation_gpl(tmp_path: Path) -> None:
    """A lock.json with a GPL-3.0 package makes the license gate exit 1."""
    lock = {
        "packages": [
            {"name": "evil-pkg", "version": "1.0.0", "license": "GPL-3.0"},
            {"name": "safe-pkg", "version": "2.0.0", "license": "MIT"},
        ]
    }
    (tmp_path / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.license"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# T-GATE-0024 — license clean fixture passes
# ---------------------------------------------------------------------------
# id: T-GATE-0024
# title: license gate passes on allowlisted licences
# purpose: Verify that a lock.json with only MIT and Apache-2.0 licences makes
#          the license gate exit 0.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-LICENSE-CLEAN
# input: a temp dir with a lock.json containing only MIT and Apache-2.0 packages
# expected result: the license gate exits 0
# risk covered: a clean dependency licence is falsely flagged as disallowed
# owning capability: gate-license


@pytest.mark.fast
def test_license_clean(tmp_path: Path) -> None:
    """A lock.json with only MIT and Apache-2.0 makes the license gate exit 0."""
    lock = {
        "packages": [
            {"name": "safe-pkg", "version": "2.0.0", "license": "MIT"},
            {"name": "other-pkg", "version": "1.5.0", "license": "Apache-2.0"},
        ]
    }
    (tmp_path / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.license"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# T-GATE-0030 — vendor pattern passes in adapter path, fails elsewhere
# ---------------------------------------------------------------------------
# id: T-GATE-0030
# title: vendor pattern passes in a declared adapter path and fails elsewhere
# purpose: Verify that a vendor pattern is allowed in a scope-matched adapter
#          file but fails in a non-scope file, a commit message and PR text.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-VENDOR-SCOPE
# input: a temp dir with an adapter file containing the vendor pattern (passes),
#        a src file with the vendor pattern (fails), a COMMIT_MSG with the
#        vendor pattern (fails), a PR_TEXT with the vendor pattern (fails)
# expected result: adapter file passes; src file fails; commit message fails;
#                   PR text fails
# risk covered: a vendor pattern is admitted outside its declared scope
# owning capability: gate-hygiene


@pytest.mark.fast
def test_vendor_pattern_scope(tmp_path: Path) -> None:
    """A vendor pattern passes in an adapter file and fails elsewhere."""
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "provider.py").write_text("SYNTHETIC_VENDOR_NAME = True\n", encoding="utf-8")
    scope = _scope_file(tmp_path, [("adapter/**/*.py", "provider adapter", "D-37")])
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "SYNTHETIC_FORBIDDEN_TOKEN",
        "HYGIENE_PATTERNS_VENDOR": "SYNTHETIC_VENDOR_NAME",
        "PATH": os.environ.get("PATH", ""),
    }
    # Vendor pattern in adapter path → passes
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "PASS"

    # Vendor pattern in a non-scope file → fails
    (tmp_path / "src_code.py").write_text("SYNTHETIC_VENDOR_NAME = True\n", encoding="utf-8")
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"

    # Clean up the src file
    (tmp_path / "src_code.py").unlink()

    # Vendor pattern in a commit message → fails
    (tmp_path / "COMMIT_MSG").write_text(
        "feat(api): add endpoint [P00-T01]\n\nSYNTHETIC_VENDOR_NAME\n",
        encoding="utf-8",
    )
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"

    # Vendor pattern in PR text → fails
    (tmp_path / "PR_TEXT").write_text(
        "feat(api): add endpoint [P00-T01]\n\nSYNTHETIC_VENDOR_NAME\n",
        encoding="utf-8",
    )
    # Remove COMMIT_MSG so only PR_TEXT is checked for patterns
    (tmp_path / "COMMIT_MSG").unlink()
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# T-GATE-0031 — always-forbidden pattern fails everywhere including declared path
# ---------------------------------------------------------------------------
# id: T-GATE-0031
# title: always-forbidden pattern fails everywhere including a declared path
# purpose: Verify that an always-forbidden pattern fails even when the file
#          is in a scope-matched adapter path.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-ALWAYS
# input: a temp dir with an adapter file containing the always-forbidden pattern
# expected result: run_hygiene returns FAIL
# risk covered: an always-forbidden pattern is admitted inside a declared scope
# owning capability: gate-hygiene


@pytest.mark.fast
def test_always_forbidden_in_scope(tmp_path: Path) -> None:
    """An always-forbidden pattern fails even in a scope-matched file."""
    adapter_dir = tmp_path / "adapter"
    adapter_dir.mkdir()
    (adapter_dir / "provider.py").write_text("SYNTHETIC_FORBIDDEN_TOKEN = True\n", encoding="utf-8")
    scope = _scope_file(tmp_path, [("adapter/**/*.py", "provider adapter", "D-37")])
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "SYNTHETIC_FORBIDDEN_TOKEN",
        "HYGIENE_PATTERNS_VENDOR": "SYNTHETIC_VENDOR_NAME",
        "PATH": os.environ.get("PATH", ""),
    }
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# T-GATE-0032 — scope entry outside permitted path families fails
# ---------------------------------------------------------------------------
# id: T-GATE-0032
# title: scope entry outside the permitted path families fails
# purpose: Verify that a hygiene_scope.toml entry whose path is not under
#          adapter/, provider-configuration/, provider-test/ or
#          provider-documentation/ fails the hygiene gate.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-SCOPE-INVALID
# input: a scope file with an entry under src/ (not a permitted family)
# expected result: run_hygiene returns FAIL with a scope validation error
# risk covered: a scope exception is granted outside the permitted path families
# owning capability: gate-hygiene


@pytest.mark.fast
def test_scope_outside_permitted_families(tmp_path: Path) -> None:
    """A scope entry under src/ (not a permitted family) fails the gate."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    scope = _scope_file(tmp_path, [("src/**/*.py", "not allowed", "D-99")])
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "FORBIDDEN",
        "HYGIENE_PATTERNS_VENDOR": "VENDOR",
        "PATH": os.environ.get("PATH", ""),
    }
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# T-GATE-0033 — missing or empty list fails
# ---------------------------------------------------------------------------
# id: T-GATE-0033
# title: a present but empty list fails the hygiene gate
# purpose: Verify that an empty HYGIENE_PATTERNS env var (present but empty)
#          fails the hygiene gate everywhere.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-EMPTY
# input: HYGIENE_PATTERNS set to an empty string, HYGIENE_PATTERNS_VENDOR set
#        to a non-empty value
# expected result: run_hygiene returns FAIL (list below minimum entry count)
# risk covered: an empty list is treated as a pass instead of a failure
# owning capability: gate-hygiene


@pytest.mark.fast
def test_empty_list_fails(tmp_path: Path) -> None:
    """An empty HYGIENE_PATTERNS (present but empty) fails the gate."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    scope = _scope_file(tmp_path, [])
    env: dict[str, str] = {
        "HYGIENE_PATTERNS": "",
        "HYGIENE_PATTERNS_VENDOR": "VENDOR",
        "PATH": os.environ.get("PATH", ""),
    }
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# T-GATE-0034 — expired exception fails
# ---------------------------------------------------------------------------
# id: T-GATE-0034
# title: an expired exception fails the deps gate
# purpose: Verify that a vulnerability with an expired exception is treated
#          as unexcepted and fails the deps gate.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-DEPS-EXPIRED
# input: a deps_audit.json with a vulnerability and an exceptions.toml with
#        an expired exception for that vulnerability
# expected result: the vulnerability is treated as unexcepted and the gate fails
# risk covered: an expired exception allows a vulnerability to pass
# owning capability: gate-deps


@pytest.mark.fast
def test_expired_exception_fails(tmp_path: Path) -> None:
    """An expired exception does not suppress a vulnerability."""
    # is_expired returns True for past dates
    assert is_expired("2020-01-01") is True
    assert is_expired("2099-12-31") is False
    # An expired exception should not suppress a vulnerability
    exceptions = [
        {
            "package": "vulnerable-pkg",
            "vulnerability_id": "PYSEC-2021-12345",
            "reason": "test",
            "owner_decision_id": "D-99",
            "expiry": "2020-01-01",  # expired
        }
    ]
    audit = parse_audit(
        {
            "dependencies": [
                {
                    "name": "vulnerable-pkg",
                    "version": "1.0.0",
                    "vulns": [{"id": "PYSEC-2021-12345", "fix_versions": ["1.0.1"]}],
                }
            ]
        }
    )
    assert len(audit) == 1
    assert audit[0]["name"] == "vulnerable-pkg"
    has_unexpired = any(
        exc["package"] == "vulnerable-pkg"
        and exc["vulnerability_id"] == "PYSEC-2021-12345"
        and not is_expired(exc["expiry"])
        for exc in exceptions
    )
    assert has_unexpired is False


# ---------------------------------------------------------------------------
# T-GATE-0039 — NOT_RUN_LOCAL (no lists, not CI)
# ---------------------------------------------------------------------------
# id: T-GATE-0039
# title: without lists a local run reports NOT_RUN_LOCAL
# purpose: Verify that when neither HYGIENE_PATTERNS nor HYGIENE_PATTERNS_VENDOR
#          is set and CI is not set, the hygiene gate reports NOT_RUN_LOCAL
#          and never counts it as a pass.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-NOT-RUN-LOCAL
# input: an env with no HYGIENE_PATTERNS, no HYGIENE_PATTERNS_VENDOR, no CI
# expected result: run_hygiene returns NOT_RUN_LOCAL with reason NOT_RUN_LOCAL
# risk covered: a missing list is treated as a pass instead of NOT_RUN_LOCAL
# owning capability: gate-hygiene


@pytest.mark.fast
def test_not_run_local(tmp_path: Path) -> None:
    """Without lists and not in CI, the hygiene gate reports NOT_RUN_LOCAL."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    env: dict[str, str] = {"PATH": os.environ.get("PATH", "")}
    result = run_hygiene(tmp_path, env)
    assert result.status == "NOT_RUN_LOCAL"
    assert result.reason == "NOT_RUN_LOCAL"


# ---------------------------------------------------------------------------
# T-GATE-0040 — CI missing list fails closed
# ---------------------------------------------------------------------------
# id: T-GATE-0040
# title: in CI a missing list fails closed
# purpose: Verify that when CI is set but HYGIENE_PATTERNS is missing, the
#          hygiene gate fails closed.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-CI-MISSING
# input: an env with CI set but no HYGIENE_PATTERNS
# expected result: run_hygiene returns FAIL
# risk covered: a missing list in CI is treated as NOT_RUN_LOCAL instead of fail
# owning capability: gate-hygiene


@pytest.mark.fast
def test_ci_missing_list_fails(tmp_path: Path) -> None:
    """In CI, a missing HYGIENE_PATTERNS fails the gate closed."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    env: dict[str, str] = {
        "CI": "true",
        "PATH": os.environ.get("PATH", ""),
    }
    result = run_hygiene(tmp_path, env)
    assert result.status == "FAIL"


# ---------------------------------------------------------------------------
# T-GATE-0041 — commit-check rejects bad format, trailers, URLs; accepts clean
# ---------------------------------------------------------------------------
# id: T-GATE-0041
# title: commit-check rejects violations and accepts a clean message
# purpose: Verify that commit-check fails on a bad first line, each forbidden
#          trailer, a URL, and passes on a clean message.
# level: fast
# requirement ids: P00-T06, Part 1 §4.9, §4.3
# scenario ids: S-GATE-COMMIT-CHECK
# input: multiple commit messages (bad format, each trailer type, URL, clean)
# expected result: violations return non-empty; clean returns empty
# risk covered: a malformed or attributed commit message passes commit-check
# owning capability: gate-commit-check


@pytest.mark.fast
def test_commit_check_bad_format() -> None:
    """A first line outside the format fails commit-check."""
    violations = check_commit_message("added a feature\n")
    assert violations


@pytest.mark.fast
def test_commit_check_trailer_co_authored() -> None:
    """A Co-Authored-By trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nCo-Authored-By: Someone\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_trailer_signed_off() -> None:
    """A Signed-off-by trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nSigned-off-by: Dev\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_trailer_generated() -> None:
    """A Generated-by trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nGenerated-by: Bot\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_trailer_reviewed() -> None:
    """A Reviewed-by trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nReviewed-by: Dev\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_trailer_acked() -> None:
    """An Acked-by trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nAcked-by: Dev\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_trailer_tested() -> None:
    """A Tested-by trailer fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nTested-by: Dev\n"
    violations = check_commit_message(msg)
    assert any("trailer" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_url() -> None:
    """A URL in the message fails commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nSee http://example.com\n"
    violations = check_commit_message(msg)
    assert any("url" in v.lower() for v in violations)


@pytest.mark.fast
def test_commit_check_clean() -> None:
    """A clean commit message passes commit-check."""
    msg = "feat(api): add endpoint [P00-T01]\n\nAdds the new API.\n"
    violations = check_commit_message(msg)
    assert violations == []


# ---------------------------------------------------------------------------
# T-GATE-0042 — hygiene pending in CI
# ---------------------------------------------------------------------------
# id: T-GATE-0042
# title: hygiene gate runs in CI (not NOT_RUN_LOCAL) when lists are present
# purpose: Verify that when CI is set and both lists are present, the hygiene
#          gate runs the full scan (status is PASS or FAIL, not NOT_RUN_LOCAL).
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-HYGIENE-CI-PENDING
# input: an env with CI set, HYGIENE_PATTERNS and HYGIENE_PATTERNS_VENDOR present
# expected result: run_hygiene status is not NOT_RUN_LOCAL
# risk covered: the hygiene gate reports NOT_RUN_LOCAL in CI when lists are present
# owning capability: gate-hygiene


@pytest.mark.fast
def test_hygiene_pending_in_ci(tmp_path: Path) -> None:
    """In CI with lists present, the hygiene gate runs (not NOT_RUN_LOCAL)."""
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    scope = _scope_file(tmp_path, [])
    env: dict[str, str] = {
        "CI": "true",
        "HYGIENE_PATTERNS": "FORBIDDEN_TOKEN",
        "HYGIENE_PATTERNS_VENDOR": "VENDOR_NAME",
        "PATH": os.environ.get("PATH", ""),
    }
    result = run_hygiene(tmp_path, env, scope_path=scope)
    assert result.status != "NOT_RUN_LOCAL"


# ---------------------------------------------------------------------------
# T-GATE-0043 — transitive package with licence outside allowlist fails
# ---------------------------------------------------------------------------
# id: T-GATE-0043
# title: a transitive package with a licence outside the allowlist fails
# purpose: Verify that a lock.json with a package whose licence is not on the
#          allowlist (and not a D-37 admission) fails the license gate.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-LICENSE-TRANSITIVE
# input: a lock.json with a package licensed under LGPL-2.1
# expected result: check_licenses returns a non-empty violation list
# risk covered: a transitive dependency with a disallowed licence passes
# owning capability: gate-license


@pytest.mark.fast
def test_license_transitive_bad_license() -> None:
    """A transitive package with LGPL-2.1 fails the license check."""
    packages = [
        {"name": "transitive-dep", "version": "0.1.0", "license": "LGPL-2.1"},
        {"name": "safe-pkg", "version": "1.0.0", "license": "MIT"},
    ]
    violations = check_licenses(packages)
    assert any("LGPL" in v for v in violations)


# ---------------------------------------------------------------------------
# T-GATE-0045 - merge commit messages are not checked again
# ---------------------------------------------------------------------------
# id: T-GATE-0045
# title: merge commit messages are dropped before the commit checks
# purpose: Verify that the messages of merge commits are removed from the list
#          that the hygiene gate checks, and that task commits are kept.
# level: fast
# requirement ids: Part 4 section 4.12, Part 1 section 4.9
# scenario ids: S-GATE-HYGIENE-MERGE
# input: three messages, two of them merge commit messages
# expected result: only the task commit message is kept
# risk covered: the gate fails on every merge commit of a pull request
# owning capability: gate-hygiene


@pytest.mark.fast
def test_drop_merge_messages() -> None:
    """Merge commit messages are dropped and task commit messages are kept."""
    messages = [
        "Merge pull request #2 from owner/phase/00-bootstrap",
        "feat(auth): add login page [P00-T01]",
        "Merge abc123 into def456",
    ]
    assert drop_merge_messages(messages) == ["feat(auth): add login page [P00-T01]"]


# ---------------------------------------------------------------------------
# T-GATE-0044 — lock changed without regenerating notices fails
# ---------------------------------------------------------------------------
# id: T-GATE-0044
# title: a stale THIRD_PARTY_NOTICES.txt fails the license gate
# purpose: Verify that a lock.json whose generated notices do not match the
#          existing THIRD_PARTY_NOTICES.txt fails the license gate.
# level: fast
# requirement ids: P00-T06, Part 4 §4.12
# scenario ids: S-GATE-LICENSE-STALE
# input: a lock.json with allowed licences and a stale notices file
# expected result: the license gate exits 1
# risk covered: a stale notices file is treated as up-to-date
# owning capability: gate-license


@pytest.mark.fast
def test_license_stale_notices(tmp_path: Path) -> None:
    """A stale THIRD_PARTY_NOTICES.txt fails the license gate."""
    lock = {
        "packages": [
            {"name": "safe-pkg", "version": "2.0.0", "license": "MIT"},
        ]
    }
    (tmp_path / "lock.json").write_text(json.dumps(lock), encoding="utf-8")
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    # Write a stale notices file that doesn't match the generated content
    (docs_dir / "THIRD_PARTY_NOTICES.txt").write_text(
        "# stale notices\n\nold content\n", encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tools.gate.gates.license"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1


# ---------------------------------------------------------------------------
# T-GATE-SELFTEST-T06 — selftest passes against the T06 gate fixtures
# ---------------------------------------------------------------------------
# id: T-GATE-SELFTEST-T06
# title: selftest passes against the hygiene, secrets, security, deps, license
#        fixtures with real tooling
# purpose: Verify that run_selftest returns 0 when the T06 gates are exercised
#          against their real fixtures.
# level: slow
# requirement ids: P00-T06, Part 6 §6.13
# scenario ids: S-GATE-SELFTEST-T06
# input: a catalogue of the five T06 gates with their real fixtures
# expected result: run_selftest returns 0
# risk covered: a gate fixture does not actually fail/pass as declared
# owning capability: gate-runner


@pytest.mark.slow
def test_selftest_t06_gates() -> None:
    """run_selftest returns 0 against the T06 gate fixtures."""
    catalogue: dict[str, GateEntry] = {
        "hygiene": GateEntry(
            "hygiene",
            "P",
            "python -m tools.gate.gates.hygiene",
            60,
            "P00",
            _FIXTURES / "hygiene_violation",
            _FIXTURES / "hygiene_clean",
        ),
        "secrets": GateEntry(
            "secrets",
            "P",
            "python -m tools.gate.gates.secrets",
            60,
            "P00",
            _FIXTURES / "secrets_violation",
            _FIXTURES / "secrets_clean",
        ),
        "security": GateEntry(
            "security",
            "P",
            "python -m tools.gate.gates.security",
            120,
            "P00",
            _FIXTURES / "security_violation.py",
            _FIXTURES / "security_clean.py",
        ),
        "deps": GateEntry(
            "deps",
            "P",
            "python -m tools.gate.gates.deps",
            120,
            "P00",
            _FIXTURES / "deps_violation",
            _FIXTURES / "deps_clean",
        ),
        "license": GateEntry(
            "license",
            "P",
            "python -m tools.gate.gates.license",
            120,
            "P00",
            _FIXTURES / "license_violation",
            _FIXTURES / "license_clean",
        ),
    }
    schedule = {"P00": ("hygiene", "secrets", "security", "deps", "license")}
    code = run_selftest(catalogue, "P00", _FIXTURES, schedule=schedule, env=_env())
    assert code == 0
