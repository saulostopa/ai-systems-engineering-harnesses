"""Sync and search against a real PostgreSQL; skipped when the container is down."""

from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adk_rag_postgres_harness.embeddings import EMBED_DIM
from adk_rag_postgres_harness.ingest import sync
from adk_rag_postgres_harness.retrieval import find_symbol, search_code, where_used
from adk_rag_postgres_harness.store import PostgresStore, database_url
from rag_harness.embeddings import NGramEmbedder

try:
    import psycopg
except ImportError:
    psycopg = None


class CountingEmbedder(NGramEmbedder):
    def __init__(self, model_id: str = "test:a") -> None:
        super().__init__(dim=EMBED_DIM)
        self.model_id = model_id
        self.texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return super().embed(text)


def _database_available() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(database_url(), connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@unittest.skipUnless(_database_available(), "PostgreSQL is not running: docker compose up -d postgres")
class SyncTests(unittest.TestCase):
    def setUp(self):
        self.database = f"harness_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database}"')
        parts = urlsplit(database_url())
        self.store = PostgresStore(urlunsplit(parts._replace(path=f"/{self.database}")))
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "shop"
        self.repo.mkdir()
        self._write("src/login.ts", "export function handleLogin(user) {\n  return checkPassword(user);\n}\n")
        self._write("src/cart.ts", "export function addToCart(item) {\n  return cart.push(item);\n}\n")
        self._write("docs/guide.md", "# Guide\n\nHow the checkout flow works.\n")
        self.embedder = CountingEmbedder()

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{self.database}" WITH (FORCE)')

    def _write(self, relative: str, content: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _sync(self, embedder=None):
        return sync(str(self.repo), embedder=embedder or self.embedder, store=self.store)

    def _search(self, query: str, **kwargs):
        return search_code(query, "shop", embedder=self.embedder, store=self.store, **kwargs)

    def test_migrate_twice_is_safe(self):
        self.store.migrate()
        self.store.migrate()

    def test_second_sync_embeds_nothing(self):
        first = self._sync()
        self.assertEqual((first.files, first.changed, first.removed, first.embedded), (3, 3, 0, 3))
        second = self._sync()
        self.assertEqual((second.files, second.changed, second.removed, second.embedded), (3, 0, 0, 0))

    def test_only_the_changed_file_is_embedded(self):
        self._sync()
        self.embedder.texts.clear()
        self._write("src/cart.ts", "export function removeFromCart(item) {\n  return cart.pop();\n}\n")
        report = self._sync()
        self.assertEqual((report.changed, report.embedded), (1, 1))
        self.assertEqual(len(self.embedder.texts), 1)
        self.assertIn("removeFromCart", self.embedder.texts[0])

    def test_deleted_file_leaves_the_search(self):
        self._sync()
        (self.repo / "src/cart.ts").unlink()
        self.assertEqual(self._sync().removed, 1)
        self.assertNotIn("src/cart.ts", [hit.path for hit in self._search("addToCart")])

    def test_identical_content_is_embedded_once(self):
        self._write("src/copy.ts", (self.repo / "src/login.ts").read_text(encoding="utf-8"))
        self.assertEqual(self._sync().embedded, 3)
        paths = [hit.path for hit in self._search("handleLogin")]
        self.assertIn("src/login.ts", paths)
        self.assertIn("src/copy.ts", paths)

    def test_changing_model_keeps_the_previous_vectors(self):
        self._sync()
        other = CountingEmbedder("test:b")
        self.assertEqual(self._sync(other).embedded, 3)
        self.assertEqual(self._sync(other).embedded, 0)
        self.assertEqual(self._sync().embedded, 0)

    def test_interrupted_embedding_resumes(self):
        class Broken(CountingEmbedder):
            def embed(self, text):
                raise RuntimeError("Ollama unavailable")

        with self.assertRaises(RuntimeError):
            self._sync(Broken("test:a"))
        self.assertEqual(self._sync().embedded, 3)

    def test_ragignore_is_honored(self):
        (self.repo / ".ragignore").write_text("docs/\n", encoding="utf-8")
        self.assertEqual(self._sync().files, 2)

    def test_too_small_embedding_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, "at least 1024"):
            self._sync(NGramEmbedder(dim=256))

    def test_identifier_parts_match_full_text(self):
        self._sync()
        hits = self._search("where is the login handled", collection="code")
        login = next(hit for hit in hits if hit.path == "src/login.ts")
        self.assertIsNotNone(login.lexical_rank)
        self.assertEqual(hits[0].path, "src/login.ts")

    def test_collection_filter(self):
        self._sync()
        self.assertEqual({hit.collection for hit in self._search("checkout", collection="docs")}, {"docs"})

    def test_results_are_read_from_disk_and_marked_stale(self):
        self._sync()
        self.assertFalse(self._search("handleLogin")[0].stale)
        self._write("src/login.ts", "export function handleLogin(user) {\n  return signIn(user);\n}\n")
        hit = next(hit for hit in self._search("handleLogin") if hit.path == "src/login.ts")
        self.assertIn("signIn", hit.text)
        self.assertTrue(hit.stale)

    def test_find_symbol_and_where_used(self):
        self._write("src/app.ts", "import { handleLogin } from './login';\nhandleLogin(user);\n")
        self._sync()
        definition = find_symbol("handleLogin", "shop", store=self.store)[0]
        self.assertEqual((definition["path"], definition["kind"], definition["exported"]), ("src/login.ts", "function", True))
        self.assertEqual(find_symbol("handlelog", "shop", store=self.store)[0]["name"], "handleLogin")
        self.assertEqual([row["path"] for row in where_used("handleLogin", "shop", store=self.store)], ["src/app.ts"])
        self.assertEqual([row["path"] for row in where_used("src/login.ts", "shop", store=self.store)], ["src/app.ts"])

    def test_new_file_resolves_imports_of_unchanged_files(self):
        self._write("src/app.ts", "import { later } from './later';\n")
        self._sync()
        self.assertIsNone(where_used("later", "shop", store=self.store)[0]["resolved_path"])
        self._write("src/later.ts", "export const later = 1;\n")
        self._sync()
        self.assertEqual(where_used("later", "shop", store=self.store)[0]["resolved_path"], "src/later.ts")

    def test_deleted_file_removes_its_symbols(self):
        self._sync()
        (self.repo / "src/login.ts").unlink()
        self._sync()
        self.assertEqual(find_symbol("handleLogin", "shop", store=self.store), [])

    def test_a_new_chunker_version_chunks_again_and_reuses_vectors(self):
        self._sync()
        with self.store.connect() as conn:
            conn.execute("UPDATE files SET chunker_version = 1")
        report = self._sync()
        self.assertEqual((report.changed, report.embedded), (3, 0))

    def test_vector_candidates_can_use_the_hnsw_index(self):
        self._sync()
        found = self.store.project("shop")
        plan = self.store.semantic_plan(
            found["id"], NGramEmbedder(dim=EMBED_DIM).embed("login"), "test:a", force_index=True
        )
        self.assertIn("embeddings_vector_idx", plan)


if __name__ == "__main__":
    unittest.main()
