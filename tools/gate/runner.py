"""Core gate runner: catalogue loading, gate execution, sets, selftest, report.

This module is importable and free of CLI concerns so tests can exercise the
runner logic directly with temporary catalogues and schedules.

Spec: Part 4 §4.3, Part 6 §6.13 (P00-T03).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import tempfile
import time
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SCHEDULE",
    "MisconfigurationError",
    "GateError",
    "GateEntry",
    "GateResult",
    "ExecutionResult",
    "load_catalogue",
    "parse_phase_number",
    "read_current_phase",
    "gate_status",
    "active_gate_names",
    "required_gate_names",
    "missing_required",
    "select_set",
    "affected_set",
    "execute_command",
    "kill_process_group",
    "run_gate",
    "run_set",
    "run_selftest",
    "hash_file",
    "render_report",
    "write_result",
    "default_env",
]

# Gate activation schedule (Part 6 §6.13). A gate listed for a phase is required,
# registered, passing and counted from the end of that phase on. This mapping is
# the source of truth that selftest cross-checks the catalogue against, so a gate
# cannot be silently dropped from an active phase.
SCHEDULE: dict[str, tuple[str, ...]] = {
    "P00": (
        "format",
        "lint",
        "types",
        "unit",
        "index",
        "state",
        "docs",
        "hygiene",
        "secrets",
        "security",
        "deps",
        "license",
        "protect",
        "directive",
        "scope",
        "chain",
        "selftest",
    ),
    "P01": ("risk",),
    "P02": ("data", "labels"),
    "P03": ("arch", "generated-files", "contract", "property", "mutation"),
    "P04": ("integration", "migration"),
    "P05": ("replay",),
    "P06": ("differential", "metamorphic", "perf"),
    "P07": ("containment", "fuzz"),
    "P08": ("eval",),
    "P09": ("e2e", "trace"),
    "P10": ("chaos",),
    "P11": ("leakage",),
    "P12": ("restore", "image"),
    "P27": ("a11y",),
    "P28": ("soak",),
}

_CHUNK = 65536
_KILL_GRACE_SECONDS = 5.0
_KILL_POLL_SECONDS = 0.1


class MisconfigurationError(Exception):
    """Catalogue or runner misconfiguration (exit code 2)."""


class GateError(Exception):
    """A referenced gate is unknown or otherwise not runnable (exit code 2)."""


@dataclass(frozen=True)
class GateEntry:
    """A single gate catalogue entry."""

    name: str
    cadence: str
    command: str
    timeout: int
    activates_in: str
    violation_fixture: Path | None
    clean_fixture: Path | None


@dataclass(frozen=True)
class ExecutionResult:
    """Raw outcome of executing one command in its own process group."""

    exit_code: int
    duration: float
    reason: str | None
    killed: tuple[str, ...]


@dataclass(frozen=True)
class GateResult:
    """A persisted gate result written to ``.gate-logs/``."""

    gate: str
    command: str
    exit_code: int
    duration: float
    counts: dict[str, int] = field(default_factory=dict)
    reason: str | None = None
    killed: tuple[str, ...] = ()


def _setsid() -> None:
    """Start a new session/process group for the child (preexec_fn)."""
    os.setsid()


def default_env(project_root: Path | None = None) -> dict[str, str]:
    """Return ``os.environ`` with the project venv bin prepended to PATH."""
    env = dict(os.environ)
    if project_root is not None:
        venv_bin = project_root / ".venv" / "bin"
        if venv_bin.is_dir():
            existing = env.get("PATH", "")
            env["PATH"] = str(venv_bin) + (os.pathsep + existing if existing else "")
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(project_root) + (os.pathsep + existing_pp if existing_pp else "")
    return env


def parse_phase_number(phase: str) -> int:
    """``"P00"`` -> ``0``, ``"P27"`` -> ``27``."""
    if len(phase) < 2 or phase[0] != "P" or not phase[1:].isdigit():
        raise MisconfigurationError(f"invalid phase id: {phase!r}")
    return int(phase[1:])


def read_current_phase(state_path: Path) -> str:
    """Read ``last_completed_phase`` from STATE.json; default to ``P00`` if absent."""
    if not state_path.is_file():
        return "P00"
    try:
        raw: object = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MisconfigurationError(f"cannot read state file {state_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise MisconfigurationError(f"state file {state_path} is not an object")
    value = raw.get("last_completed_phase", "P00")
    if not isinstance(value, str):
        raise MisconfigurationError("last_completed_phase must be a string")
    return value


def gate_status(entry: GateEntry, current_phase: str) -> str:
    """``ACTIVE`` if the gate has activated at or before the current phase."""
    return (
        "ACTIVE"
        if parse_phase_number(entry.activates_in) <= parse_phase_number(current_phase)
        else "NOT_ACTIVE"
    )


def active_gate_names(catalogue: dict[str, GateEntry], current_phase: str) -> list[str]:
    """Names of gates active at the current phase, in catalogue order."""
    return [
        name for name, entry in catalogue.items() if gate_status(entry, current_phase) == "ACTIVE"
    ]


def required_gate_names(
    current_phase: str,
    schedule: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """All gates the schedule requires at or before the current phase."""
    table = schedule if schedule is not None else SCHEDULE
    current = parse_phase_number(current_phase)
    required: list[str] = []
    for phase_id, gates in table.items():
        if parse_phase_number(phase_id) <= current:
            required.extend(gates)
    # de-duplicate, preserve first-seen order
    seen: set[str] = set()
    ordered: list[str] = []
    for gate in required:
        if gate not in seen:
            seen.add(gate)
            ordered.append(gate)
    return ordered


def missing_required(
    catalogue: dict[str, GateEntry],
    current_phase: str,
    schedule: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Scheduled gates for the current phase that are not registered."""
    return [gate for gate in required_gate_names(current_phase, schedule) if gate not in catalogue]


def select_set(
    set_name: str,
    catalogue: dict[str, GateEntry],
    current_phase: str,
) -> list[str]:
    """Resolve a named set to active gate names.

    quick = Q-cadence active gates; phase = P-cadence active gates;
    nightly/release = every active gate.
    """
    active = active_gate_names(catalogue, current_phase)
    if set_name == "quick":
        return [n for n in active if "Q" in catalogue[n].cadence]
    if set_name == "phase":
        return [n for n in active if "P" in catalogue[n].cadence]
    if set_name in ("nightly", "release"):
        return active
    raise GateError(f"unknown set: {set_name!r}")


def affected_set(catalogue: dict[str, GateEntry]) -> list[str]:
    """The complete slow set (P-cadence, non-Q gates) until a coverage map exists."""
    return [
        name
        for name, entry in catalogue.items()
        if "P" in entry.cadence and "Q" not in entry.cadence
    ]


def _group_alive(pgid: int) -> bool:
    """Best-effort liveness check for a process group (signal 0)."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_process_names(pgid: int) -> list[str]:
    """Best-effort names of processes in the group (via ``ps``)."""
    try:
        ps = subprocess.run(
            ["ps", "-o", "comm=", "-g", str(pgid)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return [token for token in ps.stdout.split() if token]
    except OSError, subprocess.SubprocessError, ValueError:
        return []


def kill_process_group(pgid: int) -> list[str]:
    """SIGTERM the group, wait the grace period, then SIGKILL if still alive.

    Returns the best-effort names of processes that had to be killed. The caller
    that owns the process handle is responsible for reaping the leader.
    """
    names = _group_process_names(pgid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return names

    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return names
        time.sleep(_KILL_POLL_SECONDS)

    # still alive after the grace period -> force kill
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError, PermissionError:
        return names

    # let the forced kill take effect
    for _ in range(50):
        if not _group_alive(pgid):
            return names
        time.sleep(_KILL_POLL_SECONDS)
    return names


def _terminate_group(pgid: int, proc: subprocess.Popen[bytes]) -> list[str]:
    """Terminate a process group, reaping the leader via ``proc``.

    SIGTERM the group, wait up to the grace period for the leader to end, then
    SIGKILL the group if the leader is still alive. Returns killed process names.
    """
    names = _group_process_names(pgid)
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return names
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return names
        time.sleep(_KILL_POLL_SECONDS)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pgid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.communicate(timeout=10)
    return names


def execute_command(
    command: str,
    timeout: int,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> ExecutionResult:
    """Run ``command`` in its own process group; enforce timeout with group kill."""
    start = time.monotonic()
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd) if cwd is not None else None,
        env=env if env is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=_setsid,
    )
    pgid = os.getpgid(proc.pid)
    killed: list[str] = []
    reason: str | None = None
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        killed = _terminate_group(pgid, proc)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=10)
        reason = "TIMEOUT"

    exit_code = proc.returncode if proc.returncode is not None else -1
    duration = time.monotonic() - start
    return ExecutionResult(
        exit_code=exit_code,
        duration=duration,
        reason=reason,
        killed=tuple(killed),
    )


def _counts_for(exit_code: int) -> dict[str, int]:
    return {"passed": 1 if exit_code == 0 else 0, "failed": 0 if exit_code == 0 else 1}


def run_gate(
    entry: GateEntry,
    log_dir: Path,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> GateResult:
    """Execute a gate and persist its JSON result to ``log_dir``."""
    execution = execute_command(entry.command, entry.timeout, cwd=cwd, env=env)
    result = GateResult(
        gate=entry.name,
        command=entry.command,
        exit_code=execution.exit_code,
        duration=execution.duration,
        counts=_counts_for(execution.exit_code),
        reason=execution.reason,
        killed=execution.killed,
    )
    write_result(result, log_dir)
    return result


def write_result(result: GateResult, log_dir: Path) -> Path:
    """Write a gate result as ``<log_dir>/<gate>.json`` (latest result per gate)."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"{result.gate}.json"
    payload: dict[str, object] = {
        "gate": result.gate,
        "command": result.command,
        "exit_code": result.exit_code,
        "duration": result.duration,
        "counts": result.counts,
        "reason": result.reason,
        "killed": list(result.killed),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def load_results(log_dir: Path) -> list[GateResult]:
    """Load all persisted gate results, sorted by gate name."""
    results: list[GateResult] = []
    if not log_dir.is_dir():
        return results
    for path in sorted(log_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        reason_raw = raw.get("reason")
        results.append(
            GateResult(
                gate=str(raw["gate"]),
                command=str(raw["command"]),
                exit_code=int(raw["exit_code"]),
                duration=float(raw["duration"]),
                counts={
                    str(k): int(v) for k, v in raw.get("counts", {}).items() if isinstance(v, int)
                },
                reason=str(reason_raw) if reason_raw is not None else None,
                killed=tuple(str(x) for x in raw.get("killed", [])),
            )
        )
    return results


def render_report(log_dir: Path) -> str:
    """Render the generated gate table (markdown) from ``.gate-logs/`` results."""
    results = load_results(log_dir)
    lines = ["| gate | command | exit_code | duration | reason |", "|---|---|---|---|---|"]
    for result in results:
        lines.append(
            f"| {result.gate} | {result.command} | {result.exit_code} | "
            f"{result.duration:.3f} | {result.reason or ''} |"
        )
    return "\n".join(lines)


def run_set(
    gate_names: list[str],
    catalogue: dict[str, GateEntry],
    log_dir: Path,
    current_phase: str,
    schedule: Mapping[str, Sequence[str]] | None = None,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Run a list of gates. Return 0 all passed, 1 a gate failed, 2 misconfiguration."""
    missing = missing_required(catalogue, current_phase, schedule)
    if missing:
        return 2
    exit_code = 0
    for name in gate_names:
        if name not in catalogue:
            raise GateError(f"unknown gate: {name!r}")
        entry = catalogue[name]
        if gate_status(entry, current_phase) != "ACTIVE":
            # listed but never counted as passed
            not_active = GateResult(
                gate=name,
                command=entry.command,
                exit_code=0,
                duration=0.0,
                counts={},
                reason="NOT_ACTIVE",
            )
            write_result(not_active, log_dir)
            continue
        result = run_gate(entry, log_dir, cwd=cwd, env=env)
        if result.exit_code != 0:
            exit_code = 1
    return exit_code


def _fixture_target(fixture: Path, dest: Path) -> None:
    """Copy a fixture file or directory tree into a temporary directory."""
    if fixture.is_dir():
        for item in fixture.rglob("*"):
            if item.is_file():
                relative = item.relative_to(fixture)
                target = dest / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(item.read_bytes())
    else:
        (dest / fixture.name).write_bytes(fixture.read_bytes())


def run_selftest(
    catalogue: dict[str, GateEntry],
    current_phase: str,
    project_root: Path,
    schedule: Mapping[str, Sequence[str]] | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """The gate of gates (Part 6 §6.13).

    For every active gate except ``selftest`` itself, run the gate's command in a
    temporary directory holding the violation fixture (must fail) and the clean
    fixture (must pass). Also fail when the active set lacks a gate the schedule
    requires for the current phase, or when an active gate lacks either fixture.
    """
    missing = missing_required(catalogue, current_phase, schedule)
    if missing:
        return 2

    for name in active_gate_names(catalogue, current_phase):
        if name == "selftest":
            continue
        entry = catalogue[name]
        if entry.violation_fixture is None or entry.clean_fixture is None:
            return 2
        violation_fixture = _resolve_fixture(entry.violation_fixture, project_root)
        clean_fixture = _resolve_fixture(entry.clean_fixture, project_root)
        if not violation_fixture.exists() or not clean_fixture.exists():
            return 2
        # violation fixture must make the gate fail
        with tempfile.TemporaryDirectory() as temp_dir:
            _fixture_target(violation_fixture, Path(temp_dir))
            fixture_env = dict(env) if env else {}
            fixture_env["GATE_ROOT"] = temp_dir
            violation_run = execute_command(
                entry.command, entry.timeout, cwd=Path(temp_dir), env=fixture_env
            )
        if violation_run.exit_code == 0:
            return 1
        # clean fixture must make the gate pass
        with tempfile.TemporaryDirectory() as temp_dir:
            _fixture_target(clean_fixture, Path(temp_dir))
            fixture_env = dict(env) if env else {}
            fixture_env["GATE_ROOT"] = temp_dir
            clean_run = execute_command(
                entry.command, entry.timeout, cwd=Path(temp_dir), env=fixture_env
            )
        if clean_run.exit_code != 0:
            return 1
    return 0


def _resolve_fixture(fixture: Path, project_root: Path) -> Path:
    """Resolve a fixture path relative to the gate package directory when not absolute."""
    if fixture.is_absolute():
        return fixture
    gate_dir = Path(__file__).resolve().parent
    return gate_dir / fixture


def hash_file(path: Path) -> str:
    """SHA-256 of a file read in 64KB chunks, lowercase hex. Stable across platforms."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        chunk = stream.read(_CHUNK)
        while chunk:
            digest.update(chunk)
            chunk = stream.read(_CHUNK)
    return digest.hexdigest()


def _to_path(value: object) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def _parse_entry(name: str, raw: dict[str, object]) -> GateEntry:
    def require(field_name: str) -> object:
        if field_name not in raw:
            raise MisconfigurationError(f"gate.{name} missing required field {field_name}")
        return raw[field_name]

    cadence = require("cadence")
    command = require("command")
    timeout = require("timeout")
    activates_in = require("activates_in")
    violation_fixture = require("violation_fixture")
    clean_fixture = require("clean_fixture")

    if not isinstance(cadence, str):
        raise MisconfigurationError(f"gate.{name}.cadence must be a string")
    if not isinstance(command, str):
        raise MisconfigurationError(f"gate.{name}.command must be a string")
    if not isinstance(timeout, int) or isinstance(timeout, bool):
        raise MisconfigurationError(f"gate.{name}.timeout must be an integer")
    if not isinstance(activates_in, str):
        raise MisconfigurationError(f"gate.{name}.activates_in must be a string")

    parse_phase_number(activates_in)

    return GateEntry(
        name=name,
        cadence=cadence,
        command=command,
        timeout=timeout,
        activates_in=activates_in,
        violation_fixture=_to_path(violation_fixture),
        clean_fixture=_to_path(clean_fixture),
    )


def load_catalogue(path: Path) -> dict[str, GateEntry]:
    """Load the gate catalogue from a TOML file.

    The catalogue uses ``[gate.NAME]`` tables, which TOML nests under a top-level
    ``gate`` table. Fixture paths are resolved relative to the catalogue file.
    """
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MisconfigurationError(f"cannot load catalogue {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise MisconfigurationError(f"catalogue {path} is not a table")
    gate_table: object = raw.get("gate")
    if not isinstance(gate_table, dict):
        raise MisconfigurationError(f"catalogue {path} has no [gate.*] tables")
    entries: dict[str, GateEntry] = {}
    base = path.resolve().parent
    for gate_name, value in gate_table.items():
        if not isinstance(value, dict):
            raise MisconfigurationError(f"gate.{gate_name} must be a table")
        entry = _parse_entry(gate_name, value)
        # resolve fixtures relative to the catalogue directory
        if entry.violation_fixture is not None and not entry.violation_fixture.is_absolute():
            entry = GateEntry(
                name=entry.name,
                cadence=entry.cadence,
                command=entry.command,
                timeout=entry.timeout,
                activates_in=entry.activates_in,
                violation_fixture=base / entry.violation_fixture,
                clean_fixture=entry.clean_fixture,
            )
        if entry.clean_fixture is not None and not entry.clean_fixture.is_absolute():
            entry = GateEntry(
                name=entry.name,
                cadence=entry.cadence,
                command=entry.command,
                timeout=entry.timeout,
                activates_in=entry.activates_in,
                violation_fixture=entry.violation_fixture,
                clean_fixture=base / entry.clean_fixture,
            )
        entries[gate_name] = entry
    return entries
