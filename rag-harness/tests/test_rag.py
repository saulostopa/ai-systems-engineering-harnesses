"""POC tests — pytest or plain asserts (`python tests/test_rag.py`).

Run with:  pytest tests/ -q   (or)   python tests/test_rag.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

# Tests never write to the real usage ledger unless a test enables it.
os.environ.setdefault("HARNESS_USAGE", "0")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rag_harness.chunker import Chunk, chunk_file
from rag_harness.embeddings import NGramEmbedder, OpenRouterEmbedder, cosine, embedder_id
from rag_harness.indexer import discover_files, index_dir, index_path_for, is_ignored, load_index, semantic_search
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


def _write(root: str, rel: str, text: str = "conteudo\n") -> None:
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _rel(root: str, files: list[str]) -> list[str]:
    return sorted(os.path.relpath(f, root).replace(os.sep, "/") for f in files)


def test_discover_respeita_gitignore_lockfiles_e_ragignore():
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["git", "init", "-q", tmp], check=True)
        _write(tmp, ".gitignore", "ios/\n")
        _write(tmp, ".ragignore", "# dump de dados\ndatabase/exercises.ts\n")
        _write(tmp, "src/App.tsx", "export const App = () => null\n")
        _write(tmp, "src/util.mjs")
        _write(tmp, "docs/guia.md")
        _write(tmp, "ios/Pods/Manifest.json")
        _write(tmp, "package-lock.json", "{}\n")
        _write(tmp, "database/exercises.ts")
        _write(tmp, ".github/workflows/ci.yml")
        assert _rel(tmp, discover_files(tmp)) == ["docs/guia.md", "src/App.tsx", "src/util.mjs"]


def test_discover_sem_git_aplica_lockfiles_e_ragignore():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, ".ragignore", "generated/\n*.min.js\n")
        _write(tmp, "app.ts")
        _write(tmp, "vendor.min.js")
        _write(tmp, "generated/schema.json")
        _write(tmp, "yarn.lock")
        _write(tmp, "pnpm-lock.yaml")
        _write(tmp, "node_modules/pkg/index.js")
        assert _rel(tmp, discover_files(tmp)) == ["app.ts"]


def test_is_ignored_padroes():
    assert is_ignored("database/exercises.ts", ["database/exercises.ts"])
    assert is_ignored("a/build/x.ts", ["build/"])
    assert not is_ignored("a/build.ts", ["build/"])
    assert is_ignored("src/x.min.js", ["*.min.js"])
    assert is_ignored("ios/Pods/a.json", ["/ios"])
    assert not is_ignored("src/ios/a.json", ["/ios"])


def test_perfis_docs_e_code_geram_indices_separados():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "README.md", "politica de deploy\n")
        _write(tmp, "src/login.ts", "export function login() { return true }\n")
        emb = NGramEmbedder()
        docs = index_dir(tmp, emb, profile="docs")
        code = index_dir(tmp, emb, profile="code")
        assert {os.path.basename(c.path) for c in docs.chunks} == {"README.md"}
        assert {os.path.basename(c.path) for c in code.chunks} == {"login.ts"}
        assert os.path.exists(os.path.join(index_path_for(tmp, "docs"), "chunks.json"))
        assert os.path.exists(os.path.join(index_path_for(tmp, "code"), "chunks.json"))
        assert load_index(index_path_for(tmp, "code")).embedder == "ngram:256"


def test_troca_de_embedder_reindexa_tudo_e_busca_falha_fechado():
    with tempfile.TemporaryDirectory() as tmp:
        _write(tmp, "a.py", FIXTURE)
        index_dir(tmp, NGramEmbedder(dim=256))
        index = index_dir(tmp, NGramEmbedder(dim=64))
        assert index.embedder == "ngram:64"
        assert all(len(v) == 64 for v in index.vectors.values())
        try:
            semantic_search(load_index(index_path_for(tmp)), NGramEmbedder(dim=256), "fipe")
        except ValueError as exc:
            assert "ngram:64" in str(exc)
        else:
            raise AssertionError("mismatched embedder must fail closed")


def test_openrouter_embedder_envia_em_lotes_e_respeita_index():
    calls = []

    def transport(payload):
        calls.append(payload)
        data = [{"index": i, "embedding": [float(len(text))]} for i, text in enumerate(payload["input"])]
        return {"data": list(reversed(data))}

    emb = OpenRouterEmbedder(model="openrouter/voyageai/voyage-code-4", api_key="test", batch_size=2, transport=transport)
    vectors = emb.embed_batch(["a", "bb", "ccc", "dddd", "eeeee"])
    assert vectors == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert [len(c["input"]) for c in calls] == [2, 2, 1]
    assert calls[0]["model"] == "voyageai/voyage-code-4"
    assert embedder_id(emb) == "openrouter:voyageai/voyage-code-4"



def test_openrouter_embedder_registra_custo_da_indexacao_no_ledger():
    from rag_harness import usage

    if usage._usage is None:
        return  # standalone copy without harness-usage: nothing to record
    with tempfile.TemporaryDirectory() as tmp:
        repo = os.path.join(tmp, "repo")
        os.makedirs(repo)
        with open(os.path.join(repo, "a.md"), "w") as fh:
            fh.write("# Deploy\npromote develop to main\n")

        def transport(payload):
            data = [{"index": i, "embedding": [1.0, 0.0]} for i, _ in enumerate(payload["input"])]
            return {"data": data, "model": "voyage-code-4", "usage": {"prompt_tokens": 7, "cost": 8.4e-07}}

        emb = OpenRouterEmbedder(api_key="test", transport=transport)
        old = {k: os.environ.get(k) for k in ("HARNESS_USAGE", "XDG_DATA_HOME")}
        os.environ.update({"HARNESS_USAGE": "1", "XDG_DATA_HOME": os.path.join(tmp, "data")})
        try:
            index_dir(repo, emb, os.path.join(repo, ".rag_index"), profile="docs")
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        ledger_dir = os.path.join(repo, ".harness", "usage")
        [name] = os.listdir(ledger_dir)
        with open(os.path.join(ledger_dir, name)) as fh:
            [line] = [json.loads(row) for row in fh]
        assert line["component"] == "embedding_index"
        assert line["operation"] == "index docs"
        assert line["harness"] == "rag-harness"
        assert line["project"] == "repo"
        assert (line["input_tokens"], line["cost_usd"], line["cost_source"]) == (7, 8.4e-07, "provider")

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