"""M4 Orphan Process Spawner Payload for Spike S1.
Spawns child processes that ignore parent exit to verify Job Object clean teardown.
"""
from __future__ import annotations

import subprocess
import sys
import time


def main():
    print("[Worker] Spawning stubborn child processes...")
    # Spawn 3 child processes running infinite sleep / ping loop
    children = []
    for i in range(3):
        p = subprocess.Popen(
            [sys.executable, "-c", "import time; [time.sleep(1) for _ in range(10)]"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        children.append(p)
        print(f"[Worker] Spawned child PID: {p.pid}")

    print("[Worker] Children running. Worker idling...")
    time.sleep(60)


if __name__ == "__main__":
    main()
