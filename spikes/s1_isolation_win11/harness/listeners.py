"""Live host listeners for Spike S1 Addendum Phase A0.
Spawns background Canary servers on Loopback, LAN, UDP, and HTTP Proxy.
"""
from __future__ import annotations

import http.server
import socket
import socketserver
import threading
import time


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class EchoTCPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data = self.request.recv(1024)
            if data:
                self.request.sendall(b"ECHO:" + data)
        except Exception:
            pass


class EchoUDPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data, sock = self.request
            sock.sendto(b"UDPECHO:" + data, self.client_address)
        except Exception:
            pass


class ProxyHTTPHandler(http.server.BaseHTTPRequestHandler):
    def do_CONNECT(self):
        self.send_response(200, "Connection Established")
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"PROXY_OK")

    def log_message(self, format, *args):
        pass  # Quiet


class CanaryListenerManager:
    def __init__(self, lan_ip: str, base_port: int = 18080):
        self.lan_ip = lan_ip
        self.loopback_port = base_port
        self.lan_port = base_port + 1
        self.udp_port = base_port + 2
        self.proxy_port = base_port + 3
        self.ipv6_port = base_port + 5

        self.servers = []
        self.threads = []

    def start(self):
        # 1. Loopback TCP Listener
        s_loopback = ThreadedTCPServer(("127.0.0.1", self.loopback_port), EchoTCPHandler)
        self.servers.append(s_loopback)

        # 2. LAN TCP Listener (Strictly bound to host LAN IP, NOT 0.0.0.0)
        s_lan = ThreadedTCPServer((self.lan_ip, self.lan_port), EchoTCPHandler)
        self.servers.append(s_lan)

        # 3. UDP Echo Listener
        s_udp = socketserver.UDPServer(("127.0.0.1", self.udp_port), EchoUDPHandler)
        self.servers.append(s_udp)

        # 4. HTTP Proxy Listener
        s_proxy = ThreadedTCPServer(("127.0.0.1", self.proxy_port), ProxyHTTPHandler)
        self.servers.append(s_proxy)

        # 5. IPv6 Loopback TCP Listener
        try:
            class IPv6Server(ThreadedTCPServer):
                address_family = socket.AF_INET6

            s_ipv6 = IPv6Server(("::1", self.ipv6_port), EchoTCPHandler)
            self.servers.append(s_ipv6)
        except Exception:
            pass

        for s in self.servers:
            t = threading.Thread(target=s.serve_forever, daemon=True)
            t.start()
            self.threads.append(t)

        time.sleep(0.2)  # Give servers time to bind

    def stop(self):
        for s in self.servers:
            try:
                s.shutdown()
                s.server_close()
            except Exception:
                pass
        self.servers.clear()
        self.threads.clear()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
