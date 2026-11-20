"""Area Copilot tests — pytest or plain asserts.

Usage: python3 tests/test_area.py  (from area-copilot/)
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from area_harness.__main__ import answer_with_sources, index_area, load_area_index
from area_harness.business_chunker import chunk_business_dir

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "area_context")


def test_chunk_planilha_csv_carrega_fontes():
    chunks = chunk_business_dir(FIXTURE)
    csv_chunks = [c for c in chunks if c.path.endswith(".csv")]
    assert csv_chunks, "no spreadsheet chunks"
    first = csv_chunks[0]
    assert "meta_vendas" in first.text
    assert first.kind == "sheet"


def test_answer_cita_fonte_com_linha():
    with tempfile.TemporaryDirectory() as tmp:
        index_area(FIXTURE)
        # uses the real index (in FIXTURE/.area_index)
        answer = answer_with_sources(FIXTURE, "qual a meta de julho do sudeste")
        assert "FONTE:" in answer
        assert "metas_2026.csv" in answer


def test_fonte_existe_no_disco():
    index = load_area_index(FIXTURE)
    for c in index.chunks:
        base = c.path.split("#")[0]
        assert os.path.exists(base), f"source does not exist: {base}"


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