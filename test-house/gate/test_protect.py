"""Tests for the protect gate (P00-T07).

Tests T-GATE-0025 to T-GATE-0029 cover the protected paths gate: a modified
protected file fails, a modified hashes file fails, ``--update`` without a
task fails, a clean tree passes, and a new protected file missing from the
hashes file fails.  An additional test verifies that ``tools/gate/stub.txt``
equals the two lines of ``<<<P7-STUB>>>`` byte for byte and is listed in
``protected.toml``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gate.gates.protect import (
    check_protected,
    load_protected_paths,
    update_hashes,
)
from tools.gate.runner import hash_file

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_DIR = REPO_ROOT / "tools" / "gate"

# The exact two lines of <<<P7-STUB>>> section 2 (directive.txt lines
# 6583-6584), LF line endings, one final newline.
_STUB_LINE_1 = (
    "This file was the build directive of this project; "
    "development is complete and the file holds no instructions."
)
_STUB_LINE_2 = "Product documentation is in README.md and in the docs directory."
_STUB_BYTES = f"{_STUB_LINE_1}\n{_STUB_LINE_2}\n".encode("ascii")


def _write_protected_toml(tmp_path: Path, paths: list[str]) -> Path:
    """Write a protected.toml with the given paths into *tmp_path*."""
    lines = ["[paths]"]
    for p in paths:
        lines.append(f'"{p}" = true')
    lines.append("")
    path = tmp_path / "protected.toml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_hashes(tmp_path: Path, hashes: dict[str, str]) -> Path:
    """Write a protected-hashes.json with the given hashes into *tmp_path*."""
    path = tmp_path / "protected-hashes.json"
    path.write_text(
        json.dumps(hashes, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# T-GATE-0025 — a modified protected file fails
# ---------------------------------------------------------------------------
# id: T-GATE-0025
# title: a modified protected file fails the protect gate
# purpose: Verify that a protected file whose content has been modified after
#          the hashes were recorded fails the protect gate.
# level: fast
# requirement ids: P00-T07, Part 1 §5.5
# scenario ids: S-GATE-PROTECT-MODIFIED
# input: a temp repo with a protected file and its correct hash, then the
#        file is modified
# expected result: check_protected returns 1
# risk covered: a modified protected file is not detected by the gate
# owning capability: gate-protect


@pytest.mark.fast
def test_modified_protected_file_fails(tmp_path: Path) -> None:
    """A modified protected file fails the protect gate."""
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    protected = _write_protected_toml(tmp_path, ["LICENSE"])
    hashes = _write_hashes(tmp_path, {"LICENSE": hash_file(tmp_path / "LICENSE")})
    # Modify the protected file after the hash was recorded.
    (tmp_path / "LICENSE").write_text("GPL License\n", encoding="utf-8")
    code = check_protected(tmp_path, protected_paths_file=protected, hashes_file=hashes)
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-0026 — a modified hashes file fails
# ---------------------------------------------------------------------------
# id: T-GATE-0026
# title: a modified hashes file (wrong hash) fails the protect gate
# purpose: Verify that a hashes file containing a wrong hash for a protected
#          file fails the protect gate.
# level: fast
# requirement ids: P00-T07, Part 1 §5.5
# scenario ids: S-GATE-PROTECT-HASHES
# input: a temp repo with a protected file and a hashes file containing a
#        wrong hash for that file
# expected result: check_protected returns 1
# risk covered: a tampered hashes file is not detected by the gate
# owning capability: gate-protect


@pytest.mark.fast
def test_modified_hashes_file_fails(tmp_path: Path) -> None:
    """A hashes file with a wrong hash fails the protect gate."""
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    protected = _write_protected_toml(tmp_path, ["LICENSE"])
    # Write a wrong hash (all zeros) for the protected file.
    hashes = _write_hashes(tmp_path, {"LICENSE": "0" * 64})
    code = check_protected(tmp_path, protected_paths_file=protected, hashes_file=hashes)
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-0027 — --update without a task fails
# ---------------------------------------------------------------------------
# id: T-GATE-0027
# title: --update without a task that changes a protected path fails
# purpose: Verify that gate protect --update refuses to run when no task
#          changes a protected path (no git diff and no explicit task paths).
# level: fast
# requirement ids: P00-T07, Part 1 §5.5
# scenario ids: S-GATE-PROTECT-UPDATE
# input: a temp repo with a protected file and its correct hash, --update
#        called with an empty task_paths list
# expected result: update_hashes returns 1
# risk covered: the hashes file is rewritten outside a task that names a path
# owning capability: gate-protect


@pytest.mark.fast
def test_update_without_task_fails(tmp_path: Path) -> None:
    """--update without a task that changes a protected path fails."""
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    protected = _write_protected_toml(tmp_path, ["LICENSE"])
    hashes = _write_hashes(tmp_path, {"LICENSE": hash_file(tmp_path / "LICENSE")})
    code = update_hashes(
        tmp_path,
        protected_paths_file=protected,
        hashes_file=hashes,
        task_paths=[],
    )
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-0028 — a clean tree passes
# ---------------------------------------------------------------------------
# id: T-GATE-0028
# title: a clean tree with matching hashes passes the protect gate
# purpose: Verify that a clean tree where every protected file's hash matches
#          the recorded hash passes the protect gate.
# level: fast
# requirement ids: P00-T07, Part 1 §5.5
# scenario ids: S-GATE-PROTECT-CLEAN
# input: a temp repo with a protected file and its correct hash
# expected result: check_protected returns 0
# risk covered: a clean tree is falsely flagged as a protect violation
# owning capability: gate-protect


@pytest.mark.fast
def test_clean_tree_passes(tmp_path: Path) -> None:
    """A clean tree with matching hashes passes the protect gate."""
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    protected = _write_protected_toml(tmp_path, ["LICENSE"])
    hashes = _write_hashes(tmp_path, {"LICENSE": hash_file(tmp_path / "LICENSE")})
    code = check_protected(tmp_path, protected_paths_file=protected, hashes_file=hashes)
    assert code == 0


# ---------------------------------------------------------------------------
# T-GATE-0029 — a new protected file missing from the hashes file fails
# ---------------------------------------------------------------------------
# id: T-GATE-0029
# title: a new protected file not in the hashes file fails the protect gate
# purpose: Verify that a protected file that exists on disk but is missing
#          from the hashes file fails the protect gate.
# level: fast
# requirement ids: P00-T07, Part 1 §5.5
# scenario ids: S-GATE-PROTECT-MISSING
# input: a temp repo with a protected file listed in protected.toml but
#        absent from the hashes file
# expected result: check_protected returns 1
# risk covered: a new protected file is not recorded in the hashes file
# owning capability: gate-protect


@pytest.mark.fast
def test_new_protected_file_missing_from_hashes_fails(tmp_path: Path) -> None:
    """A new protected file not in the hashes file fails the protect gate."""
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    protected = _write_protected_toml(tmp_path, ["LICENSE"])
    # Empty hashes — the file exists but has no recorded hash.
    hashes = _write_hashes(tmp_path, {})
    code = check_protected(tmp_path, protected_paths_file=protected, hashes_file=hashes)
    assert code == 1


# ---------------------------------------------------------------------------
# T-GATE-STUB — stub.txt equals the two lines of <<<P7-STUB>>> byte for byte
# ---------------------------------------------------------------------------
# id: T-GATE-STUB
# title: stub.txt equals the two lines of <<<P7-STUB>>> and is protected
# purpose: Verify that tools/gate/stub.txt contains the exact two lines from
#          section 2 of <<<P7-STUB>>> (two lines, LF endings, one final
#          newline) and is listed in protected.toml.
# level: fast
# requirement ids: P00-T07, Part 1 §5.5, Part 7 §7.8
# scenario ids: S-GATE-PROTECT-STUB
# input: the real tools/gate/stub.txt and protected.toml from the repository
# expected result: stub.txt bytes equal the two exact lines; the path is listed
# risk covered: the stub text or its protection listing is wrong
# owning capability: gate-protect


@pytest.mark.fast
def test_stub_txt_matches_directive_bytes() -> None:
    """stub.txt equals the two lines of <<<P7-STUB>>> byte for byte."""
    stub_path = GATE_DIR / "stub.txt"
    content = stub_path.read_bytes()
    assert content == _STUB_BYTES


@pytest.mark.fast
def test_stub_txt_listed_in_protected_toml() -> None:
    """stub.txt is listed in protected.toml."""
    protected = load_protected_paths(GATE_DIR / "protected.toml")
    assert "tools/gate/stub.txt" in protected
