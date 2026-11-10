"""Quarantine-tree for the Control Tower phase machinery (P00-T13).

Implements the quarantine-tree command of Part 1 §7.5a(b): stores the dirty
state as a patch bundle with a manifest under the ignored path
``.gate-quarantine/``, verifies the bundle on a temporary copy of HEAD, and
only then returns the working tree to HEAD.  Also implements the interruption
record of Part 1 §12.6.

Spec: Part 1 §7.5a(b), §12.6; Part 6 §6.16 (P00-T13).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = [
    "QuarantineError",
    "INTERRUPTION_RECORD_FIELDS",
    "quarantine_tree",
    "create_bundle",
    "verify_bundle",
    "create_interruption_record",
    "validate_interruption_record",
    "main",
]


class QuarantineError(Exception):
    """A quarantine-tree error."""


# Required fields for an interruption record (Part 1 §12.6).
INTERRUPTION_RECORD_FIELDS: tuple[str, ...] = (
    "phase",
    "interrupted_task",
    "last_done_task",
    "bundle_hash",
    "paths",
    "untouched",
)


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #


def _git_env() -> dict[str, str]:
    """Environment for git subprocess calls (sets DEVELOPER_DIR)."""
    env = dict(os.environ)
    if "DEVELOPER_DIR" not in env:
        env["DEVELOPER_DIR"] = "/Library/Developer/CommandLineTools"
    return env


def _git_run(args: list[str], repo_root: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in *repo_root* and return the completed process."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        env=_git_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _git_out(args: list[str], repo_root: Path) -> str:
    """Run a git command and return stdout stripped (empty on failure)."""
    return _git_run(args, repo_root).stdout.strip()


def _git_process_running(repo_root: Path) -> bool:
    """Check if any git process is running inside *repo_root* (best-effort).

    Uses ``pgrep -x git`` to find git PIDs, then checks each one's working
    directory with ``lsof`` to filter to only processes whose cwd is within
    *repo_root*.  This avoids false positives from git processes running in
    other repositories (e.g. parallel test workers).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-x", "git"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    repo_str = str(repo_root.resolve())
    for pid in result.stdout.strip().splitlines():
        pid = pid.strip()
        if not pid:
            continue
        try:
            lsof = subprocess.run(
                ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            # lsof unavailable — assume the process is unrelated.
            continue
        if lsof.returncode == 0:
            for line in lsof.stdout.splitlines():
                if line.startswith("n") and repo_str in line[1:]:
                    return True
    return False


# --------------------------------------------------------------------------- #
# Bundle creation
# --------------------------------------------------------------------------- #


def _untracked_files(repo_root: Path) -> list[str]:
    """Return the list of untracked, non-ignored file paths."""
    status = _git_out(["status", "--porcelain", "--untracked-files=all"], repo_root)
    files: list[str] = []
    for line in status.splitlines():
        if not line:
            continue
        if line.startswith("?? "):
            path = line[3:].strip().strip('"')
            if path.endswith("/"):
                path = path.rstrip("/")
            files.append(path)
    return files


def create_bundle(repo_root: Path, bundle_dir: Path) -> str:
    """Create a patch bundle with manifest under *bundle_dir*.

    Stores tracked changes as a ``git diff`` patch and copies untracked,
    non-ignored files.  Writes a manifest with SHA-256 hashes and the dirty
    tree hash.  Returns the SHA-256 of the manifest JSON.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Capture tracked changes.
    diff_result = _git_run(["diff", "HEAD"], repo_root)
    patch_content = diff_result.stdout
    patch_path = bundle_dir / "dirty.patch"
    patch_path.write_text(patch_content, encoding="utf-8")

    # Capture untracked files.
    untracked_dir = bundle_dir / "untracked"
    untracked_info: list[dict[str, str]] = []
    for fpath in _untracked_files(repo_root):
        src = repo_root / fpath
        if src.is_file():
            content = src.read_bytes()
            dst = untracked_dir / fpath
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content)
            untracked_info.append({"path": fpath, "sha256": hashlib.sha256(content).hexdigest()})

    # Compute the dirty tree hash.
    _git_run(["add", "-A"], repo_root)
    dirty_tree = _git_out(["write-tree"], repo_root)
    _git_run(["reset", "HEAD"], repo_root)

    # Write the manifest.
    manifest: dict[str, object] = {
        "patch_sha256": hashlib.sha256(patch_content.encode("utf-8")).hexdigest(),
        "untracked_files": untracked_info,
        "dirty_tree_hash": dirty_tree,
    }
    manifest_json = json.dumps(manifest, indent=2, sort_keys=True)
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(manifest_json, encoding="utf-8")

    return hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Bundle verification
# --------------------------------------------------------------------------- #


def verify_bundle(repo_root: Path, bundle_dir: Path) -> bool:
    """Verify that applying the bundle to a temp copy of HEAD reproduces the dirty tree hash.

    Creates a temporary git worktree from HEAD, applies the patch, copies
    untracked files, stages all, and compares the resulting tree hash with
    the ``dirty_tree_hash`` in the manifest.
    """
    manifest_path = bundle_dir / "manifest.json"
    if not manifest_path.is_file():
        return False

    manifest_raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest_raw, dict):
        return False
    expected_tree = manifest_raw.get("dirty_tree_hash")
    if not isinstance(expected_tree, str):
        return False

    patch_path = bundle_dir / "dirty.patch"
    untracked_dir = bundle_dir / "untracked"

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_repo = Path(tmpdir) / "verify"
        add_result = _git_run(["worktree", "add", str(temp_repo), "HEAD"], repo_root)
        if add_result.returncode != 0:
            return False
        try:
            # Apply the patch.
            if patch_path.is_file():
                patch_text = patch_path.read_text(encoding="utf-8")
                if patch_text.strip():
                    apply_result = subprocess.run(
                        ["git", "apply", str(patch_path)],
                        cwd=str(temp_repo),
                        env=_git_env(),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if apply_result.returncode != 0:
                        return False

            # Copy untracked files.
            untracked_raw = manifest_raw.get("untracked_files", [])
            if isinstance(untracked_raw, list):
                for entry in untracked_raw:
                    if isinstance(entry, dict):
                        fpath = entry.get("path")
                        if isinstance(fpath, str) and fpath:
                            src = untracked_dir / fpath
                            dst = temp_repo / fpath
                            if src.is_file():
                                dst.parent.mkdir(parents=True, exist_ok=True)
                                dst.write_bytes(src.read_bytes())

            # Compute the tree hash.
            subprocess.run(
                ["git", "add", "-A"],
                cwd=str(temp_repo),
                env=_git_env(),
                capture_output=True,
                text=True,
                check=False,
            )
            tree_result = subprocess.run(
                ["git", "write-tree"],
                cwd=str(temp_repo),
                env=_git_env(),
                capture_output=True,
                text=True,
                check=False,
            )
            if tree_result.returncode != 0:
                return False
            actual_tree = tree_result.stdout.strip()
            return actual_tree == expected_tree
        finally:
            _git_run(["worktree", "remove", "--force", str(temp_repo)], repo_root)
            _git_run(["worktree", "prune"], repo_root)


# --------------------------------------------------------------------------- #
# Interruption record
# --------------------------------------------------------------------------- #


def _parse_ledger_done_tasks(repo_root: Path, phase_id: str) -> list[str]:
    """Return the list of task ids with DONE lines for *phase_id*, in order."""
    ledger = repo_root / "docs" / "ledger" / f"{phase_id}.md"
    if not ledger.is_file():
        return []
    done: list[str] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.endswith("DONE"):
            parts = stripped.split()
            if parts:
                done.append(parts[0])
    return done


def create_interruption_record(repo_root: Path, phase_id: str, bundle_dir: Path) -> str:
    """Create an interruption record (Part 1 §12.6).

    Returns the path to the created record file.
    """
    manifest_path = bundle_dir / "manifest.json"
    bundle_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()

    done_tasks = _parse_ledger_done_tasks(repo_root, phase_id)
    last_done = done_tasks[-1] if done_tasks else "none"

    # Find the interrupted task (first without DONE line).
    interrupted_task = "unknown"
    for i in range(1, 100):
        candidate = f"{phase_id}-T{i:02d}"
        if candidate not in done_tasks:
            interrupted_task = candidate
            break

    # Collect paths from the manifest.
    manifest_raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    paths: list[str] = []
    if isinstance(manifest_raw, dict):
        untracked_raw = manifest_raw.get("untracked_files", [])
        if isinstance(untracked_raw, list):
            for entry in untracked_raw:
                if isinstance(entry, dict) and isinstance(entry.get("path"), str):
                    paths.append(str(entry["path"]))

    report_dir = repo_root / "docs" / "phase-reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    existing = list(report_dir.glob(f"{phase_id}-INT-*.md"))
    seq = len(existing) + 1

    record = (
        f"phase: {phase_id}\n"
        f"interrupted_task: {interrupted_task}\n"
        f"last_done_task: {last_done}\n"
        f"bundle_hash: {bundle_hash}\n"
        f"paths: {', '.join(paths) if paths else 'none'}\n"
        f"untouched: all other tasks\n"
    )

    record_path = report_dir / f"{phase_id}-INT-{seq}.md"
    record_path.write_text(record, encoding="utf-8")
    return str(record_path)


def validate_interruption_record(text: str) -> list[str]:
    """Validate an interruption record (Part 1 §12.6).

    Accepts either a ``Field: value`` text format or a JSON object.
    Returns a list of error messages (empty = valid).
    """
    errors: list[str] = []
    fields: dict[str, str] = {}

    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            raw: object = json.loads(stripped)
        except json.JSONDecodeError as exc:
            return [f"invalid JSON: {exc}"]
        if not isinstance(raw, dict):
            return ["interruption record is not a JSON object"]
        for key in INTERRUPTION_RECORD_FIELDS:
            value = raw.get(key)
            if value is not None:
                fields[key] = str(value)
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            colon = line.find(":")
            if colon < 0:
                continue
            key = line[:colon].strip().lower().replace(" ", "_")
            value = line[colon + 1 :].strip()
            fields[key] = value

    for field_name in INTERRUPTION_RECORD_FIELDS:
        if field_name not in fields or not fields[field_name]:
            errors.append(f"missing required field {field_name!r}")

    for field_name in fields:
        if field_name not in INTERRUPTION_RECORD_FIELDS:
            errors.append(f"extra field {field_name!r} not in interruption record schema")

    return errors


# --------------------------------------------------------------------------- #
# Quarantine-tree
# --------------------------------------------------------------------------- #


def quarantine_tree(repo_root: Path, phase_id: str) -> int:
    """Run the quarantine-tree command of Part 1 §7.5a(b).

    Stores the dirty state as a patch bundle with a manifest under
    ``.gate-quarantine/``, verifies the bundle on a temporary copy of HEAD,
    and only then returns the working tree to HEAD.  A stale
    ``.git/index.lock`` is removed only after verifying no git process is
    running.
    """
    bundle_dir = repo_root / ".gate-quarantine"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    # Handle stale index.lock (before any git index operations).
    index_lock = repo_root / ".git" / "index.lock"
    if index_lock.exists():
        if _git_process_running(repo_root):
            print(
                "quarantine: git process is running, cannot remove index.lock",
                file=sys.stderr,
            )
            return 1
        index_lock.unlink()

    # Create the bundle.
    create_bundle(repo_root, bundle_dir)

    # Verify the bundle.
    if not verify_bundle(repo_root, bundle_dir):
        print("quarantine: bundle verification failed", file=sys.stderr)
        return 1

    # Restore the working tree to HEAD.
    manifest_raw: object = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    untracked_raw: object = (
        manifest_raw.get("untracked_files", []) if isinstance(manifest_raw, dict) else []
    )

    # Restore tracked files to HEAD.
    _git_run(["checkout", "HEAD", "--", "."], repo_root)

    # Remove untracked files listed in the manifest.
    if isinstance(untracked_raw, list):
        for entry in untracked_raw:
            if isinstance(entry, dict):
                fpath = entry.get("path")
                if isinstance(fpath, str) and fpath:
                    full_path = repo_root / fpath
                    if full_path.exists():
                        full_path.unlink()

    # Create the interruption record.
    create_interruption_record(repo_root, phase_id, bundle_dir)

    return 0


# --------------------------------------------------------------------------- #
# CLI entry point
# --------------------------------------------------------------------------- #


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def main(args: list[str]) -> int:
    """CLI entry for ``gate phase quarantine-tree <NN>``."""
    if not args:
        print("usage: gate phase quarantine-tree <NN>", file=sys.stderr)
        return 2
    phase_id = args[0]
    return quarantine_tree(_repo_root(), phase_id)
