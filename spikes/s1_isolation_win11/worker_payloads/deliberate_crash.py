"""M5 Deliberate Crash Payload for Spike S1.
Triggers an immediate access violation / segfault via ctypes to test host harness survival.
"""
from __future__ import annotations

import ctypes
import sys


def main():
    print("[Worker] Triggering deliberate null pointer dereference...")
    sys.stdout.flush()
    # Dereference null pointer in C
    ctypes.string_at(0)


if __name__ == "__main__":
    main()
