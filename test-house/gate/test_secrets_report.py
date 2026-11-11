"""Tests for how the secrets gate reads the scanner report (P00-REV9).

A fake scanner script stands in for the real binary, so the tests need no
network and no external tool.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.gate.gates.secrets import run_gitleaks

_FAKE = """#!/bin/sh
while [ $# -gt 0 ]; do
  if [ "$1" = "--report-path" ]; then shift; REPORT="$1"; fi
  shift
done
BODY
"""


def _fake(tmp_path: Path, body: str) -> Path:
    """A fake scanner executable whose behaviour is the given shell body."""
    script = tmp_path / "fake-scanner"
    script.write_text(_FAKE.replace("BODY", body), encoding="utf-8")
    script.chmod(0o700)
    return script


# ---------------------------------------------------------------------------
# T-GATE-0049 - report file with a finding
# ---------------------------------------------------------------------------
# id: T-GATE-0049
# title: the secrets gate reads findings from the report file
# purpose: Verify that run_gitleaks() returns exit 1 and the finding when the scanner writes one.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-SECRETS-REPORT-FINDING
# input: a fake scanner that writes a report file with one finding
# expected result: exit code 1 and one finding naming the file
# risk covered: findings are lost because the report is read from the wrong place
# owning capability: gate-secrets


@pytest.mark.fast
def test_report_file_with_finding(tmp_path: Path) -> None:
    """A finding in the report file fails the gate."""
    fake = _fake(tmp_path, 'printf \'[{"File": "a.txt"}]\' > "$REPORT"')
    code, findings, error = run_gitleaks(tmp_path, binary=fake)
    assert code == 1
    assert error is None
    assert findings[0]["File"] == "a.txt"


# ---------------------------------------------------------------------------
# T-GATE-0050 - no report and no clean statement
# ---------------------------------------------------------------------------
# id: T-GATE-0050
# title: the secrets gate fails closed when the scanner leaves no report
# purpose: Verify run_gitleaks() returns exit 2 with no report and no clean statement.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-SECRETS-REPORT-MISSING
# input: a fake scanner that writes no report and says leaks were found
# expected result: exit code 2 and an error message
# risk covered: a scanner that found leaks but wrote nothing is read as a pass
# owning capability: gate-secrets


@pytest.mark.fast
def test_no_report_is_an_error(tmp_path: Path) -> None:
    """Missing report without a clean statement is a tool error."""
    fake = _fake(tmp_path, 'echo "WRN leaks found: 2" >&2')
    code, findings, error = run_gitleaks(tmp_path, binary=fake)
    assert code == 2
    assert findings == []
    assert error


# ---------------------------------------------------------------------------
# T-GATE-0051 - clean run without a report
# ---------------------------------------------------------------------------
# id: T-GATE-0051
# title: the secrets gate passes a run the scanner reports as clean
# purpose: Verify run_gitleaks() returns exit 0 with no report and a clean statement.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-SECRETS-REPORT-CLEAN
# input: a fake scanner that writes no report and says no leaks found
# expected result: exit code 0, no findings, no error
# risk covered: a clean scan is reported as a tool failure
# owning capability: gate-secrets


@pytest.mark.fast
def test_clean_run_without_report(tmp_path: Path) -> None:
    """A clean statement without a report file passes."""
    fake = _fake(tmp_path, 'echo "INF no leaks found" >&2')
    code, findings, error = run_gitleaks(tmp_path, binary=fake)
    assert code == 0
    assert findings == []
    assert error is None
