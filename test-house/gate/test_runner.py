"""Tests for the Control Tower gate runner (P00-T03).

Every test carries a header (id, title, purpose, level, requirement ids, input,
expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from tools.gate.runner import (
    GateEntry,
    GateError,
    MisconfigurationError,
    active_gate_names,
    affected_set,
    default_env,
    gate_status,
    hash_file,
    kill_process_group,
    load_catalogue,
    load_results,
    missing_required,
    parse_phase_number,
    read_current_phase,
    render_report,
    run_gate,
    run_selftest,
    run_set,
    select_set,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = REPO_ROOT / "tools" / "gate" / "fixtures"


def _env() -> dict[str, str]:
    """A subprocess env with the project venv bin on PATH (for real tools)."""
    return default_env(REPO_ROOT)


def _catalogue(tmp_path: Path, text: str) -> dict[str, GateEntry]:
    """Write a TOML catalogue to tmp_path and load it."""
    path = tmp_path / "catalogue.toml"
    path.write_text(text, encoding="utf-8")
    return load_catalogue(path)


def _gate(
    name: str,
    *,
    command: str = "true",
    cadence: str = "QP",
    timeout: int = 10,
    activates_in: str = "P00",
    violation_fixture: str = "",
    clean_fixture: str = "",
) -> str:
    """Render a single [gate.NAME] TOML block."""
    return (
        f"[gate.{name}]\n"
        f'cadence = "{cadence}"\n'
        f'command = "{command}"\n'
        f"timeout = {timeout}\n"
        f'activates_in = "{activates_in}"\n'
        f'violation_fixture = "{violation_fixture}"\n'
        f'clean_fixture = "{clean_fixture}"\n'
    )


# ---------------------------------------------------------------------------
# T-GATE-0001 — Exit-code semantics
# ---------------------------------------------------------------------------
# id: T-GATE-0001
# title: Exit-code semantics (pass / fail / misconfiguration)
# purpose: Verify that a passing gate returns 0, a failing gate returns 1, and a
#          malformed catalogue entry is a misconfiguration (exit 2).
# level: fast
# requirement ids: P00-T03, Part 4 §4.3
# scenario ids: S-GATE-EXIT
# input: two temp catalogues (passing and failing gates) plus a malformed entry
# expected result: run_set -> 0, 1; load_catalogue(malformed) raises MisconfigurationError
# risk covered: a gate failure or misconfiguration is misreported as a pass
# owning capability: gate-runner


@pytest.mark.fast
def test_exit_code_pass(tmp_path: Path) -> None:
    """A gate whose command exits 0 makes run_set return 0."""
    catalogue = _catalogue(tmp_path, _gate("pass", command="true"))
    log_dir = tmp_path / "logs"
    code = run_set(["pass"], catalogue, log_dir, "P00", schedule={"P00": ("pass",)})
    assert code == 0


@pytest.mark.fast
def test_exit_code_fail(tmp_path: Path) -> None:
    """A gate whose command exits nonzero makes run_set return 1."""
    catalogue = _catalogue(tmp_path, _gate("fail", command="false"))
    log_dir = tmp_path / "logs"
    code = run_set(["fail"], catalogue, log_dir, "P00", schedule={"P00": ("fail",)})
    assert code == 1


@pytest.mark.fast
def test_exit_code_misconfiguration(tmp_path: Path) -> None:
    """A catalogue entry missing a required field raises MisconfigurationError."""
    malformed = (
        "[gate.bad]\n"
        'cadence = "QP"\n'
        "timeout = 10\n"
        'activates_in = "P00"\n'
        'violation_fixture = ""\n'
        'clean_fixture = ""\n'
    )
    with pytest.raises(MisconfigurationError):
        _catalogue(tmp_path, malformed)


# ---------------------------------------------------------------------------
# T-GATE-0002 — Timeout
# ---------------------------------------------------------------------------
# id: T-GATE-0002
# title: Gate timeout records reason TIMEOUT
# purpose: Verify a gate exceeding its timeout is killed and records reason
#          TIMEOUT with a nonzero exit code.
# level: slow
# requirement ids: P00-T03, Part 4 §4.3, Part 6 §6.13
# scenario ids: S-GATE-TIMEOUT
# input: a gate with timeout=1 and command "sleep 10"
# expected result: result.reason == "TIMEOUT" and exit_code != 0
# risk covered: a hung command is reported as a pass instead of a timeout failure
# owning capability: gate-runner


@pytest.mark.slow
def test_timeout_reason(tmp_path: Path) -> None:
    """A gate that overruns its timeout is killed and records reason TIMEOUT."""
    catalogue = _catalogue(tmp_path, _gate("slow", command="sleep 10", timeout=1))
    log_dir = tmp_path / "logs"
    result = run_gate(catalogue["slow"], log_dir)
    assert result.reason == "TIMEOUT"
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# T-GATE-0003 — JSON result schema
# ---------------------------------------------------------------------------
# id: T-GATE-0003
# title: JSON result has the required schema
# purpose: Verify every persisted result carries gate, command, exit_code and
#          duration fields.
# level: fast
# requirement ids: P00-T03, Part 4 §4.3
# scenario ids: S-GATE-SCHEMA
# input: a passing gate run
# expected result: the written JSON contains all required keys with correct types
# risk covered: a gate result is unreadable or missing the contract fields
# owning capability: gate-runner


@pytest.mark.fast
def test_json_result_schema(tmp_path: Path) -> None:
    """The persisted JSON result has the required fields."""
    import json

    catalogue = _catalogue(tmp_path, _gate("pass", command="true"))
    log_dir = tmp_path / "logs"
    result = run_gate(catalogue["pass"], log_dir)
    path = log_dir / "pass.json"
    raw: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    assert raw["gate"] == "pass"
    assert raw["command"] == "true"
    assert isinstance(raw["exit_code"], int)
    assert isinstance(raw["duration"], float)
    assert "counts" in raw
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T-GATE-0004 — NOT_ACTIVE never counted
# ---------------------------------------------------------------------------
# id: T-GATE-0004
# title: NOT_ACTIVE gates are listed but never counted as passed
# purpose: Verify a gate activated in a later phase is NOT_ACTIVE, excluded from
#          the active set, and not counted.
# level: fast
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-ACTIVE
# input: a catalogue with one active and one NOT_ACTIVE gate
# expected result: gate_status == NOT_ACTIVE, active set excludes it, run returns 0
# risk covered: a not-yet-active gate is silently counted as a passing gate
# owning capability: gate-runner


@pytest.mark.fast
def test_not_active_never_counted(tmp_path: Path) -> None:
    """A NOT_ACTIVE gate is excluded from the active set and not counted."""
    text = _gate("active", command="true") + _gate("future", activates_in="P99")
    catalogue = _catalogue(tmp_path, text)
    assert gate_status(catalogue["future"], "P00") == "NOT_ACTIVE"
    assert "future" not in active_gate_names(catalogue, "P00")
    log_dir = tmp_path / "logs"
    code = run_set(["active", "future"], catalogue, log_dir, "P00", schedule={"P00": ("active",)})
    assert code == 0
    future_result = load_results(log_dir)
    future_json = [r for r in future_result if r.gate == "future"]
    assert future_json and future_json[0].reason == "NOT_ACTIVE"


# ---------------------------------------------------------------------------
# T-GATE-0005 — Overdue activation returns 2
# ---------------------------------------------------------------------------
# id: T-GATE-0005
# title: A required gate missing from the catalogue returns exit 2
# purpose: Verify that when the schedule requires a gate for the current phase
#          but it is not registered, the runner returns exit 2.
# level: fast
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-REQUIRED
# input: a schedule requiring "required" but a catalogue lacking it
# expected result: run_set returns 2; missing_required lists "required"
# risk covered: a gate is dropped from an active phase without detection
# owning capability: gate-runner


@pytest.mark.fast
def test_overdue_activation_returns_2(tmp_path: Path) -> None:
    """A missing required gate makes run_set return 2."""
    catalogue = _catalogue(tmp_path, _gate("present", command="true"))
    schedule = {"P00": ("required",)}
    assert "required" in missing_required(catalogue, "P00", schedule)
    log_dir = tmp_path / "logs"
    code = run_set(["present"], catalogue, log_dir, "P00", schedule=schedule)
    assert code == 2


# ---------------------------------------------------------------------------
# T-GATE-0006 — Generated gate table equals JSON results
# ---------------------------------------------------------------------------
# id: T-GATE-0006
# title: Generated gate table matches persisted JSON results
# purpose: Verify the rendered report reflects the JSON in .gate-logs/.
# level: fast
# requirement ids: P00-T03, Part 4 §4.3
# scenario ids: S-GATE-REPORT
# input: two gates run (exit 0 and exit 7)
# expected result: report rows match loaded JSON results
# risk covered: the gate table is hand-written rather than generated from logs
# owning capability: gate-runner


@pytest.mark.fast
def test_report_matches_json(tmp_path: Path) -> None:
    """The generated gate table matches the persisted JSON results."""
    text = _gate("alpha", command="true") + _gate("beta", command="exit 7")
    catalogue = _catalogue(tmp_path, text)
    log_dir = tmp_path / "logs"
    run_gate(catalogue["alpha"], log_dir)
    run_gate(catalogue["beta"], log_dir)
    results = load_results(log_dir)
    by_name = {r.gate: r for r in results}
    assert by_name["alpha"].exit_code == 0
    assert by_name["beta"].exit_code == 7
    report = render_report(log_dir)
    assert "| alpha | true | 0 |" in report
    assert "| beta | exit 7 | 7 |" in report


# ---------------------------------------------------------------------------
# T-GATE-0007 — gate affected fallback
# ---------------------------------------------------------------------------
# id: T-GATE-0007
# title: gate affected returns the complete slow set without a coverage map
# purpose: Verify the affected fallback returns every P-cadence non-Q gate.
# level: fast
# requirement ids: P00-T03, Part 4 §4.5
# scenario ids: S-GATE-AFFECTED
# input: a catalogue with QP, P-only and N gates
# expected result: affected_set returns only the P-cadence non-Q gates
# risk covered: the impact fallback runs the wrong (or no) slow gates
# owning capability: gate-runner


@pytest.mark.fast
def test_affected_fallback() -> None:
    """affected_set returns all P-cadence non-Q gates."""
    catalogue: dict[str, GateEntry] = {
        "fmt": GateEntry("fmt", "QP", "x", 1, "P00", None, None),
        "uni": GateEntry("uni", "QP", "x", 1, "P00", None, None),
        "self": GateEntry("self", "P", "x", 1, "P00", None, None),
        "state": GateEntry("state", "P", "x", 1, "P00", None, None),
        "night": GateEntry("night", "N", "x", 1, "P00", None, None),
    }
    affected = affected_set(catalogue)
    assert sorted(affected) == ["self", "state"]


# ---------------------------------------------------------------------------
# T-GATE-0008 — Unknown gate name returns 2
# ---------------------------------------------------------------------------
# id: T-GATE-0008
# title: Running an unknown gate name returns exit 2
# purpose: Verify an unknown gate name is a tool error (exit 2), not a failure.
# level: fast
# requirement ids: P00-T03, Part 4 §4.3
# scenario ids: S-GATE-UNKNOWN
# input: run_set with a name not in the catalogue
# expected result: run_set raises GateError (the CLI maps this to exit 2)
# risk covered: a typo in a gate name is silently treated as a pass
# owning capability: gate-runner


@pytest.mark.fast
def test_unknown_gate_returns_2(tmp_path: Path) -> None:
    """An unknown gate name raises GateError (mapped to exit 2 by the CLI)."""
    catalogue = _catalogue(tmp_path, _gate("present", command="true"))
    log_dir = tmp_path / "logs"
    with pytest.raises(GateError):
        run_set(["nope"], catalogue, log_dir, "P00", schedule={})


# ---------------------------------------------------------------------------
# T-GATE-HASH — gate hash matches shasum, including empty files
# ---------------------------------------------------------------------------
# id: T-GATE-HASH
# title: gate hash matches the system sha256 on fixture and empty files
# purpose: Verify hash_file is a stable, chunked SHA-256 identical to shasum.
# level: fast
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-HASH
# input: a fixture file and an empty file
# expected result: hash_file output equals `shasum -a 256` and the empty hash
# risk covered: a protected-file hash is non-deterministic or platform-dependent
# owning capability: gate-runner


@pytest.mark.fast
def test_hash_matches_shasum(tmp_path: Path) -> None:
    """hash_file matches the system shasum on a fixture file."""
    fixture = _FIXTURES / "format_clean.py"
    expected = hashlib.sha256(fixture.read_bytes()).hexdigest()
    assert hash_file(fixture) == expected
    # cross-check against the system shasum binary
    shasum = subprocess.run(
        ["shasum", "-a", "256", str(fixture)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert hash_file(fixture) == shasum.stdout.split()[0]


@pytest.mark.fast
def test_hash_empty_file(tmp_path: Path) -> None:
    """hash_file works on an empty file and yields the known empty SHA-256."""
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    assert hash_file(empty) == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


# ---------------------------------------------------------------------------
# T-GATE-KILL — timeout kills the whole process group, no child remains
# ---------------------------------------------------------------------------
# id: T-GATE-KILL
# title: Timeout kill leaves no process from the group alive
# purpose: Verify the process-group kill terminates child processes and none
#          of the group remains after kill_process_group returns.
# level: slow
# requirement ids: P00-T03, Part 4 §4.3, Part 1 §3.7
# scenario ids: S-GATE-GROUPKILL
# input: a process group with a backgrounded child sleep
# expected result: after kill_process_group, os.killpg(pgid, 0) raises
# risk covered: a child process survives the timeout and outlives the run
# owning capability: gate-runner


@pytest.mark.slow
def test_kill_process_group_leaves_no_child() -> None:
    """kill_process_group terminates the whole group including children."""
    proc = subprocess.Popen(
        "sleep 30 & sleep 30",
        shell=True,
        preexec_fn=os.setsid,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pgid = os.getpgid(proc.pid)
    time.sleep(0.3)  # let the shell start the backgrounded child
    kill_process_group(pgid)
    proc.wait()  # reap the leader so its child is reparented and reaped
    # poll briefly for the orphaned child to be reaped by init
    for _ in range(50):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)


# ---------------------------------------------------------------------------
# T-GATE-SELFTEST — the gate of gates
# ---------------------------------------------------------------------------
# id: T-GATE-SELFTEST
# title: selftest fails on bad fixtures and passes on good ones
# purpose: Verify selftest fails when a gate passes its violation fixture,
#          fails its clean fixture, lacks a fixture, or a required gate is
#          missing; and passes on a good catalogue.
# level: slow (uses real tool round-trips via the selftest fixtures)
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-SELFTEST
# input: mini-catalogues exercising each failure mode plus the selftest fixtures
# expected result: returns 1/2 for bad inputs, 0 for good inputs
# risk covered: a gate is loosened or turned into an always-pass stub unnoticed
# owning capability: gate-runner


@pytest.mark.fast
def test_selftest_passes_violation_returns_1(tmp_path: Path) -> None:
    """selftest fails when a gate passes its violation fixture."""
    (tmp_path / "v.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("x = 1\n", encoding="utf-8")
    text = _gate("demo", command="true", violation_fixture="v.py", clean_fixture="c.py")
    catalogue = _catalogue(tmp_path, text)
    code = run_selftest(catalogue, "P00", tmp_path, schedule={"P00": ("demo",)}, env=_env())
    assert code == 1


@pytest.mark.fast
def test_selftest_fails_clean_returns_1(tmp_path: Path) -> None:
    """selftest fails when a gate fails its clean fixture."""
    (tmp_path / "v.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("x = 1\n", encoding="utf-8")
    text = _gate("demo", command="false", violation_fixture="v.py", clean_fixture="c.py")
    catalogue = _catalogue(tmp_path, text)
    code = run_selftest(catalogue, "P00", tmp_path, schedule={"P00": ("demo",)}, env=_env())
    assert code == 1


@pytest.mark.fast
def test_selftest_missing_fixture_returns_2(tmp_path: Path) -> None:
    """selftest fails (exit 2) when an active gate lacks a fixture."""
    text = _gate("demo", command="true", violation_fixture="", clean_fixture="")
    catalogue = _catalogue(tmp_path, text)
    code = run_selftest(catalogue, "P00", tmp_path, schedule={"P00": ("demo",)}, env=_env())
    assert code == 2


@pytest.mark.fast
def test_selftest_required_gate_missing_returns_2(tmp_path: Path) -> None:
    """selftest fails (exit 2) when a required gate is missing."""
    text = _gate("demo", command="true")
    catalogue = _catalogue(tmp_path, text)
    schedule = {"P00": ("demo", "missing")}
    code = run_selftest(catalogue, "P00", tmp_path, schedule=schedule, env=_env())
    assert code == 2


@pytest.mark.fast
def test_selftest_clean_fixture_passes() -> None:
    """selftest returns 0 on the good selftest_clean catalogue."""
    catalogue = load_catalogue(_FIXTURES / "selftest_clean" / "catalogue.toml")
    code = run_selftest(catalogue, "P00", _FIXTURES, schedule={"P00": ("demo",)}, env=_env())
    assert code == 0


@pytest.mark.fast
def test_selftest_violation_fixture_fails() -> None:
    """selftest returns 1 on the bad selftest_violation catalogue."""
    catalogue = load_catalogue(_FIXTURES / "selftest_violation" / "catalogue.toml")
    code = run_selftest(catalogue, "P00", _FIXTURES, schedule={"P00": ("demo",)}, env=_env())
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-SELFTEST-REAL — real tool round-trip via the format/lint/types/unit
# fixtures (integration)
# ---------------------------------------------------------------------------
# id: T-GATE-SELFTEST-REAL
# title: selftest passes against the real P00 fixtures with real tools
# purpose: Verify run_selftest returns 0 when the format, lint, types and unit
#          gates are exercised against their real fixtures and tooling.
# level: slow
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-SELFTEST-REAL
# input: a catalogue of format/lint/types/unit with real fixtures
# expected result: run_selftest returns 0
# risk covered: fixtures or commands do not actually fail/pass as declared
# owning capability: gate-runner


@pytest.mark.slow
def test_selftest_real_round_trip() -> None:
    """run_selftest returns 0 against the real format/lint/types/unit fixtures."""

    def _entry(name: str, command: str, timeout: int, vf: str, cf: str) -> GateEntry:
        return GateEntry(name, "QP", command, timeout, "P00", _FIXTURES / vf, _FIXTURES / cf)

    catalogue: dict[str, GateEntry] = {
        "format": _entry(
            "format", "ruff format --check", 60, "format_violation.py", "format_clean.py"
        ),
        "lint": _entry("lint", "ruff check", 60, "lint_violation.py", "lint_clean.py"),
        "types": _entry("types", "mypy .", 120, "types_violation.py", "types_clean.py"),
        "unit": _entry(
            "unit", "pytest -m fast", 300, "test_unit_violation.py", "test_unit_clean.py"
        ),
    }
    schedule = {"P00": ("format", "lint", "types", "unit")}
    code = run_selftest(catalogue, "P00", _FIXTURES, schedule=schedule, env=_env())
    assert code == 0


# ---------------------------------------------------------------------------
# T-GATE-PHASE — current phase default and schedule helpers
# ---------------------------------------------------------------------------
# id: T-GATE-PHASE
# title: Phase parsing and default current phase
# purpose: Verify parse_phase_number and read_current_phase default behaviour.
# level: fast
# requirement ids: P00-T03, Part 6 §6.13
# scenario ids: S-GATE-PHASE
# input: phase strings and a missing STATE.json
# expected result: P00 -> 0; missing state defaults to P00
# risk covered: the current phase is misread and gates misclassified
# owning capability: gate-runner


@pytest.mark.fast
def test_parse_phase_number() -> None:
    """Phase ids parse to their numeric suffix."""
    assert parse_phase_number("P00") == 0
    assert parse_phase_number("P27") == 27
    assert parse_phase_number("P28") == 28


@pytest.mark.fast
def test_read_current_phase_default(tmp_path: Path) -> None:
    """A missing STATE.json defaults the current phase to P00."""
    state = tmp_path / "STATE.json"
    assert read_current_phase(state) == "P00"


# ---------------------------------------------------------------------------
# T-GATE-SETS — set selection
# ---------------------------------------------------------------------------
# id: T-GATE-SETS
# title: Set selection resolves quick / phase / nightly correctly
# purpose: Verify select_set picks the right cadence-filtered active gates.
# level: fast
# requirement ids: P00-T03, Part 4 §4.3
# scenario ids: S-GATE-SETS
# input: a catalogue with QP and P-only gates at P00
# expected result: quick -> Q gates; phase -> P gates; nightly -> all active
# risk covered: the wrong set of gates runs for a given cadence
# owning capability: gate-runner


@pytest.mark.fast
def test_select_sets(tmp_path: Path) -> None:
    """select_set resolves quick, phase and nightly against active gates."""
    text = _gate("fmt", command="true", cadence="QP") + _gate("self", command="true", cadence="P")
    cat = _catalogue(tmp_path, text)
    assert select_set("quick", cat, "P00") == ["fmt"]
    assert select_set("phase", cat, "P00") == ["fmt", "self"]
    assert select_set("nightly", cat, "P00") == ["fmt", "self"]
