"""Intranet server — stdlib http.server.

Routes:
    GET /            → UI (index.html, system theme)
    GET /search?q=…  → JSON: hybrid RAG results with cited sources
    GET /static/…    → assets (system.css)
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag_harness.agentic import AgentController
from rag_harness.embeddings import make_embedder

from .indexer import load_artifact_index

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
PKG_DIR = os.path.dirname(__file__)


class Handler(BaseHTTPRequestHandler):
    index = None
    embedder = None
    controller = None

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            with open(os.path.join(PKG_DIR, "..", "index.html"), "rb") as fh:
                return self._send(200, fh.read(), "text/html; charset=utf-8")
        if parsed.path == "/static/system.css":
            css = os.path.join(REPO_ROOT, "skills-artifacts", "assets", "system.css")
            if os.path.exists(css):
                with open(css, "rb") as fh:
                    return self._send(200, fh.read(), "text/css; charset=utf-8")
            return self._send(404, b"css not found", "text/plain")
        if parsed.path == "/search":
            qs = urllib.parse.parse_qs(parsed.query)
            q = qs.get("q", [""])[0].strip()
            k = int(qs.get("k", ["6"])[0])
            if not q:
                return self._send(200, json.dumps({"query": "", "results": []}).encode(), "application/json")
            results = self.controller.retrieve(q, REPO_ROOT) if self.controller else []
            payload = {
                "query": q,
                "tools": list(getattr(self.controller, "used_tools", [])),
                "results": [
                    {
                        "path": c.path,
                        "kind": c.kind,
                        "name": c.name,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "preview": c.text[:280],
                    }
                    for c in results[:k]
                ],
            }
            return self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        self._send(404, b"not found", "text/plain")

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if os.environ.get("INTRANET_QUIET") != "1":
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser(prog="artifacts_intranet")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--reindex", action="store_true", help="reindex before serving")
    args = ap.parse_args()

    Handler.embedder = make_embedder()
    idx_dir = os.path.join(PKG_DIR, ".intranet_index")
    if args.reindex or not os.path.exists(idx_dir):
        from .indexer import index_artifacts

        index_artifacts(REPO_ROOT, Handler.embedder, verbose=True)
    Handler.index = load_artifact_index(REPO_ROOT)
    Handler.controller = AgentController(Handler.index, Handler.embedder)

    print(f"embedder: {type(Handler.embedder).__name__}")
    print(f"index: {len(Handler.index.chunks)} chunks")
    print(f"intranet: http://localhost:{args.port}")
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
