"""Repaired Probe Suite for Spike S1 Addendum Phase A0.
Tests all network vectors against live Canary listeners and filesystem vectors against live Canary files.
Outputs structured JSON surrounded by PROBE_RESULT_START / PROBE_RESULT_END.
"""
from __future__ import annotations

import faulthandler
import json
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path


def test_tcp_canary(host: str, port: int, timeout: float = 1.0) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(b"PING")
        reply = s.recv(1024)
        s.close()
        return {
            "status": "ALLOWED",
            "allowed": True,
            "bytes_received": len(reply),
            "verified_echo": reply == b"ECHO:PING",
            "error": None,
        }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "bytes_received": 0,
            "verified_echo": False,
            "error": f"{type(e).__name__}: {e}",
        }


def test_udp_canary(host: str, port: int, timeout: float = 1.0) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(b"PING", (host, port))
        reply, addr = s.recvfrom(1024)
        s.close()
        return {
            "status": "ALLOWED",
            "allowed": True,
            "bytes_received": len(reply),
            "verified_echo": reply == b"UDPECHO:PING",
            "error": None,
        }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "bytes_received": 0,
            "verified_echo": False,
            "error": f"{type(e).__name__}: {e}",
        }


def test_ipv6_canary(host: str = "::1", port: int = 18085, timeout: float = 1.0) -> dict:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(b"PING")
        reply = s.recv(1024)
        s.close()
        return {
            "status": "ALLOWED",
            "allowed": True,
            "bytes_received": len(reply),
            "verified_echo": reply == b"ECHO:PING",
            "error": None,
        }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "bytes_received": 0,
            "verified_echo": False,
            "error": f"{type(e).__name__}: {e}",
        }


def test_proxy_canary(proxy_url: str, target_url: str = "http://google.com/test", timeout: float = 1.5) -> dict:
    try:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(proxy_handler)
        req = urllib.request.Request(target_url)
        with opener.open(req, timeout=timeout) as resp:
            data = resp.read()
            return {
                "status": "ALLOWED",
                "allowed": True,
                "status_code": resp.status,
                "verified_proxy": data == b"PROXY_OK",
                "error": None,
            }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "status_code": 0,
            "verified_proxy": False,
            "error": f"{type(e).__name__}: {e}",
        }


def test_dns_resolution(host: str = "google.com") -> dict:
    try:
        res = socket.getaddrinfo(host, 80)
        return {
            "status": "ALLOWED",
            "allowed": True,
            "ips": [r[4][0] for r in res],
            "error": None,
        }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "ips": [],
            "error": f"{type(e).__name__}: {e}",
        }


def test_doh_query(ca_file: str | None = None, timeout: float = 2.0) -> dict:
    try:
        import ssl
        ctx = ssl.create_default_context(cafile=ca_file) if ca_file and os.path.exists(ca_file) else None
        req = urllib.request.Request(
            "https://1.1.1.1/dns-query?name=google.com&type=A",
            headers={"accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            data = resp.read()
            return {
                "status": "ALLOWED",
                "allowed": True,
                "bytes_read": len(data),
                "error": None,
            }
    except Exception as e:
        return {
            "status": "BLOCKED",
            "allowed": False,
            "bytes_read": 0,
            "error": f"{type(e).__name__}: {e}",
        }


def try_read_file(path: Path) -> dict:
    try:
        if not path.exists():
            return {"status": "BLOCKED", "allowed": False, "exists": False, "error": "FileNotFound"}
        data = path.read_text(encoding="utf-8")
        return {"status": "ALLOWED", "allowed": True, "exists": True, "content": data[:32], "error": None}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "exists": True, "content": None, "error": f"{type(e).__name__}: {e}"}


def try_write_file(path: Path, content: str = "malicious_write") -> dict:
    try:
        path.write_text(content, encoding="utf-8")
        return {"status": "ALLOWED", "allowed": True, "error": None}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": f"{type(e).__name__}: {e}"}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    # Crash mode
    if mode == "crash":
        faulthandler._sigsegv()
        return

    # Child spawner mode
    if mode == "spawn_children":
        import subprocess
        children = []
        for i in range(3):
            p = subprocess.Popen(
                [sys.executable, "-c", "import time; [time.sleep(1) for _ in range(300)]"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            children.append({"pid": p.pid, "create_time": time.time()})

        # Save manifest
        Path("children_manifest.json").write_text(json.dumps(children), encoding="utf-8")
        print("CHILDREN_SPAWNED")
        sys.stdout.flush()
        time.sleep(300)
        return

    # Parse args for paths & endpoints
    # Usage: probe_suite_a0.py all <lan_ip> <canary_dir> <workspace_dir> <ca_file>
    lan_ip = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    canary_dir = Path(sys.argv[3]).resolve() if len(sys.argv) > 3 else Path("canary").resolve()
    ws_dir = Path(sys.argv[4]).resolve() if len(sys.argv) > 4 else Path(".").resolve()
    ca_file = sys.argv[5] if len(sys.argv) > 5 else None

    user_profile = Path(os.environ.get("USERPROFILE", "C:\\Users\\Default"))
    canary_secret = canary_dir / "secret_canary.txt"
    canary_core_db = canary_dir / "core.db"

    report = {
        "network": {
            "tcp_loopback": test_tcp_canary("127.0.0.1", 18080),
            "tcp_lan": test_tcp_canary(lan_ip, 18081),
            "udp_canary": test_udp_canary("127.0.0.1", 18082),
            "http_proxy": test_proxy_canary("http://127.0.0.1:18083"),
            "ipv6_loopback": test_ipv6_canary("::1", 18085),
            "dns_public": test_dns_resolution("google.com"),
            "doh_https": test_doh_query(ca_file),
        },
        "filesystem": {
            "workspace_rw": {
                "write": try_write_file(ws_dir / "ws_test.txt", "VALID_WORKSPACE_DATA"),
                "read": try_read_file(ws_dir / "ws_test.txt"),
            },
            "canary_direct_read": try_read_file(canary_secret),
            "canary_traversal_read": try_read_file(ws_dir / ".." / ".." / "canary" / "secret_canary.txt"),
            "canary_junction_read": try_read_file(ws_dir / "junction_canary" / "secret_canary.txt"),
            "canary_symlink_read": {
                "status": "NOT_TESTABLE",
                "allowed": False,
                "reason": "SeCreateSymbolicLinkPrivilege required (WinError 1314)",
            },
            "at_c_11_core_db_read": try_read_file(canary_core_db),
            "at_c_11_core_db_write": try_write_file(canary_core_db),
            "user_profile_ntuser_read": try_read_file(user_profile / "NTUSER.DAT"),
        },
    }

    print("PROBE_RESULT_START")
    print(json.dumps(report, indent=2))
    print("PROBE_RESULT_END")


if __name__ == "__main__":
    main()
