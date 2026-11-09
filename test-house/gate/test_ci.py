"""Tests for CI workflows (P00-T08).

Every test carries a header (id, title, purpose, level, requirement ids, input,
expected result, risk covered, owning capability) per Part 4 §4.5.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import cast

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# A 40-character lowercase hex commit hash (GitHub SHA-1).
_HASH_RE = re.compile(r"^[0-9a-f]{40}$")

# Shell operators that indicate inline shell logic (not a single command).
_SHELL_OPERATORS = re.compile(r"[|;&>]|`|\$\(")

# Allowed run-command prefixes (gate and build commands only).
_ALLOWED_RUN_PREFIXES = (
    "uv sync",
    "uv run",
    "uv python",
    "uv pip",
    "pip install",
    "python -m tools.gate",
    "gate ",
)


def _workflow_files() -> list[Path]:
    """Every .yml/.yaml file under .github/workflows/."""
    if not WORKFLOWS_DIR.is_dir():
        return []
    return sorted(p for p in WORKFLOWS_DIR.iterdir() if p.suffix in (".yml", ".yaml"))


def _load_yaml(path: Path) -> dict[object, object]:
    """Parse a YAML file into a dict, handling PyYAML's ``on`` -> ``True`` quirk."""
    with path.open(encoding="utf-8") as stream:
        raw: object = yaml.safe_load(stream)
    assert isinstance(raw, dict), f"{path} is not a YAML mapping"
    return cast(dict[object, object], raw)


# ---------------------------------------------------------------------------
# T-CI-0001 — CI workflow structure
# ---------------------------------------------------------------------------
# id: T-CI-0001
# title: CI workflows use only gate and build steps with actions pinned by hash
# purpose: Verify every workflow YAML uses only allowed step forms (gate and
#          build commands, no inline shell logic), pins every action by commit
#          hash, declares permissions, and pr.yml has a job named `phase`.
# level: fast
# requirement ids: P00-T08, Part 1 §4.9, Part 6 §6.13
# scenario ids: S-CI-WORKFLOWS
# input: every .github/workflows/*.yml file
# expected result: all assertions pass — actions pinned by 40-char hash,
#                  run steps are gate/build only, permissions declared,
#                  phase job in pr.yml, only nightly.yml is scheduled
# risk covered: a workflow uses an unpinned action or inline shell logic that
#               bypasses the gate contract
# owning capability: ci-workflows


@pytest.mark.fast
def test_ci_workflows_structure() -> None:
    """Every workflow YAML has the required structure."""
    files = _workflow_files()
    assert files, "no workflow files found in .github/workflows/"

    for path in files:
        data = _load_yaml(path)

        # --- permissions declared (top-level or per-job) ---
        top_permissions = data.get("permissions")
        jobs = data.get("jobs")
        assert isinstance(jobs, dict), f"{path.name}: no `jobs` mapping"
        for job_name, job_data in jobs.items():
            if not isinstance(job_data, dict):
                continue
            job_permissions = job_data.get("permissions", top_permissions)
            assert job_permissions is not None, (
                f"{path.name}: job {job_name!r} has no permissions declared"
            )

            # --- every step: actions pinned by hash, runs are gate/build only ---
            steps = job_data.get("steps", [])
            assert isinstance(steps, list), f"{path.name}: job {job_name!r} steps is not a list"
            for step in steps:
                if not isinstance(step, dict):
                    continue
                # uses: must be pinned by a 40-char commit hash
                uses = step.get("uses")
                if uses is not None:
                    assert isinstance(uses, str), f"{path.name}: step `uses` is not a string"
                    assert "@" in uses, f"{path.name}: action {uses!r} is not pinned with @"
                    ref = uses.rsplit("@", 1)[1].strip()
                    assert _HASH_RE.match(ref), (
                        f"{path.name}: action {uses!r} pinned by {ref!r} "
                        f"— not a 40-char commit hash"
                    )

                # run: must be an allowed command with no inline shell logic
                run = step.get("run")
                if run is not None:
                    assert isinstance(run, str), f"{path.name}: step `run` is not a string"
                    assert not _SHELL_OPERATORS.search(run), (
                        f"{path.name}: run step {run!r} contains shell operators "
                        f"(inline logic not allowed)"
                    )
                    stripped = run.strip()
                    assert any(stripped.startswith(prefix) for prefix in _ALLOWED_RUN_PREFIXES), (
                        f"{path.name}: run step {run!r} is not a gate or build command "
                        f"(allowed prefixes: {_ALLOWED_RUN_PREFIXES})"
                    )


@pytest.mark.fast
def test_pr_yml_has_phase_job() -> None:
    """pr.yml has a job named `phase` (the required check)."""
    pr_path = WORKFLOWS_DIR / "pr.yml"
    assert pr_path.is_file(), "pr.yml not found in .github/workflows/"
    data = _load_yaml(pr_path)
    jobs = data.get("jobs")
    assert isinstance(jobs, dict), "pr.yml has no `jobs` mapping"
    assert "phase" in jobs, "pr.yml has no job named `phase` (the required check)"


@pytest.mark.fast
def test_nightly_is_only_scheduled() -> None:
    """Only nightly.yml has a cron schedule trigger."""
    files = _workflow_files()
    for path in files:
        data = _load_yaml(path)
        # PyYAML parses bare `on:` as `True:` (YAML 1.1 boolean)
        on = data.get("on")
        if on is None:
            on = data.get(True)
        if isinstance(on, dict) and "schedule" in on:
            assert path.name == "nightly.yml", (
                f"{path.name}: schedule trigger found — only nightly.yml may be scheduled"
            )
