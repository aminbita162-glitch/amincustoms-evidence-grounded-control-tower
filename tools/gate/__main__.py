"""Command-line entry point for the AminCustoms gate runner.

Commands:
    gate list                 list every gate with cadence, activates_in, status
    gate run <name|set>       run a single gate or a set (quick/phase/nightly/release)
    gate affected             print the complete slow set (P-cadence, non-Q gates)
    gate report               print the generated gate table from .gate-logs/
    gate hash <path>          SHA-256 of a file, lowercase hex, stable everywhere
    gate selftest             run the gate of gates directly

Exit codes: 0 all passed, 1 a gate failed, 2 misconfiguration or tool error.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.gate.runner import (
    SCHEDULE,
    GateEntry,
    GateError,
    MisconfigurationError,
    affected_set,
    default_env,
    gate_status,
    hash_file,
    load_catalogue,
    missing_required,
    read_current_phase,
    render_report,
    run_gate,
    run_selftest,
    select_set,
)


def _gate_package_dir() -> Path:
    """The ``tools/gate`` package directory (this file's parent)."""
    return Path(__file__).resolve().parent


def _repo_root() -> Path:
    """The repository root (parent of the ``tools`` directory)."""
    return _gate_package_dir().parent.parent


def _resolve_catalogue() -> Path:
    return _gate_package_dir() / "catalogue.toml"


_USAGE = (
    "usage: gate list | gate run <name|set> | gate affected | "
    "gate report | gate hash <path> | gate selftest"
)

_SET_NAMES = ("quick", "phase", "nightly", "release")


def _cmd_list(catalogue: dict[str, GateEntry], current_phase: str) -> int:
    for name in sorted(catalogue):
        entry = catalogue[name]
        status = gate_status(entry, current_phase)
        print(f"{name}\t{entry.cadence}\t{entry.activates_in}\t{status}")
    return 0


def _cmd_run(
    target: str,
    catalogue: dict[str, GateEntry],
    log_dir: Path,
    current_phase: str,
    env: dict[str, str],
    cwd: Path,
) -> int:
    missing = missing_required(catalogue, current_phase, SCHEDULE)
    if missing:
        print(f"misconfiguration: missing required gates: {', '.join(missing)}", file=sys.stderr)
        return 2
    if target in _SET_NAMES:
        names = select_set(target, catalogue, current_phase)
    elif target in catalogue:
        names = [target]
    else:
        print(f"unknown gate or set: {target!r}", file=sys.stderr)
        return 2
    for name in names:
        entry = catalogue[name]
        if gate_status(entry, current_phase) != "ACTIVE":
            print(f"{name}: NOT_ACTIVE (activates_in {entry.activates_in})")
            continue
        result = run_gate(entry, log_dir, cwd=cwd, env=env)
        print(
            f"{name}: exit {result.exit_code} ({result.duration:.3f}s)"
            + (f" reason={result.reason}" if result.reason else "")
        )
        if result.exit_code != 0:
            return 1
    return 0


def _cmd_affected(catalogue: dict[str, GateEntry]) -> int:
    for name in sorted(affected_set(catalogue)):
        print(name)
    return 0


def _cmd_report(log_dir: Path) -> int:
    print(render_report(log_dir))
    return 0


def _cmd_hash(path: Path) -> int:
    print(hash_file(path))
    return 0


def _cmd_selftest(
    catalogue: dict[str, GateEntry],
    current_phase: str,
    repo_root: Path,
    env: dict[str, str],
) -> int:
    code = run_selftest(
        catalogue=catalogue,
        current_phase=current_phase,
        project_root=repo_root,
        schedule=SCHEDULE,
        env=env,
    )
    if code != 0:
        print(f"selftest: exit {code}", file=sys.stderr)
    return code


def main() -> int:
    """Parse argv and dispatch to the matching subcommand."""
    args = sys.argv[1:]
    if not args:
        print(_USAGE, file=sys.stderr)
        return 2
    command = args[0]
    rest = args[1:]

    repo_root = _repo_root()
    log_dir = repo_root / ".gate-logs"
    state_path = repo_root / "docs" / "state" / "STATE.json"
    env = default_env(repo_root)

    try:
        if command == "hash":
            if len(rest) != 1:
                print("usage: gate hash <path>", file=sys.stderr)
                return 2
            return _cmd_hash(Path(rest[0]))
        if command == "report":
            return _cmd_report(log_dir)
        if command == "affected":
            catalogue = load_catalogue(_resolve_catalogue())
            return _cmd_affected(catalogue)

        catalogue = load_catalogue(_resolve_catalogue())
        current_phase = read_current_phase(state_path)

        if command == "list":
            return _cmd_list(catalogue, current_phase)
        if command == "run":
            if len(rest) != 1:
                print("usage: gate run <name|set>", file=sys.stderr)
                return 2
            return _cmd_run(rest[0], catalogue, log_dir, current_phase, env, repo_root)
        if command == "selftest":
            return _cmd_selftest(catalogue, current_phase, repo_root, env)
        print(_USAGE, file=sys.stderr)
        return 2
    except MisconfigurationError as exc:
        print(f"misconfiguration: {exc}", file=sys.stderr)
        return 2
    except GateError as exc:
        print(f"gate error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
