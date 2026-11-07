"""M1 Network Probe Payload for Spike S1.
Attempts outbound network connections across multiple vectors and outputs JSON results.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request


def test_tcp_outbound(host: str = "1.1.1.1", port: int = 80, timeout: float = 1.0) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return {"status": "CONNECTED", "allowed": True}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": str(e)}


def test_udp_outbound(host: str = "8.8.8.8", port: int = 53, timeout: float = 1.0) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        query = b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x06google\x03com\x00\x00\x01\x00\x01"
        s.sendto(query, (host, port))
        data, addr = s.recvfrom(512)
        s.close()
        return {"status": "REPLIED", "allowed": True, "bytes": len(data)}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": str(e)}


def test_dns_resolution(host: str = "google.com") -> dict:
    try:
        res = socket.getaddrinfo(host, 80)
        return {"status": "RESOLVED", "allowed": True, "ips": [r[4][0] for r in res]}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": str(e)}


def test_doh(url: str = "https://1.1.1.1/dns-query?name=google.com&type=A", timeout: float = 1.5) -> dict:
    try:
        req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            return {"status": "CONNECTED", "allowed": True, "bytes": len(data)}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": str(e)}


def test_lan_outbound(host: str = "192.168.1.1", port: int = 80, timeout: float = 0.5) -> dict:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return {"status": "CONNECTED", "allowed": True}
    except Exception as e:
        return {"status": "BLOCKED", "allowed": False, "error": str(e)}


def test_local_host_ports(ports: list[int] = [11434, 8000, 5432, 6379, 8080], timeout: float = 0.3) -> dict:
    results = {}
    for port in ports:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            s.close()
            results[str(port)] = {"status": "REACHABLE", "allowed": True}
        except Exception as e:
            results[str(port)] = {"status": "UNREACHABLE", "allowed": False, "error": str(e)}
    return results


def test_proxy_env() -> dict:
    proxy_vars = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
    return {"proxy_env_present": bool(proxy_vars), "variables": list(proxy_vars.keys())}


def main():
    report = {
        "test": "M1_NETWORK_EGRESS",
        "tcp_public": test_tcp_outbound(),
        "udp_public": test_udp_outbound(),
        "dns_resolve": test_dns_resolution(),
        "doh_https": test_doh(),
        "lan_probe": test_lan_outbound(),
        "local_host_probe": test_local_host_ports(),
        "proxy_env": test_proxy_env(),
    }
    # Print formatted JSON to stdout for harness consumption
    print("PROBE_RESULT_START")
    print(json.dumps(report, indent=2))
    print("PROBE_RESULT_END")


if __name__ == "__main__":
    main()
