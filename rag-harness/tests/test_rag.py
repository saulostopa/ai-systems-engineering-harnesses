"""POC tests — pytest or plain asserts (`python tests/test_rag.py`).

Run with:  pytest tests/ -q   (or)   python tests/test_rag.py
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag_harness.chunker import Chunk, chunk_file
from rag_harness.embeddings import NGramEmbedder, cosine
from rag_harness.indexer import index_dir
from rag_harness.retrieval import hybrid_search, lexical_search, rrf_merge

FIXTURE = """\
def calcular_fipe(preco: float, ano: int) -> float:
    \"\"\"Depreciação anual aproximada da tabela FIPE.\"\"\"
    taxa = 0.03 if ano >= 2018 else 0.05
    return preco * (1 - taxa)

class Veiculo:
    def __init__(self, marca: str, modelo: str):
        self.marca = marca
        self.modelo = modelo

def gerar_relatorio_financeiro(planilha: str) -> str:
    \"\"\"Gera o relatório de receita a partir da planilha.\"\"\"
    return f"receita de {planilha} consolidada"
"""


def test_chunk_python_extrai_funcoes_e_classes():
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(FIXTURE)
        path = fh.name
    chunks = chunk_file(path)
    os.unlink(path)
    kinds = {(c.kind, c.name) for c in chunks}
    assert ("function", "calcular_fipe") in kinds
    assert ("class", "Veiculo") in kinds
    assert ("function", "gerar_relatorio_financeiro") in kinds
    # No chunk cut in the middle of a function
    for c in chunks:
        if c.kind == "function":
            assert c.text.strip().startswith("def")


def test_ngram_embedder_deterministico_e_normalizado():
    emb = NGramEmbedder()
    v1 = emb.embed("calcular fipe preco")
    v2 = emb.embed("calcular fipe preco")
    assert v1 == v2
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6
    v3 = emb.embed("relatorio financeiro planilha")
    assert cosine(v1, v3) < cosine(v1, v1)


def test_rrf_merges_rankings():
    x = Chunk("f.py", "function", "x", "texto a", 1, 1)
    y = Chunk("f.py", "function", "y", "texto b", 1, 1)
    # y rank 1+2 => 1/61 + 1/62; x rank 2+1 => 1/62 + 1/61 (theoretical tie)
    # to break the tie, use different rankings: y first in both lists
    a = [(y, 9.0), (x, 1.0)]
    b = [(y, 8.0), (x, 2.0)]
    merged = rrf_merge(a, b, top_k=2)
    assert merged[0][0].name == "y"


def test_indexacao_e_recuperacao_hibrida():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "veiculo.py"), "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)
        emb = NGramEmbedder()
        index = index_dir(tmp, emb)
        assert len(index.chunks) >= 4
        top = hybrid_search(index, emb, "como calcular a fipe", top_k=2)
        assert top, "no hybrid results"
        assert "calcular_fipe" in top[0][0].text or "fipe" in top[0][0].text.lower()


def test_cache_reindexacao_reaproveita_vetores():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "a.py"), "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)
        emb = NGramEmbedder()
        index_dir(tmp, emb)
        index2 = index_dir(tmp, emb)
        assert len(index2.chunks) == len(index_dir(tmp, emb).chunks)


def test_lexical_normaliza_acentos_e_splits_camelcase():
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "log-event.sh"), "w", encoding="utf-8") as fh:
            fh.write("registra fricção do harness\nativa core.hooksPath\n")
        with open(os.path.join(tmp, "README.md"), "w", encoding="utf-8") as fh:
            fh.write("relatório genérico sem os termos exatos\n")
        emb = NGramEmbedder()
        index = index_dir(tmp, emb)
        top = lexical_search(index, "como registrar friccao e o hookspath", top_k=1)
        assert top and "log-event" in top[0][0].path, f"expected log-event.sh, got {top[:1]}"


def test_lexical_boost_por_nome_de_arquivo():
    with tempfile.TemporaryDirectory() as tmp:
        # Realistic fixture: the install.sh content does NOT repeat the rare
        # term "instalador" — only the file name carries that identification.
        with open(os.path.join(tmp, "install.sh"), "w", encoding="utf-8") as fh:
            fh.write("Instalando harness básico em: ativa core.hooksPath\n")
        with open(os.path.join(tmp, "AGENTS.md"), "w", encoding="utf-8") as fh:
            fh.write("roteador do projeto: leia antes de qualquer trabalho\n")
        emb = NGramEmbedder()
        index = index_dir(tmp, emb)
        top = lexical_search(index, "instalador que ativa hooksPath", top_k=1)
        assert top and "install.sh" in top[0][0].path, f"expected install.sh, got {top[:1]}"


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