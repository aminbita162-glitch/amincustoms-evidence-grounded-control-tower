"""Directive lint — Part 6 §6.15, §6.15b (cross-check), §6.15a (stub mode).

Implements ``gate directive`` which runs at every phase entry (Part 1 §8) and
in the export linter.  Fails on structural violations of the directive format
and, with ``--cross-check``, on mechanical consistency rules: identifier
closure, closed vocabularies, and key-fact consistency.

In stub mode (§6.15a) the directive is read from the parent commit of the
stub commit.  On main after the release merge, the gate prints ``RELEASED``
and exits 0.

Spec: Part 6 §6.15, §6.15a, §6.15b; P00-T11.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "DirectiveError",
    "PhaseBlock",
    "KeyFact",
    "MATCHING_MODES",
    "STATUS_WORDS",
    "LABELS",
    "PHASE_BLOCK_FIELDS",
    "parse_phase_blocks",
    "find_standalone_markers",
    "extract_context_pack_markers",
    "check_markers_exist_once",
    "check_phase_block_fields",
    "check_task_ids_sequential",
    "check_risk_before_end1",
    "check_test_id_ranges",
    "check_lookahead_phases_exist",
    "check_scope_paths_present",
    "check_block_count",
    "check_directive",
    "load_keyfacts",
    "check_keyfacts",
    "check_closed_vocabularies",
    "check_identifier_closure",
    "check_cross",
    "is_stub_mode",
    "read_parent_directive",
    "check_released",
    "run_directive_gate",
    "main",
]


class DirectiveError(Exception):
    """A directive lint configuration or read error."""


# ---------------------------------------------------------------------------
# Closed vocabularies (§6.15b)
# ---------------------------------------------------------------------------

MATCHING_MODES: frozenset[str] = frozenset({"PROTECTIVE", "NORMALIZED", "EXACT"})

STATUS_WORDS: frozenset[str] = frozenset(
    {"DONE", "PARKED", "STOP", "SKIP", "REVIEWED", "UNREVIEWED", "CHANGED_SINCE_REVIEW"}
)

LABELS: frozenset[str] = frozenset({"DEC", "ADV", "REP"})

# The eleven fields of §6.4 (numbered 1 through 11).
PHASE_BLOCK_FIELDS: tuple[int, ...] = tuple(range(1, 12))

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PhaseBlock:
    """A single ``<<<PHASE-NN>>>`` … ``<<<END-PHASE-NN>>>`` block."""

    id: str
    num: int
    start_line: int
    end_line: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class KeyFact:
    """One row of the ``<<<P8-KEYFACTS>>>`` table."""

    id: str
    value: str
    patterns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_PHASE_START_RE = re.compile(r"^<<<PHASE-(\d+)>>>")
_PHASE_END_RE = re.compile(r"^<<<END-PHASE-(\d+)>>>")
_STANDALONE_MARKER_RE = re.compile(r"^<<<([A-Z][A-Z0-9-]*)>>>$")
_MARKER_REF_RE = re.compile(r"<<<([A-Z][A-Z0-9-]*)>>>")


def parse_phase_blocks(text: str) -> list[PhaseBlock]:
    """Parse all ``<<<PHASE-NN>>>`` blocks from *text*."""
    lines = text.splitlines()
    blocks: list[PhaseBlock] = []
    i = 0
    while i < len(lines):
        m = _PHASE_START_RE.match(lines[i].strip())
        if m:
            num = int(m.group(1))
            pid = f"P{num:02d}"
            start = i + 1
            end = len(lines)
            for j in range(i + 1, len(lines)):
                em = _PHASE_END_RE.match(lines[j].strip())
                if em and int(em.group(1)) == num:
                    end = j + 1
                    break
            blocks.append(
                PhaseBlock(
                    id=pid,
                    num=num,
                    start_line=start,
                    end_line=end,
                    lines=lines[i:end],
                )
            )
            i = end
        else:
            i += 1
    return blocks


def find_standalone_markers(text: str) -> dict[str, list[int]]:
    """Find every standalone ``<<<MARKER>>>`` line and its line number(s)."""
    markers: dict[str, list[int]] = {}
    for idx, line in enumerate(text.splitlines(), 1):
        m = _STANDALONE_MARKER_RE.match(line.strip())
        if m:
            markers.setdefault(m.group(1), []).append(idx)
    return markers


def extract_context_pack_markers(block: PhaseBlock) -> list[str]:
    """Extract markers listed in field 5 (Context Pack) of *block*."""
    markers: list[str] = []
    in_field = False
    for line in block.lines:
        stripped = line.strip()
        if re.match(r"^5\.\s", stripped):
            in_field = True
        elif re.match(r"^\d+\.\s", stripped):
            in_field = False
        if in_field:
            for m in _MARKER_REF_RE.finditer(stripped):
                name = m.group(1)
                if name not in markers:
                    markers.append(name)
    return markers


# ---------------------------------------------------------------------------
# §6.15 structural checks
# ---------------------------------------------------------------------------


def check_markers_exist_once(text: str, blocks: list[PhaseBlock]) -> list[str]:
    """Check that every marker listed in a Context Pack exists exactly once."""
    standalone = find_standalone_markers(text)
    violations: list[str] = []
    for block in blocks:
        for marker in extract_context_pack_markers(block):
            count = len(standalone.get(marker, []))
            if count != 1:
                violations.append(
                    f"marker <<<{marker}>>> listed in Context Pack of {block.id} "
                    f"exists {count} time(s), expected exactly 1"
                )
    return violations


def check_phase_block_fields(blocks: list[PhaseBlock]) -> list[str]:
    """Check that each phase block has all eleven fields of §6.4."""
    violations: list[str] = []
    for block in blocks:
        found: set[int] = set()
        for line in block.lines:
            m = re.match(r"^(\d+)\.\s", line.strip())
            if m:
                found.add(int(m.group(1)))
        for field_num in PHASE_BLOCK_FIELDS:
            if field_num not in found:
                violations.append(f"phase block {block.id} missing field {field_num}")
    return violations


_TASK_ID_RE = re.compile(r"^(P\d{2}-T\d{2})\b", re.MULTILINE)


def check_task_ids_sequential(blocks: list[PhaseBlock]) -> list[str]:
    """Check that task ids in each phase block are sequential and not duplicated."""
    violations: list[str] = []
    for block in blocks:
        task_ids: list[str] = []
        for line in block.lines:
            task_ids.extend(_TASK_ID_RE.findall(line))
        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for tid in task_ids:
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
        if len(task_ids) != len(unique):
            violations.append(f"phase block {block.id} has duplicate task ids")
        for idx, tid in enumerate(unique):
            expected = f"{block.id}-T{idx + 1:02d}"
            if tid != expected:
                violations.append(
                    f"phase block {block.id} task id {tid} is not sequential (expected {expected})"
                )
                break
    return violations


_TASKLIKE_RE = re.compile(r"\b(P\d{2}-(?:T\d{2}|RISK|END1|END2))\b")


def check_risk_before_end1(blocks: list[PhaseBlock]) -> list[str]:
    """Check that ``Pnn-RISK`` is present (from P01) and immediately before ``Pnn-END1``."""
    violations: list[str] = []
    for block in blocks:
        if block.num < 1:
            continue
        ids: list[str] = []
        for line in block.lines:
            ids.extend(_TASKLIKE_RE.findall(line))
        seen: set[str] = set()
        unique: list[str] = []
        for tid in ids:
            if tid not in seen:
                seen.add(tid)
                unique.append(tid)
        risk_idx: int | None = None
        end1_idx: int | None = None
        for idx, tid in enumerate(unique):
            if tid.endswith("-RISK"):
                risk_idx = idx
            if tid.endswith("-END1"):
                end1_idx = idx
        if risk_idx is None:
            violations.append(f"phase block {block.id} missing {block.id}-RISK")
        elif end1_idx is not None and risk_idx != end1_idx - 1:
            violations.append(
                f"phase block {block.id} {block.id}-RISK is not immediately before {block.id}-END1"
            )
    return violations


_TEST_RANGE_RE = re.compile(r"T-([A-Z]+)-(\d{4})\s+to\s+T-\1-(\d{4})")


def check_test_id_ranges(blocks: list[PhaseBlock]) -> list[str]:
    """Check that no test id range in field 7 is declared twice."""
    violations: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    for block in blocks:
        in_field = False
        for line in block.lines:
            stripped = line.strip()
            if re.match(r"^7\.\s", stripped):
                in_field = True
            elif re.match(r"^\d+\.\s", stripped):
                in_field = False
            if in_field:
                for m in _TEST_RANGE_RE.finditer(stripped):
                    area = m.group(1)
                    start_num = int(m.group(2))
                    end_num = int(m.group(3))
                    key = (area, start_num, end_num)
                    if key in seen:
                        violations.append(
                            f"test id range T-{area}-{start_num:04d} to "
                            f"T-{area}-{end_num:04d} declared twice"
                        )
                    seen.add(key)
    return violations


def check_lookahead_phases_exist(blocks: list[PhaseBlock]) -> list[str]:
    """Check that phases named in look-ahead (field 10) exist."""
    all_ids = {b.id for b in blocks}
    violations: list[str] = []
    for block in blocks:
        in_field = False
        for line in block.lines:
            stripped = line.strip()
            if re.match(r"^10\.\s", stripped):
                in_field = True
            elif re.match(r"^\d+\.\s", stripped):
                in_field = False
            if in_field:
                for m in re.finditer(r"\b(P\d{2})\b", stripped):
                    if m.group(1) not in all_ids:
                        violations.append(
                            f"phase block {block.id} look-ahead references "
                            f"non-existent phase {m.group(1)}"
                        )
    return violations


def check_scope_paths_present(blocks: list[PhaseBlock]) -> list[str]:
    """Check that each phase block has a ``Scope paths:`` line."""
    violations: list[str] = []
    for block in blocks:
        if not any("Scope paths:" in line for line in block.lines):
            violations.append(f"phase block {block.id} missing 'Scope paths:' line")
    return violations


def check_block_count(blocks: list[PhaseBlock], phases_count: int) -> list[str]:
    """Check that the block count matches ``phases.toml``."""
    if len(blocks) != phases_count:
        return [f"block count {len(blocks)} != phases.toml count {phases_count}"]
    return []


def check_directive(text: str, phases_count: int) -> list[str]:
    """Run all §6.15 structural checks.  Returns a list of violations (empty = clean)."""
    blocks = parse_phase_blocks(text)
    violations: list[str] = []
    violations.extend(check_markers_exist_once(text, blocks))
    violations.extend(check_phase_block_fields(blocks))
    violations.extend(check_task_ids_sequential(blocks))
    violations.extend(check_risk_before_end1(blocks))
    violations.extend(check_test_id_ranges(blocks))
    violations.extend(check_lookahead_phases_exist(blocks))
    violations.extend(check_scope_paths_present(blocks))
    violations.extend(check_block_count(blocks, phases_count))
    return violations


# ---------------------------------------------------------------------------
# §6.15b cross-check
# ---------------------------------------------------------------------------

_KF_LINE_RE = re.compile(r"^(KF-\d+)\s*\|\s*(\S+)\s*\|.*?\|(.+)$")


def load_keyfacts(text: str) -> list[KeyFact]:
    """Parse the ``<<<P8-KEYFACTS>>>`` table from *text*."""
    start = text.find("<<<P8-KEYFACTS>>>")
    end = text.find("<<<END-P8-KEYFACTS>>>")
    if start == -1 or end == -1:
        return []
    table = text[start:end]
    facts: list[KeyFact] = []
    for line in table.splitlines():
        m = _KF_LINE_RE.match(line.strip())
        if m:
            kid = m.group(1)
            value = m.group(2)
            patterns = [p.strip() for p in m.group(3).split(";;") if p.strip()]
            facts.append(KeyFact(id=kid, value=value, patterns=patterns))
    return facts


def check_keyfacts(text: str, facts: list[KeyFact]) -> list[str]:
    """Check that every key-fact expression yields the correct value (§6.15b c).

    The table block itself is excluded from the scan.
    """
    if not facts:
        return []
    start = text.find("<<<P8-KEYFACTS>>>")
    end = text.find("<<<END-P8-KEYFACTS>>>")
    if start == -1 or end == -1:
        return ["key-fact table not found"]
    end_marker_len = len("<<<END-P8-KEYFACTS>>>")
    scan_text = text[:start] + text[end + end_marker_len :]
    violations: list[str] = []
    for fact in facts:
        for pattern in fact.patterns:
            if not pattern:
                continue
            try:
                regex = re.compile(pattern)
            except re.error:
                violations.append(f"key-fact {fact.id}: invalid regex {pattern!r}")
                continue
            matches = regex.findall(scan_text)
            if not matches:
                violations.append(f"key-fact {fact.id}: expression {pattern!r} matches nowhere")
                continue
            for match in matches:
                value = str(match).replace(",", "")
                if value != fact.value:
                    violations.append(f"key-fact {fact.id}: expected {fact.value}, got {value}")
    return violations


_MODE_RE = re.compile(r"matching mode\s+([A-Z]+)", re.IGNORECASE)
_STATUS_RE = re.compile(r"status\s+([A-Z]+)", re.IGNORECASE)
_LABEL_RE = re.compile(r"\blabel\s+([A-Z]+)", re.IGNORECASE)
_OUTCOME_RE = re.compile(r"\boutcome\s+([A-Z]+)", re.IGNORECASE)
_REASON_CODE_REF_RE = re.compile(r"reason code[:\s]+([A-Z]+\d*)\.", re.IGNORECASE)
_REGISTER_DEF_RE = re.compile(r"<<<([A-Z]+\d*)-")


def check_closed_vocabularies(text: str) -> list[str]:
    """Check closed vocabularies: matching modes, labels, status words (§6.15b b)."""
    # Exclude the key-fact table from the scan.
    start = text.find("<<<P8-KEYFACTS>>>")
    end = text.find("<<<END-P8-KEYFACTS>>>")
    if start != -1 and end != -1:
        end_marker_len = len("<<<END-P8-KEYFACTS>>>")
        scan_text = text[:start] + text[end + end_marker_len :]
    else:
        scan_text = text
    violations: list[str] = []
    for m in _MODE_RE.finditer(scan_text):
        mode = m.group(1).upper()
        if mode not in MATCHING_MODES:
            violations.append(f"unknown matching mode: {m.group(1)}")
    for m in _LABEL_RE.finditer(scan_text):
        label = m.group(1).upper()
        if label not in LABELS:
            violations.append(f"unknown label: {m.group(1)}")
    for m in _STATUS_RE.finditer(scan_text):
        word = m.group(1).upper()
        if word not in STATUS_WORDS:
            violations.append(f"unknown status word: {m.group(1)}")
    for m in _OUTCOME_RE.finditer(scan_text):
        word = m.group(1).upper()
        if word not in STATUS_WORDS:
            violations.append(f"unknown outcome word: {m.group(1)}")
    return violations


def check_identifier_closure(text: str) -> list[str]:
    """Check that every referenced register id resolves to a definition (§6.15b a).

    A simplified check: reason-code references of the form ``reason code: D06.``
    must have a matching ``<<<D06-`` marker definition.
    """
    # Exclude the key-fact table from the scan.
    start = text.find("<<<P8-KEYFACTS>>>")
    end = text.find("<<<END-P8-KEYFACTS>>>")
    if start != -1 and end != -1:
        end_marker_len = len("<<<END-P8-KEYFACTS>>>")
        scan_text = text[:start] + text[end + end_marker_len :]
    else:
        scan_text = text
    defined: set[str] = set()
    for m in _REGISTER_DEF_RE.finditer(text):
        defined.add(m.group(1))
    violations: list[str] = []
    for m in _REASON_CODE_REF_RE.finditer(scan_text):
        prefix = m.group(1)
        if prefix and prefix not in defined:
            violations.append(f"undefined reason code prefix: {prefix}")
    return violations


def check_cross(text: str) -> list[str]:
    """Run all §6.15b cross-check rules.  Returns violations (empty = clean)."""
    violations: list[str] = []
    violations.extend(check_identifier_closure(text))
    violations.extend(check_closed_vocabularies(text))
    facts = load_keyfacts(text)
    violations.extend(check_keyfacts(text, facts))
    return violations


# ---------------------------------------------------------------------------
# §6.15a stub mode
# ---------------------------------------------------------------------------


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _git_out(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _git_show(rev_path: str, repo_root: Path) -> str:
    """Show the content of a file at a given revision (no stripping)."""
    result = subprocess.run(
        ["git", "show", rev_path],
        cwd=str(repo_root),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def is_stub_mode(repo_root: Path) -> bool:
    """Check whether all stub-mode conditions hold (§6.15a)."""
    directive_path = repo_root / "directive.txt"
    stub_path = repo_root / "tools" / "gate" / "stub.txt"
    if not directive_path.is_file() or not stub_path.is_file():
        return False
    # Condition 1: content equals stub.txt byte for byte.
    if directive_path.read_bytes() != stub_path.read_bytes():
        return False
    # Condition 2: last commit is P32-STUB.
    last_msg = _git_out(["log", "-1", "--format=%B"], repo_root)
    if "P32-STUB" not in last_msg:
        return False
    # Condition 3: last commit changes only directive.txt.
    changed = _git_out(["show", "--name-only", "--format=", "HEAD"], repo_root)
    changed_files = [f.strip() for f in changed.splitlines() if f.strip()]
    if changed_files != ["directive.txt"]:
        return False
    # Condition 4: parent is the P32-END2 commit.
    parent = _git_out(["rev-parse", "HEAD~1"], repo_root)
    if not parent:
        return False
    parent_msg = _git_out(["log", "-1", "--format=%B", parent], repo_root)
    if "P32-END2" not in parent_msg:
        return False
    # Condition 5: SHA-256 of directive.txt at parent matches STATE.json.
    state_path = repo_root / "docs" / "state" / "STATE.json"
    if not state_path.is_file():
        return False
    try:
        state_raw: object = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return False
    if not isinstance(state_raw, dict):
        return False
    state_hash = str(state_raw.get("directive_hash", ""))
    parent_directive = _git_show(f"{parent}:directive.txt", repo_root)
    parent_hash = hashlib.sha256(parent_directive.encode("utf-8")).hexdigest()
    return parent_hash == state_hash


def read_parent_directive(repo_root: Path) -> str:
    """Read ``directive.txt`` from the parent commit of the stub commit."""
    parent = _git_out(["rev-parse", "HEAD~1"], repo_root)
    return _git_show(f"{parent}:directive.txt", repo_root)


def check_released(repo_root: Path) -> int:
    """Check the RELEASED condition: on main with the stub and STATE at P32 DONE."""
    directive_path = repo_root / "directive.txt"
    stub_path = repo_root / "tools" / "gate" / "stub.txt"
    if not directive_path.is_file() or not stub_path.is_file():
        return 1
    if directive_path.read_bytes() != stub_path.read_bytes():
        return 1
    state_path = repo_root / "docs" / "state" / "STATE.json"
    if not state_path.is_file():
        return 1
    try:
        state_raw: object = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return 1
    if not isinstance(state_raw, dict):
        return 1
    if state_raw.get("last_completed_phase") != "P32":
        return 1
    state_hash = str(state_raw.get("directive_hash", ""))
    actual_hash = hashlib.sha256(directive_path.read_bytes()).hexdigest()
    if state_hash != actual_hash:
        return 1
    print("RELEASED")
    return 0


# ---------------------------------------------------------------------------
# Gate entry point
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _gate_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_phases_count(path: Path) -> int:
    try:
        with path.open("rb") as stream:
            raw: object = tomllib.load(stream)
        phase_table: object = raw.get("phase") if isinstance(raw, dict) else None
        if isinstance(phase_table, dict):
            return len(phase_table)
    except OSError, tomllib.TOMLDecodeError:
        pass
    return 0


def _is_released(repo_root: Path) -> bool:
    """Check the RELEASED condition without printing."""
    directive_path = repo_root / "directive.txt"
    stub_path = repo_root / "tools" / "gate" / "stub.txt"
    if not directive_path.is_file() or not stub_path.is_file():
        return False
    if directive_path.read_bytes() != stub_path.read_bytes():
        return False
    state_path = repo_root / "docs" / "state" / "STATE.json"
    if not state_path.is_file():
        return False
    try:
        state_raw: object = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError, OSError:
        return False
    if not isinstance(state_raw, dict):
        return False
    if state_raw.get("last_completed_phase") != "P32":
        return False
    state_hash = str(state_raw.get("directive_hash", ""))
    actual_hash = hashlib.sha256(directive_path.read_bytes()).hexdigest()
    return state_hash == actual_hash


def run_directive_gate(
    repo_root: Path,
    *,
    cross_check: bool = False,
) -> int:
    """Run the directive gate.  Returns 0 (pass), 1 (violation), 2 (misconfiguration).

    When ``directive.txt`` exists in the current working directory (e.g. a
    selftest fixture), it is read from there; otherwise from *repo_root*.
    """
    # RELEASED: on main with the stub and STATE at P32 DONE.
    if _is_released(repo_root):
        print("RELEASED")
        return 0

    # Stub mode: read the directive from the parent commit.
    if is_stub_mode(repo_root):
        try:
            directive_text = read_parent_directive(repo_root)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"directive: cannot read parent directive: {exc}", file=sys.stderr)
            return 2
        phases_path = _gate_dir() / "phases.toml"
    else:
        # Prefer cwd (selftest fixtures); fall back to repo root.
        cwd = Path.cwd()
        cwd_directive = cwd / "directive.txt"
        if cwd_directive.is_file() and cwd != repo_root:
            directive_text = cwd_directive.read_text(encoding="utf-8")
            cwd_phases = cwd / "phases.toml"
            phases_path = cwd_phases if cwd_phases.is_file() else _gate_dir() / "phases.toml"
        else:
            directive_path = repo_root / "directive.txt"
            if not directive_path.is_file():
                print("directive: directive.txt not found", file=sys.stderr)
                return 2
            directive_text = directive_path.read_text(encoding="utf-8")
            # Verify hash against STATE.json (outside stub mode, a changed
            # directive.txt whose hash differs is a directive integrity failure).
            state_path = repo_root / "docs" / "state" / "STATE.json"
            if state_path.is_file():
                try:
                    state_raw: object = json.loads(state_path.read_text(encoding="utf-8"))
                    if isinstance(state_raw, dict):
                        state_hash = str(state_raw.get("directive_hash", ""))
                        if state_hash:
                            actual_hash = hashlib.sha256(directive_text.encode("utf-8")).hexdigest()
                            if state_hash != actual_hash:
                                print(
                                    "directive: hash mismatch (directive.txt changed "
                                    "outside stub mode)",
                                    file=sys.stderr,
                                )
                                return 1
                except json.JSONDecodeError, OSError:
                    pass
            phases_path = _gate_dir() / "phases.toml"

    phases_count = _load_phases_count(phases_path)

    if cross_check:
        violations = check_cross(directive_text)
        if violations:
            for v in violations:
                print(f"directive: {v}", file=sys.stderr)
            return 1
        print("no violation of the listed rules")
        return 0

    violations = check_directive(directive_text, phases_count)
    if violations:
        for v in violations:
            print(f"directive: {v}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Entry point for the directive gate."""
    args = sys.argv[1:]
    cross_check = "--cross-check" in args
    return run_directive_gate(_repo_root(), cross_check=cross_check)


if __name__ == "__main__":
    sys.exit(main())
