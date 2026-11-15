"""HTTP layer: serve the static page and a small JSON API using only the standard library.

Routes
  GET  /             -> web/index.html
  GET  /app.js       -> web/app.js
  GET  /styles.css   -> web/styles.css
  GET  /api/catalog  -> users, price lists, policy values (no costs)
  POST /api/replay   -> {"viewer": "<user id>", "steps": [...]} replayed on a fresh desk;
                        422 + "clarify" when a step needs the person to answer a question
"""

import json
import os
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from quote_sim.access import PermissionDenied

from server.scenario import ClarificationNeeded, StepFormatError, load_fake_data, replay
from server.serialize import catalog_json, replay_json

WEB_DIRECTORY = Path(__file__).resolve().parents[1] / "web"
MAX_REQUEST_BYTES = 64 * 1024
REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_PORT = 8000

# A fixed whitelist instead of mapping URL paths onto the disk, so "/../secret" cannot escape.
STATIC_FILES = MappingProxyType(
    {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    }
)
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


class BadRequest(ValueError):
    """The request itself is malformed; answered with HTTP 400 and a short reason."""


class QuoteSimHandler(BaseHTTPRequestHandler):
    """Every request is independent: nothing is stored between requests."""

    server_version = "quote-sim"

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in STATIC_FILES:
            file_name, content_type = STATIC_FILES[path]
            self._send(200, (WEB_DIRECTORY / file_name).read_bytes(), content_type)
        elif path == "/api/catalog":
            self._send_json(200, catalog_json(load_fake_data()))
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/replay":
            self._send_json(404, {"error": "not found"})
            return
        try:
            body = self._read_json_body()
            if not isinstance(body, dict):
                raise BadRequest("request body must be a JSON object")
            data = load_fake_data()
            viewer_id = body.get("viewer")
            if not isinstance(viewer_id, str):
                raise BadRequest("viewer must be a user id")
            try:
                viewer = data.users.get(viewer_id)
            except PermissionDenied as error:
                raise BadRequest(str(error)) from error
            result = replay(body.get("steps"), data)
            payload = replay_json(result, viewer)
        except (BadRequest, StepFormatError) as error:
            self._send_json(400, {"error": str(error)})
            return
        except ClarificationNeeded as question:
            # 422: the request was well-formed, but a person must answer before it can run.
            self._send_json(
                422,
                {
                    "error": str(question),
                    "clarify": {"step": question.step_index, "options": question.options()},
                },
            )
            return
        except TimeoutError:
            self._send_json(408, {"error": "request timed out"})
            return
        self._send_json(200, payload)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep test output quiet; a deployment platform still sees the process's stderr on errors.
        if os.environ.get("QUOTE_SIM_ACCESS_LOG") == "1":
            super().log_message(format, *args)

    def _read_json_body(self) -> object:
        content_type = self.headers.get("Content-Type", "").split(";", maxsplit=1)[0]
        if content_type.strip().lower() != "application/json":
            raise BadRequest("Content-Type must be application/json")
        length_text = self.headers.get("Content-Length", "")
        if not length_text.isascii() or not length_text.isdecimal():
            raise BadRequest("Content-Length is required")
        length = int(length_text)
        if length > MAX_REQUEST_BYTES:
            raise BadRequest("request is too large")
        self.connection.settimeout(REQUEST_TIMEOUT_SECONDS)
        raw = self.rfile.read(length)
        try:
            # parse_float=Decimal means no binary float is ever created from request data.
            return json.loads(
                raw.decode("utf-8"),
                parse_float=Decimal,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise BadRequest("request body is not valid JSON") from error

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.end_headers()
        self.wfile.write(body)


def _reject_constant(name: str) -> object:
    raise ValueError(f"{name} is not allowed")


def main() -> None:
    try:
        port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    except ValueError as error:
        raise SystemExit("PORT must be a valid TCP port number") from error
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be between 1 and 65535")

    server = ThreadingHTTPServer(("0.0.0.0", port), QuoteSimHandler)
    print(f"quote-sim listening on http://localhost:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping quote-sim.")
    finally:
        server.server_close()
