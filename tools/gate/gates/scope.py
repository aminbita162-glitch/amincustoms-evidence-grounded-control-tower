"""Scope gate (P00-T11).

Wraps the scope check of Part 6 §6.14.  Invokable as
``python -m tools.gate.gates.scope``.

Exit codes: 0 in-scope, 1 out-of-scope, 2 misconfiguration.
"""

from __future__ import annotations

import sys

from tools.gate.phase.scope import main as scope_main


def main() -> int:
    return scope_main()


if __name__ == "__main__":
    sys.exit(main())
