"""Chain gate (P00-T12).

Wraps the build chain of Part 6 §6.17.  Invokable as
``python -m tools.gate.gates.chain``.

Exit codes: 0 verified, 1 violation, 2 misconfiguration.
"""

from __future__ import annotations

import sys

from tools.gate.phase.chain import main as chain_main


def main() -> int:
    return chain_main()


if __name__ == "__main__":
    sys.exit(main())
