"""Sync and search against a real PostgreSQL; skipped when the container is down."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from adk_rag_postgres_harness.embeddings import EMBED_DIM
from adk_rag_postgres_harness.ingest import MAX_FILE_BYTES, MAX_LINE_BYTES, sync
from adk_rag_postgres_harness.retrieval import find_symbol, read_file, search_code, where_used
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

    def _indexed_paths(self) -> set[str]:
        return set(self.store.file_states(self.store.project("shop")["id"]))

    def _stored_text(self) -> str:
        with self.store.connect() as conn:
            return "\n".join(row["content"] for row in conn.execute("SELECT content FROM chunks"))

    def test_problem_files_are_skipped_and_the_rest_still_syncs(self):
        self._write("big.txt", "line\n" * (MAX_FILE_BYTES // 5 + 1))
        self._write("data.json", '{"a": "' + "x" * (MAX_LINE_BYTES + 1) + '"}')
        (self.repo / "blob.txt").write_bytes(b"abc\0def")
        self._write("locked.md", "no access")
        (self.repo / "locked.md").chmod(0)
        self._write("src/new.ts", "export const probe = 1;\n")

        report = self._sync()

        reasons = dict(report.skipped)
        self.assertIn("bytes", reasons["big.txt"])
        self.assertIn("line", reasons["data.json"])
        self.assertEqual(reasons["blob.txt"], "binary")
        if os.geteuid() != 0:
            self.assertIn("unreadable", reasons["locked.md"])
        self.assertEqual(find_symbol("probe", "shop", store=self.store)[0]["path"], "src/new.ts")
        self.assertNotIn("big.txt", self._indexed_paths())

    def test_the_largest_accepted_file_fits_full_text(self):
        # Unique words are the worst case for the 1 MB limit of a tsvector.
        line = lambda number: " ".join(f"word{number}x{column}" for column in range(MAX_LINE_BYTES // 16))
        lines, size = [], 0
        while size + MAX_LINE_BYTES < MAX_FILE_BYTES:
            lines.append(line(len(lines)))
            size += len(lines[-1]) + 1
        self._write("words.txt", "\n".join(lines))
        report = self._sync()
        self.assertEqual(report.skipped, ())
        self.assertIn("words.txt", self._indexed_paths())

    def test_a_file_that_grows_too_big_leaves_the_index(self):
        self._sync()
        self._write("src/cart.ts", "x" * (MAX_LINE_BYTES + 1))
        self.assertEqual(self._sync().removed, 1)
        self.assertNotIn("src/cart.ts", self._indexed_paths())

    def test_links_and_sensitive_names_never_reach_the_database(self):
        outside = Path(self.temp.name) / "creds.txt"
        outside.write_text("OUTSIDE-MARKER\n", encoding="utf-8")
        self._write(".env", "DOTENV-MARKER\n")
        (self.repo / "link.txt").symlink_to(outside)
        (self.repo / "env.txt").symlink_to(self.repo / ".env")
        (self.repo / "linked").symlink_to(Path(self.temp.name))
        for name in (".env.yaml", ".secrets.json", "client_secret.json", "credentials.txt"):
            self._write(name, "NAME-MARKER\n")

        reasons = dict(self._sync().skipped)

        self.assertEqual(reasons["link.txt"], "symbolic link")
        self.assertEqual(reasons["env.txt"], "symbolic link")
        self.assertEqual(reasons[".secrets.json"], "sensitive name")
        stored = self._stored_text()
        for marker in ("OUTSIDE-MARKER", "DOTENV-MARKER", "NAME-MARKER"):
            self.assertNotIn(marker, stored)

    def test_a_file_replaced_by_a_link_after_indexing_is_not_served(self):
        self._sync()
        outside = Path(self.temp.name) / "creds.txt"
        outside.write_text("OUTSIDE-MARKER\n", encoding="utf-8")
        target = self.repo / "src/cart.ts"
        target.unlink()
        target.symlink_to(outside)

        hits = self._search("addToCart")
        self.assertNotIn("src/cart.ts", {hit.path for hit in hits})
        self.assertFalse(any("OUTSIDE-MARKER" in hit.text for hit in hits))
        with self.assertRaises(ValueError):
            read_file("src/cart.ts", "shop", store=self.store)

    def test_a_path_in_another_encoding_does_not_stop_the_sync(self):
        subprocess.run(["git", "init", "-q"], cwd=self.repo, check=True)
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"], cwd=self.repo, input=b"x", capture_output=True, check=True
        ).stdout.decode().strip()
        subprocess.run(
            ["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},".encode() + b"bad\xff.md"],
            cwd=self.repo, check=True,
        )
        self.assertEqual(self._sync().files, 3)

    def test_a_missing_folder_changes_nothing(self):
        self._sync()
        with self.assertRaisesRegex(ValueError, "not a folder"):
            sync(str(self.repo / "nope"), "shop", embedder=self.embedder, store=self.store)
        self.assertEqual(len(self._indexed_paths()), 3)
        self.assertEqual(self.store.project("shop")["root"], str(self.repo.resolve()))

    def test_another_folder_needs_move(self):
        self._sync()
        other = Path(self.temp.name) / "other"
        other.mkdir()
        (other / "a.md").write_text("Other.\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "--move"):
            sync(str(other), "shop", embedder=self.embedder, store=self.store)
        self.assertEqual(self.store.project("shop")["root"], str(self.repo.resolve()))

        sync(str(other), "shop", embedder=self.embedder, store=self.store, move=True)
        self.assertEqual(self.store.project("shop")["root"], str(other.resolve()))
        self.assertEqual(self._indexed_paths(), {"a.md"})

    def test_parallel_syncs_do_not_collide(self):
        errors = []

        def run():
            try:
                self._sync(CountingEmbedder())
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self._indexed_paths()), 3)

    def test_without_a_collection_the_search_goes_by_meaning(self):
        self._sync()
        hits = self._search("how does the checkout flow work")
        self.assertTrue(hits)
        self.assertTrue(all(hit.lexical_rank is None for hit in hits))

    def test_with_a_collection_the_search_also_matches_text(self):
        self._sync()
        self.assertTrue(any(hit.lexical_rank for hit in self._search("login", collection="code")))

    def test_a_name_in_code_style_finds_its_definition_first(self):
        self._write("src/one.ts", "import { addToCart } from './cart';\naddToCart(1); addToCart(2);\n")
        self._write("src/two.ts", "import { addToCart } from './cart';\naddToCart(3); addToCart(4);\n")
        self._sync()
        for kwargs in ({}, {"collection": "code"}, {"collection": "code", "strategy": "keyword"}):
            hits = self._search("Where is addToCart defined?", **kwargs)
            self.assertEqual((hits[0].path, hits[0].kind, hits[0].score), ("src/cart.ts", "function", 1.0), kwargs)
            self.assertEqual([hit.path for hit in hits].count("src/cart.ts"), 1, kwargs)

    def test_a_definition_does_not_enter_a_docs_search(self):
        self._sync()
        hits = self._search("Where is addToCart defined?", collection="docs")
        self.assertNotIn("src/cart.ts", [hit.path for hit in hits])

    def test_a_long_definition_is_cut(self):
        body = "".join(f"  step{number}();\n" for number in range(200))
        self._write("src/long.ts", f"export function longOne() {{\n{body}}}\n")
        self._sync()
        hit = self._search("Where is longOne?")[0]
        self.assertEqual((hit.path, hit.end_line - hit.start_line + 1), ("src/long.ts", 80))

    def test_uses_finds_packages_and_normalizes_paths(self):
        self._write("src/page.ts", "import { navigate } from '@scope/nav';\nimport { addToCart } from './cart';\nexport const a = 1;\n")
        self._sync()
        for name in ("@scope/nav", "./src/cart.ts", "src/cart.ts"):
            self.assertEqual([row["path"] for row in where_used(name, "shop", store=self.store)], ["src/page.ts"], name)


if __name__ == "__main__":
    unittest.main()
