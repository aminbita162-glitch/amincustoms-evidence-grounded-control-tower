"""Tests for the gitleaks installer used in CI (T-GATE-0046 to T-GATE-0048)."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest

from tools.gate.install_gitleaks import extract_binary, verify


def _archive(member_name: str, payload: bytes) -> bytes:
    """A gzip tar archive in memory holding one regular file."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# T-GATE-0046 - digest check
# ---------------------------------------------------------------------------
# id: T-GATE-0046
# title: the installer accepts only data with the pinned SHA-256
# purpose: Verify that verify() is True for the matching digest and False for any other.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-GITLEAKS-DIGEST
# input: the bytes abc with their real digest and with an all-zero digest
# expected result: True for the real digest, False for the zero digest
# risk covered: a tampered archive is installed as the secrets scanner
# owning capability: gate-secrets


@pytest.mark.fast
def test_verify_digest() -> None:
    """Only the matching digest is accepted."""
    data = b"abc"
    assert verify(data, hashlib.sha256(data).hexdigest())
    assert not verify(data, "0" * 64)


# ---------------------------------------------------------------------------
# T-GATE-0047 - extraction
# ---------------------------------------------------------------------------
# id: T-GATE-0047
# title: the installer writes the gitleaks member as an executable file
# purpose: Verify that extract_binary() writes the member bytes and sets the execute bits.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-GITLEAKS-EXTRACT
# input: an in-memory archive with a member named gitleaks
# expected result: the target file holds the member bytes and is executable
# risk covered: the secrets gate finds a binary that cannot run
# owning capability: gate-secrets


@pytest.mark.fast
def test_extract_binary(tmp_path: Path) -> None:
    """The member is written to the target and made executable."""
    target = tmp_path / "ci" / "gitleaks"
    extract_binary(_archive("gitleaks", b"binary"), target)
    assert target.read_bytes() == b"binary"
    assert target.stat().st_mode & 0o111


# ---------------------------------------------------------------------------
# T-GATE-0048 - missing member
# ---------------------------------------------------------------------------
# id: T-GATE-0048
# title: the installer fails when the archive has no gitleaks member
# purpose: Verify that extract_binary() raises KeyError and writes nothing.
# level: fast
# requirement ids: Part 4 section 4.12
# scenario ids: S-GATE-GITLEAKS-MISSING
# input: an in-memory archive whose only member is named other
# expected result: KeyError is raised and no target file exists
# risk covered: a wrong archive layout is installed silently
# owning capability: gate-secrets


@pytest.mark.fast
def test_extract_binary_missing_member(tmp_path: Path) -> None:
    """An archive without the gitleaks member raises KeyError."""
    target = tmp_path / "ci" / "gitleaks"
    with pytest.raises(KeyError):
        extract_binary(_archive("other", b"x"), target)
    assert not target.exists()
