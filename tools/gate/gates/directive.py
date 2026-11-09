"""Directive gate (P00-T11).

Wraps the directive lint of Part 6 §6.15.  Invokable as
``python -m tools.gate.gates.directive``.

Exit codes: 0 clean, 1 violation, 2 misconfiguration.
"""

from __future__ import annotations

import sys

from tools.gate.phase.directive import main as directive_main


def main() -> int:
    return directive_main()


if __name__ == "__main__":
    sys.exit(main())
