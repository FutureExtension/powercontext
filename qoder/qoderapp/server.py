"""A small HTTP service for the research desk.

The service only uses the standard library, so the runbook does not need a
web framework.  The web interface is a static single page application that
the service serves from ``web/``.
"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from qoderapp.config import APP_DIR, Settings
from qoderapp.service import ResearchDesk

WEB_DIR = APP_DIR / "web"
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


class DeskHandler(BaseHTTPRequestHandler):
    """Handle the API calls and the static files."""

    desk: ResearchDesk

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        return

    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, name: str) -> None:
        path = (WEB_DIR / name).resolve()
        if not str(path).startswith(str(WEB_DIR.resolve())) or not path.is_file():
            self._send_json({"error": "not found"}, status=404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._send_file("index.html")
            return
        if parsed.path.startswith("/static/"):
            self._send_file(parsed.path[len("/static/") :])
            return
        if parsed.path == "/api/topics":
            self._send_json({"topics": self.desk.topics()})
            return
        if parsed.path == "/api/progress":
            self._send_json({"progress": asyncio.run(self.desk.progress())})
            return
        if parsed.path == "/api/ask":
            query = parse_qs(parsed.query)
            question = (query.get("q") or [""])[0]
            topic = (query.get("topic") or [""])[0]
            if not question.strip():
                self._send_json({"error": "q is required"}, status=400)
                return
            answer = asyncio.run(self.desk.ask(question, topic=topic))
            self._send_json(
                {
                    "question": answer.question,
                    "topic": answer.topic,
                    "hits": [
                        {
                            "note_id": hit.note_id,
                            "topic": hit.topic,
                            "title": hit.title,
                            "source_path": hit.source_path,
                            "score": hit.score,
                            "snippet": hit.snippet[:400],
                        }
                        for hit in answer.hits
                    ],
                    "open_notes": answer.open_notes,
                    "reviews": answer.reviews,
                    "statements": answer.statements,
                }
            )
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib signature
        parsed = urlparse(self.path)
        if parsed.path != "/api/mark":
            self._send_json({"error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except ValueError:
            self._send_json({"error": "invalid json"}, status=400)
            return
        topic = str(payload.get("topic") or "")
        note_id = str(payload.get("note_id") or "")
        if not topic or not note_id:
            self._send_json({"error": "topic and note_id are required"}, status=400)
            return
        state = asyncio.run(self.desk.mark(topic, note_id, bool(payload.get("mastered"))))
        self._send_json(
            {
                "topic": state.topic,
                "mastered": state.mastered,
                "open_notes": state.open_notes,
                "reviews": state.reviews,
            }
        )


def serve(settings: Settings) -> None:
    """Run the service until it is interrupted."""

    handler = type("BoundDeskHandler", (DeskHandler,), {"desk": ResearchDesk(settings)})
    server = ThreadingHTTPServer((settings.host, settings.port), handler)
    print(f"research desk on http://{settings.host}:{settings.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
