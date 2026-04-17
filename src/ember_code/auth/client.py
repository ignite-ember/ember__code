"""CLI authentication — browser-based login with local callback.

Flow:
1. Start a local HTTP server on a random port
2. Open browser to portal login with callback URL
3. User authenticates in the portal
4. Portal redirects to localhost callback with token
5. Local server receives token, returns it to caller
"""

import asyncio
import logging
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.ignite-ember.sh"
DEFAULT_PORTAL_URL = "https://ignite-ember.sh"
_TIMEOUT = 15.0


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the token from the callback redirect."""

    token: str | None = None

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        token = params.get("token", [None])[0]

        if token:
            _CallbackHandler.token = token
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:system-ui;text-align:center;padding:60px'>"
                b"<h2>&#10004; Logged in to Ember Code</h2>"
                b"<p>You can close this tab and return to the terminal.</p>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>Missing token</h2></body></html>")

    def log_message(self, *args):
        pass  # silence HTTP logs


def get_login_url(port: int, portal_url: str = DEFAULT_PORTAL_URL) -> str:
    """Return the portal CLI auth URL that redirects the token back to localhost."""
    return f"{portal_url.rstrip('/')}/cli-auth?port={port}"


def start_callback_server() -> tuple[HTTPServer, str]:
    """Start a local HTTP server for receiving the auth callback.

    Returns (server, callback_url).
    The caller is responsible for running the server and closing it.
    """
    port = _find_free_port()
    callback_url = f"http://localhost:{port}/callback"

    _CallbackHandler.token = None
    server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.timeout = 1.0

    def _serve():
        while _CallbackHandler.token is None:
            try:
                server.handle_request()
            except (ValueError, OSError):
                break  # server closed

    thread = Thread(target=_serve, daemon=True)
    thread.start()

    return server, callback_url


async def wait_for_token(server: HTTPServer, timeout: float = 300.0) -> str:
    """Wait for the callback handler to receive a token.

    Raises TimeoutError if no callback within timeout.
    """
    elapsed = 0.0
    while _CallbackHandler.token is None and elapsed < timeout:
        await asyncio.sleep(0.5)
        elapsed += 0.5

    server.server_close()

    if _CallbackHandler.token is None:
        raise TimeoutError("Login timed out — no callback received")

    return _CallbackHandler.token


async def wait_for_callback(timeout: float = 300.0) -> tuple[str, str]:
    """Start a local HTTP server and wait for the portal to redirect with a token.

    Returns (token, callback_url).
    Raises TimeoutError if no callback within timeout.
    """
    server, callback_url = start_callback_server()
    token = await wait_for_token(server, timeout)
    return token, callback_url


async def validate_token(token: str, api_url: str = DEFAULT_API_URL) -> dict | None:
    """Validate a CLI token by calling the server.

    Returns user info dict on success, None on failure.
    """
    import httpx

    url = f"{api_url.rstrip('/')}/v1/portal/me"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        logger.debug("Token validation failed: %s", e)
    return None
