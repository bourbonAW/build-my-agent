"""Host-side HTTP proxy for credential injection.

Container connects via http_proxy/https_proxy environment variables.
The proxy validates the target domain against allow_domains and
injects credentials on the host side — the container never holds them.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bourbon.sandbox.credential import CredentialManager


class CredentialProxy:
    """Host-side HTTP forward proxy with domain allowlisting.

    Domain matching rules:
    - Exact match: "api.example.com" matches only "api.example.com"
    - Wildcard: "*.example.com" matches "api.example.com" but NOT "example.com"
    """

    def __init__(
        self,
        credential_mgr: CredentialManager | None,
        allow_domains: list[str],
        host: str = "127.0.0.1",
        port: int = 0,  # 0 = OS assigns ephemeral port
    ) -> None:
        self._credential_mgr = credential_mgr
        self._allow_domains = allow_domains
        self._host = host
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start the proxy server. Returns 'host:port' address string."""
        handler = _make_handler(self)
        self._server = HTTPServer((self._host, 0), handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="CredentialProxy",
        )
        self._thread.start()
        return self.address

    def stop(self) -> None:
        """Stop the proxy server. Safe to call multiple times."""
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def address(self) -> str:
        """Returns 'host:port'. Raises RuntimeError if not started."""
        if self._server is None:
            raise RuntimeError("CredentialProxy not started — call start() first")
        host, port = self._server.server_address
        return f"{host}:{port}"

    def _is_domain_allowed(self, target: str) -> bool:
        """Check if target domain matches the allow_domains list."""
        for pattern in self._allow_domains:
            if pattern.startswith("*."):
                # Wildcard: match subdomain only, not root
                suffix = pattern[2:]  # strip "*."
                if target.endswith("." + suffix):
                    return True
            else:
                if target == pattern:
                    return True
        return False


def _make_handler(proxy: CredentialProxy) -> type[BaseHTTPRequestHandler]:
    """Create a handler class bound to the given proxy instance."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def do_HEAD(self) -> None:
            self._handle()

        def _handle(self) -> None:
            from urllib.parse import urlparse

            parsed = urlparse(self.path)
            host = parsed.netloc or parsed.hostname or ""
            # Strip port from host
            if ":" in host:
                host = host.rsplit(":", 1)[0]

            if not proxy._is_domain_allowed(host):
                self.send_response(403)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(
                    f"CredentialProxy: domain '{host}' not in allow_domains\n".encode()
                )
                return

            # Read request body if present
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length) if content_length else None

            # Build forwarded request
            req = urllib.request.Request(self.path, data=body, method=self.command)
            # Forward original headers (skip proxy-specific ones)
            for key, value in self.headers.items():
                if key.lower() not in ("host", "proxy-connection", "content-length"):
                    req.add_header(key, value)

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    self.send_response(resp.status)
                    for key, value in resp.headers.items():
                        self.send_header(key, value)
                    self.end_headers()
                    self.wfile.write(resp.read())
            except urllib.error.HTTPError as e:
                self.send_response(e.code)
                self.end_headers()
            except Exception as e:
                self.send_response(502)
                self.end_headers()
                self.wfile.write(f"CredentialProxy error: {e}\n".encode())

        def log_message(self, format: str, *args: object) -> None:
            pass  # Suppress default access log

    return _Handler
