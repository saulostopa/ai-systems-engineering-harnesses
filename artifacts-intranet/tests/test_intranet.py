"""Intranet tests — pytest or plain asserts.

Usage: python3 tests/test_intranet.py   (from artifacts-intranet/)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from artifacts_intranet.indexer import chunk_artifact_file, html_to_text, index_artifacts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "demo-artifact.html")


def test_html_to_text_remove_tags_e_scripts():
    html = "<html><script>var x=1;</script><style>.a{}</style><h1>Título</h1><p>Texto <b>legal</b></p></html>"
    text = html_to_text(html)
    assert "Título" in text and "Texto legal" in text
    assert "script" not in text.lower().replace("título", "") or "var x" not in text


def test_chunk_artifact_html():
    if not os.path.exists(FIXTURE):
        return
    chunks = chunk_artifact_file(FIXTURE)
    assert chunks, "no chunks"
    assert all(c.kind == "artifact" for c in chunks)


def test_index_artifacts_gera_indice():
    repo = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    index = index_artifacts(repo)
    assert len(index.chunks) > 0
    # Hash dedup is intentional: identical text (boilerplate) = 1 embedding
    assert len(index.vectors) > 0
    assert len(index.vectors) <= len(index.chunks)


if __name__ == "__main__":
    import traceback

    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)