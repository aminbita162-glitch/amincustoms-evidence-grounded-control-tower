"""Self-review validation for the AminCustoms phase machinery (P00-T05).

Validates the phase self-review (Part 1 §9.3):
  - at most 10 findings in the main text
  - each finding has: id, category, evidence, impact, question
  - at most 40 words per finding
  - when more than 10 findings exist, the 10 most severe are in the main
    text and the rest go into an overflow file; the main text ends with a
    single ``OVERFLOW:`` line whose counts match the overflow file

Finding format (each finding is a ``### <id>`` block)::

    ### F001
    - category: CONTRADICTION
    - evidence: src/main.py:10-20
    - impact: The value is wrong.
    - question: Should we fix this?

Categories (in severity order): CONTRADICTION, GAP, RISK, AMBIGUITY, DEBT.
"""

from __future__ import annotations

import re

__all__ = [
    "CATEGORIES",
    "MAX_FINDINGS",
    "MAX_WORDS",
    "Finding",
    "OverflowInfo",
    "parse_findings",
    "parse_overflow_line",
    "finding_word_count",
    "validate_selfreview",
]

CATEGORIES: tuple[str, ...] = ("CONTRADICTION", "GAP", "RISK", "AMBIGUITY", "DEBT")
MAX_FINDINGS: int = 10
MAX_WORDS: int = 40

_OVERFLOW_RE = re.compile(
    r"OVERFLOW:\s+(\d+)\s+.*?"
    r"\(CONTRADICTION\s+(\d+),\s*GAP\s+(\d+),\s*RISK\s+(\d+),"
    r"\s*AMBIGUITY\s+(\d+),\s*DEBT\s+(\d+)\)"
)

_FINDING_HEADER_RE = re.compile(r"^#{1,4}\s+([A-Za-z0-9_-]+)\s*$")
_FIELD_RE = re.compile(r"^-\s*([A-Za-z_]+)\s*:\s*(.*)$")


class Finding:
    """A single self-review finding."""

    __slots__ = ("id", "category", "evidence", "impact", "question")

    def __init__(
        self,
        finding_id: str,
        category: str,
        evidence: str,
        impact: str,
        question: str,
    ) -> None:
        self.id = finding_id
        self.category = category
        self.evidence = evidence
        self.impact = impact
        self.question = question

    @property
    def word_count(self) -> int:
        """Total words across evidence, impact and question."""
        return finding_word_count(self)

    def __repr__(self) -> str:
        return f"Finding(id={self.id!r}, category={self.category!r})"


class OverflowInfo:
    """Parsed OVERFLOW line."""

    __slots__ = ("total", "counts")

    def __init__(self, total: int, counts: dict[str, int]) -> None:
        self.total = total
        self.counts = counts


def parse_overflow_line(text: str) -> OverflowInfo | None:
    """Parse an ``OVERFLOW:`` line from *text*; return ``None`` if absent."""
    for line in text.splitlines():
        match = _OVERFLOW_RE.search(line)
        if match:
            total = int(match.group(1))
            counts = {
                "CONTRADICTION": int(match.group(2)),
                "GAP": int(match.group(3)),
                "RISK": int(match.group(4)),
                "AMBIGUITY": int(match.group(5)),
                "DEBT": int(match.group(6)),
            }
            return OverflowInfo(total=total, counts=counts)
    return None


def parse_findings(text: str) -> list[Finding]:
    """Parse ``### <id>`` finding blocks from *text*."""
    findings: list[Finding] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        header_match = _FINDING_HEADER_RE.match(line)
        if header_match:
            finding_id = header_match.group(1)
            fields: dict[str, str] = {}
            i += 1
            while i < len(lines):
                field_line = lines[i].strip()
                if not field_line:
                    i += 1
                    continue
                if _FINDING_HEADER_RE.match(field_line):
                    break
                if field_line.startswith("OVERFLOW:"):
                    break
                field_match = _FIELD_RE.match(field_line)
                if field_match:
                    fields[field_match.group(1).lower()] = field_match.group(2).strip()
                i += 1
            findings.append(
                Finding(
                    finding_id=finding_id,
                    category=fields.get("category", ""),
                    evidence=fields.get("evidence", ""),
                    impact=fields.get("impact", ""),
                    question=fields.get("question", ""),
                )
            )
        else:
            i += 1
    return findings


def finding_word_count(finding: Finding) -> int:
    """Count total words in a finding (evidence + impact + question)."""
    text = " ".join([finding.evidence, finding.impact, finding.question])
    return len(text.split())


def validate_selfreview(
    text: str,
    overflow_content: str | None = None,
) -> list[str]:
    """Validate the self-review text.

    Returns a list of error messages (empty = valid):
      - more than 10 findings without an OVERFLOW line
      - OVERFLOW line counts don't match the overflow file
      - overflow file exists but no OVERFLOW line
      - a finding missing one of the five required parts
      - a finding exceeding 40 words
    """
    errors: list[str] = []
    findings = parse_findings(text)
    overflow_info = parse_overflow_line(text)

    # Check finding count and overflow rules.
    overflow_findings: list[Finding] = []
    if overflow_content is not None:
        overflow_findings = parse_findings(overflow_content)

    if len(findings) > MAX_FINDINGS:
        if overflow_info is None:
            errors.append(
                f"self-review has {len(findings)} findings (max {MAX_FINDINGS}) "
                f"but no OVERFLOW line"
            )
        elif overflow_content is None:
            errors.append("OVERFLOW line present but overflow file content not provided")

    if overflow_content is not None and overflow_info is None:
        errors.append("overflow file exists but no OVERFLOW line in the self-review text")

    if overflow_info is not None and overflow_content is not None:
        # Verify total matches the number of findings in the overflow file.
        if overflow_info.total != len(overflow_findings):
            errors.append(
                f"OVERFLOW total {overflow_info.total} != "
                f"overflow file has {len(overflow_findings)} findings"
            )
        # Verify category counts match.
        actual_counts: dict[str, int] = dict.fromkeys(CATEGORIES, 0)
        for f in overflow_findings:
            if f.category in actual_counts:
                actual_counts[f.category] += 1
        for cat in CATEGORIES:
            if overflow_info.counts.get(cat, 0) != actual_counts[cat]:
                errors.append(
                    f"OVERFLOW {cat} count {overflow_info.counts.get(cat, 0)} != "
                    f"overflow file has {actual_counts[cat]}"
                )

    # Check each finding has all five parts and is within the word limit.
    for f in findings:
        missing_parts: list[str] = []
        if not f.id:
            missing_parts.append("id")
        if not f.category:
            missing_parts.append("category")
        if not f.evidence:
            missing_parts.append("evidence")
        if not f.impact:
            missing_parts.append("impact")
        if not f.question:
            missing_parts.append("question")
        if missing_parts:
            errors.append(f"finding {f.id!r} missing parts: {', '.join(missing_parts)}")
        if f.category and f.category not in CATEGORIES:
            errors.append(
                f"finding {f.id!r} has invalid category {f.category!r} "
                f"(must be one of {', '.join(CATEGORIES)})"
            )
        wc = f.word_count
        if wc > MAX_WORDS:
            errors.append(f"finding {f.id!r} has {wc} words (max {MAX_WORDS})")

    # Also validate overflow findings for word count.
    for f in overflow_findings:
        wc = f.word_count
        if wc > MAX_WORDS:
            errors.append(f"overflow finding {f.id!r} has {wc} words (max {MAX_WORDS})")

    return errors
