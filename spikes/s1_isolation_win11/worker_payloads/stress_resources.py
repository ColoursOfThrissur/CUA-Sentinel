"""M3 Resource Stress Payload for Spike S1.
Attempts to consume memory exponentially and peg CPU to verify Job Object caps.
"""
from __future__ import annotations

import sys
import time


def memory_bomb(limit_mb: int = 4096):
    chunks = []
    chunk_size = 50 * 1024 * 1024  # 50 MB
    print(f"[Worker] Starting memory allocation up to {limit_mb} MB...")
    try:
        for i in range(limit_mb // 50):
            chunks.append(bytearray(chunk_size))
            print(f"[Worker] Allocated {(i + 1) * 50} MB")
            time.sleep(0.05)
    except MemoryError:
        print("[Worker] Caught MemoryError inside process!")
    except Exception as e:
        print(f"[Worker] Caught exception: {e}")


def cpu_bomb(duration_sec: float = 5.0):
    print(f"[Worker] Starting CPU loop for {duration_sec}s...")
    start = time.time()
    while time.time() - start < duration_sec:
        _ = [x ** 2 for x in range(10000)]
    print("[Worker] Finished CPU loop.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "memory"
    if mode == "memory":
        memory_bomb()
    elif mode == "cpu":
        cpu_bomb()
    else:
        print(f"Unknown mode {mode}")
