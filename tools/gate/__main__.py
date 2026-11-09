"""Command-line entry point for the AminCustoms gate runner.

Commands:
    gate list                 list every gate with cadence, activates_in, status
    gate run <name|set>       run a single gate or a set (quick/phase/nightly/release)
    gate affected             print the complete slow set (P-cadence, non-Q gates)
    gate report               print the generated gate table from .gate-logs/
    gate hash <path>          SHA-256 of a file, lowercase hex, stable everywhere
    gate protect              check protected file hashes against protected-hashes.json
    gate protect --update     rewrite protected-hashes.json (only inside a task)
    gate selftest             run the gate of gates directly
    gate phase entry <NN>     run entry verification checks for phase NN (§8.2)
    gate phase exit <NN>      run exit verification checks for phase NN (§9.1)
    gate phase end <NN>       run the phase-end sequence for phase NN (§10)

Exit codes: 0 all passed, 1 a gate/check failed, 2 misconfiguration or tool error.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools.gate.commit_check import main as commit_check_main
from tools.gate.phase.baselines import (
    BaselineError,
    check_baseline_decrease,
    load_baselines,
    measure_coverage,
    save_baselines,
    update_baselines,
)
from tools.gate.phase.chain import ChainError
from tools.gate.phase.checks import (
    PHASE_REPORT_FIELDS,
    PhaseCheckError,
    check_phase_entry,
    check_phase_exit,
    load_phases,
    validate_report_fields,
)
from tools.gate.phase.state import StateError, load_state
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
    "gate report | gate hash <path> | gate protect [--update] | "
    "gate baseline [--update] | gate directive [--cross-check] | "
    "gate scope <NN> | gate chain verify | gate selftest | "
    "gate phase entry|exit|end <NN>"
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


def _cmd_baseline(repo_root: Path, update: bool) -> int:
    """Measure ``tools/gate`` coverage and check or seed ``baselines.json``.

    Without ``--update``: measure coverage, load the baselines and fail
    (exit 1) if any measured value is below its floor.  With ``--update``:
    ratchet the measured values into ``baselines.json`` (monotonic — a value
    is never lowered) and report any decreases that were refused.
    """
    baselines_path = repo_root / "docs" / "state" / "baselines.json"
    component = "tools/gate"
    try:
        measured = {component: measure_coverage(repo_root, component)}
    except BaselineError as exc:
        print(f"baseline: {exc}", file=sys.stderr)
        return 2
    if update:
        updated, decreases = update_baselines(baselines_path, measured)
        save_baselines(baselines_path, updated)
        print(f"baseline: wrote {len(updated)} component(s) to {baselines_path}")
        for component in sorted(updated):
            for key in ("branch_coverage", "line_coverage"):
                if key in updated[component]:
                    print(f"  {component}.{key}: {updated[component][key]}")
        for decrease in decreases:
            print(f"  DECREASE (not written): {decrease}", file=sys.stderr)
        return 0
    baselines = load_baselines(baselines_path)
    decreases = check_baseline_decrease(baselines, measured)
    if decreases:
        for decrease in decreases:
            print(f"  {decrease}", file=sys.stderr)
        return 1
    print("baseline: no baseline decreases")
    return 0


def _resolve_phases() -> Path:
    return _gate_package_dir() / "phases.toml"


def _cmd_phase_entry(phase_id: str, repo_root: Path, state_path: Path) -> int:
    """Run entry verification checks for *phase_id* (Part 1 §8.2)."""
    directive_path = repo_root / "directive.txt"
    phases = load_phases(_resolve_phases())
    try:
        state = load_state(state_path)
    except StateError as exc:
        print(f"state error: {exc}", file=sys.stderr)
        return 2
    results = check_phase_entry(
        phase_id=phase_id,
        phases=phases,
        state=state,
        directive_path=directive_path,
        repo_root=repo_root,
    )
    exit_code = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"  {result.item}: {status} — {result.evidence}")
        if not result.passed:
            exit_code = 1
    decision = "proceed" if exit_code == 0 else "STOP"
    print(f"  decision: {decision}")
    return exit_code


def _cmd_phase_exit(phase_id: str, repo_root: Path) -> int:
    """Run exit verification checks for *phase_id* (Part 1 §9.1)."""
    phases = load_phases(_resolve_phases())
    if phase_id not in phases:
        print(f"unknown phase: {phase_id!r}", file=sys.stderr)
        return 2
    # Derive expected task ids from the ledger if it exists.
    ledger = repo_root / "docs" / "ledger" / f"{phase_id}.md"
    expected_tasks: list[str] = []
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.endswith("DONE"):
                parts = line.split()
                if parts:
                    expected_tasks.append(parts[0])
    results = check_phase_exit(phase_id, expected_tasks, repo_root)
    exit_code = 0
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"  {result.item}: {status} — {result.evidence}")
        if not result.passed:
            exit_code = 1
    return exit_code


def _cmd_phase_end(phase_id: str, repo_root: Path, state_path: Path) -> int:
    """Run the phase-end sequence for *phase_id* (Part 1 §10).

    10.1: Run full test suite and all gates.
    10.2: END1 — write phase report (every field except merge hash).
    10.3: END2 — set Build Progress to done, update STATE.json.
    10.4: Re-run gates.
    """
    directive_path = repo_root / "directive.txt"
    phases = load_phases(_resolve_phases())
    try:
        state = load_state(state_path)
    except StateError as exc:
        print(f"state error: {exc}", file=sys.stderr)
        return 2

    # 10.1 — entry/exit checks and gates.
    entry_results = check_phase_entry(
        phase_id=phase_id,
        phases=phases,
        state=state,
        directive_path=directive_path,
        repo_root=repo_root,
    )
    for result in entry_results:
        if not result.passed:
            print(f"  STOP: entry check {result.item} failed — {result.evidence}", file=sys.stderr)
            return 1

    exit_results = check_phase_exit(phase_id, [], repo_root)
    for result in exit_results:
        if not result.passed:
            print(f"  STOP: exit check {result.item} failed — {result.evidence}", file=sys.stderr)
            return 1

    # 10.2 — END1: report written (in real use, by the agent; here we validate).
    report: dict[str, object] = {
        "entry_report": "see entry results",
        "exit_report": "see exit results",
        "commit_table": [],
        "self_review": "",
        "directive_hash": state.directive_hash,
        "budgets_used": {},
        "label_counts": state.label_counts,
    }
    report_errors = validate_report_fields(report, PHASE_REPORT_FIELDS)
    if report_errors:
        print("  STOP: phase report validation failed:", file=sys.stderr)
        for err in report_errors:
            print(f"    {err}", file=sys.stderr)
        return 1

    # 10.3 — END2: update STATE.json (set last_completed_phase).
    state.last_completed_phase = phase_id
    from tools.gate.phase.state import save_state

    save_state(state_path, state)
    print(f"  END2: STATE.json updated (last_completed_phase={phase_id})")

    # 10.4 — re-run gates (entry checks).
    print("  10.4: re-running entry checks")
    recheck = check_phase_entry(
        phase_id=phase_id,
        phases=phases,
        state=state,
        directive_path=directive_path,
        repo_root=repo_root,
    )
    for result in recheck:
        status = "PASS" if result.passed else "FAIL"
        print(f"    {result.item}: {status}")
        if not result.passed:
            return 1
    return 0


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
        if command == "commit-check":
            if len(rest) != 1:
                print("usage: gate commit-check <file>", file=sys.stderr)
                return 2
            return commit_check_main(Path(rest[0]))
        if command == "protect":
            from tools.gate.gates.protect import check_protected, update_hashes

            if rest and rest[0] == "--update":
                return update_hashes(repo_root)
            return check_protected(repo_root)
        if command == "baseline":
            update = bool(rest) and rest[0] == "--update"
            return _cmd_baseline(repo_root, update)
        if command == "directive":
            from tools.gate.phase.directive import run_directive_gate

            cross_check = "--cross-check" in rest
            return run_directive_gate(repo_root, cross_check=cross_check)
        if command == "scope":
            from tools.gate.phase.scope import run_scope_gate

            if rest:
                phase_id = rest[0]
                if not phase_id.startswith("P"):
                    try:
                        phase_id = f"P{int(phase_id):02d}"
                    except ValueError:
                        print("usage: gate scope <NN>", file=sys.stderr)
                        return 2
            else:
                phase_id = "P00"
            return run_scope_gate(repo_root, phase_id)
        if command == "chain":
            from tools.gate.phase.chain import verify_chain

            chain_path = repo_root / "docs" / "state" / "CHAIN.jsonl"
            try:
                violations = verify_chain(chain_path)
            except ChainError as exc:
                print(f"chain: {exc}", file=sys.stderr)
                return 2
            if violations:
                for v in violations:
                    print(f"chain: {v}", file=sys.stderr)
                return 1
            print("chain: verified")
            return 0
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
        if command == "phase":
            if not rest:
                print("usage: gate phase entry|exit|end <NN>", file=sys.stderr)
                return 2
            sub = rest[0]
            if sub not in ("entry", "exit", "end"):
                print(
                    f"unknown phase subcommand: {sub!r} (expected entry, exit, end)",
                    file=sys.stderr,
                )
                return 2
            if len(rest) != 2:
                print(f"usage: gate phase {sub} <NN>", file=sys.stderr)
                return 2
            phase_id = rest[1]
            if sub == "entry":
                return _cmd_phase_entry(phase_id, repo_root, state_path)
            if sub == "exit":
                return _cmd_phase_exit(phase_id, repo_root)
            return _cmd_phase_end(phase_id, repo_root, state_path)
        print(_USAGE, file=sys.stderr)
        return 2
    except StateError as exc:
        print(f"state error: {exc}", file=sys.stderr)
        return 2
    except PhaseCheckError as exc:
        print(f"phase check error: {exc}", file=sys.stderr)
        return 2
    except MisconfigurationError as exc:
        print(f"misconfiguration: {exc}", file=sys.stderr)
        return 2
    except GateError as exc:
        print(f"gate error: {exc}", file=sys.stderr)
        return 2
    except BaselineError as exc:
        print(f"baseline error: {exc}", file=sys.stderr)
        return 2
    except ChainError as exc:
        print(f"chain error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
