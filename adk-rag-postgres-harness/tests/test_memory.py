"""Memories: the file is the source of truth; Postgres can always be rebuilt from it."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).parents[1]))

from adk_rag_postgres_harness.embeddings import EMBED_DIM
from adk_rag_postgres_harness.ingest import sync
from adk_rag_postgres_harness.memory import (
    DEFAULT_MEMORY_FILE,
    Memory,
    MemoryRefused,
    find_credential,
    read_memories,
    recall,
    remember,
    write_memories,
)
from adk_rag_postgres_harness.store import PostgresStore, database_url
from rag_harness.embeddings import NGramEmbedder

try:
    import psycopg
except ImportError:
    psycopg = None


def _database_available() -> bool:
    if psycopg is None:
        return False
    try:
        with psycopg.connect(database_url(), connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


class CredentialTests(unittest.TestCase):
    def test_credentials_are_found_without_returning_them(self):
        samples = {
            "API key": "the key is sk-or-v1-abcdef0123456789abcdef",
            "GitHub token": "use ghp_abcdefghijklmnopqrstuvwxyz012345",
            "AWS key": "AKIAABCDEFGHIJKLMNOP",
            "JWT": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.abcdefghijkl",
            "private key": "-----BEGIN RSA PRIVATE KEY-----",
            "URL with a password": "postgresql://user:hunter2@db.example.com/app",
            "secret assignment": "password = correcthorse",
            "Stripe key": "sk_live_abcd1234efgh5678",
            "GitLab token": "glpat-abcd1234efgh5678",
            "npm token": "npm_abcd1234efgh5678abcd",
            "bearer token": "Authorization: Bearer abcd1234efgh5678",
            "secret in a sentence": "the password is abcd1234efgh",
        }
        for kind, text in samples.items():
            self.assertEqual(find_credential(text), kind, text)

    def test_names_with_a_prefix_or_suffix_are_found(self):
        for text in (
            "DB_PASSWORD=abcd1234efgh",
            "SECRET_KEY=abcd1234efgh",
            "client_secret=abcd1234efgh",
            "API_TOKEN=abcd1234efgh",
            "AWS_SECRET_ACCESS_KEY=abcd1234efgh",
            "dbPassword: abcd1234efgh",
            "senha: abcd1234efgh",
        ):
            self.assertEqual(find_credential(text), "secret assignment", text)

    def test_references_to_a_secret_pass(self):
        for text in (
            "api_key=process.env.API_KEY must be used",
            "token = getAccessToken() is called on start",
            "password: ${DB_PASSWORD}",
            "Authorization: Bearer ${ACCESS_TOKEN_VALUE}",
            "The password: required rule stays.",
            "sk-learn-integration-branch-2024",
            "The password is encrypted at rest.",
        ):
            self.assertIsNone(find_credential(text), text)

    def test_ordinary_decisions_pass(self):
        for text in (
            "Tokens are renewed by the API client when a request returns 401.",
            "The token: string field stays in the schema.",
            "Use postgresql://localhost:5433/harness_rag for local tests.",
            "The password field is hidden by default.",
        ):
            self.assertIsNone(find_credential(text), text)


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "docs" / "memories.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_round_trip_keeps_accents_readable(self):
        memory = Memory("mem_1", "decision", "Decisão com acento", "PR 12", "2026-10-30T10:00:00+00:00")
        write_memories(self.path, [memory])
        self.assertIn("Decisão", self.path.read_text(encoding="utf-8"))
        self.assertEqual(read_memories(self.path), [memory])

    def test_damaged_line_stops_with_its_number(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('<<<<<<< HEAD\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, ":1 is not a valid memory"):
            read_memories(self.path)

    def test_a_union_merge_keeps_the_replaced_version(self):
        base = {"id": "mem_1", "kind": "note", "text": "a", "source": "b", "created_at": "2026-01-01T00:00:00+00:00"}
        newer = {**base, "id": "mem_2", "superseded_by": None}
        lines = [json.dumps({**base, "superseded_by": "mem_2"}), json.dumps({**base, "superseded_by": None}), json.dumps(newer)]
        self.path.parent.mkdir(parents=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(read_memories(self.path)[0].superseded_by, "mem_2")

    def _write_line(self, **fields):
        base = {"id": "mem_1", "kind": "note", "text": "a", "source": "b", "created_at": "2026-01-01T00:00:00+00:00"}
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({**base, **fields}) + "\n", encoding="utf-8")

    def test_invalid_lines_stop_with_their_number(self):
        cases = (
            {"kind": "bogus"},
            {"created_at": "not-a-date"},
            {"created_at": None},
            {"text": ""},
            {"source": "a\x00b"},
            {"superseded_by": 7},
            {"superseded_by": "mem_unknown"},
            {"superseded_by": "mem_1"},
        )
        for fields in cases:
            self._write_line(**fields)
            with self.assertRaises(ValueError, msg=fields):
                read_memories(self.path)
            self.path.unlink()
            self.path.parent.rmdir()

    def test_a_credential_edited_into_the_file_stops_without_repeating_it(self):
        self._write_line(text="DB_PASSWORD=abcd1234efgh")
        with self.assertRaises(ValueError) as caught:
            read_memories(self.path)
        self.assertIn("secret assignment", str(caught.exception))
        self.assertNotIn("abcd1234efgh", str(caught.exception))


@unittest.skipUnless(_database_available(), "PostgreSQL is not running: docker compose up -d postgres")
class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.database = f"harness_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database}"')
        self.store = PostgresStore(urlunsplit(urlsplit(database_url())._replace(path=f"/{self.database}")))
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "shop"
        (self.repo / "docs/harness/features/login").mkdir(parents=True)
        (self.repo / "docs/harness/features/login/progress.md").write_text("Login retries were moved to the client.\n")
        (self.repo / "docs/harness/features/login/handoff.md").write_text("Next: test retries on Android.\n")
        (self.repo / "docs/other.md").write_text("Retries are unrelated here.\n")
        (self.repo / "app.ts").write_text("export const retries = 3;\n")
        self.embedder = NGramEmbedder(dim=EMBED_DIM)
        self._sync()

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')

    def _sync(self):
        return sync(str(self.repo), embedder=self.embedder, store=self.store)

    def _remember(self, text, **kwargs):
        kwargs.setdefault("source", "PR 12")
        return remember(text, "shop", embedder=self.embedder, store=self.store, **kwargs)[0]

    def _recall(self, query, **kwargs):
        return recall(query, "shop", embedder=self.embedder, store=self.store, **kwargs)

    def test_remember_writes_the_file_without_vectors(self):
        memory = self._remember("We use Postgres for the code memory.", kind="decision")
        line = json.loads((self.repo / DEFAULT_MEMORY_FILE).read_text(encoding="utf-8"))
        self.assertEqual(line["id"], memory.id)
        self.assertEqual(set(line), {"id", "kind", "text", "source", "created_at", "superseded_by"})

    def test_recall_finds_a_memory_with_its_source(self):
        self._remember("We use Postgres for the code memory.", kind="decision")
        hit = self._recall("postgres memory")[0]
        self.assertEqual((hit.origin, hit.kind, hit.source), ("memory", "decision", "PR 12"))

    def test_superseded_memory_is_not_returned_as_current(self):
        old = self._remember("The cache lives in Redis.", kind="decision")
        new = self._remember("The cache lives in Postgres.", kind="decision", supersedes=old.id)
        current = {hit.memory_id for hit in self._recall("cache lives") if hit.origin == "memory"}
        self.assertEqual(current, {new.id})
        history = {hit.memory_id: hit.superseded_by for hit in self._recall("cache lives", include_superseded=True)}
        self.assertEqual(history[old.id], new.id)

    def test_same_memory_twice_is_one_line(self):
        self._remember("A convention.", kind="convention")
        self._remember("A convention.", kind="convention")
        self.assertEqual(len(read_memories(self.repo / DEFAULT_MEMORY_FILE)), 1)

    def test_credential_is_refused_and_never_reaches_the_file(self):
        secret = "sk-or-v1-abcdef0123456789abcdef"
        with self.assertRaises(MemoryRefused) as caught:
            self._remember(f"The OpenRouter key is {secret}")
        self.assertNotIn(secret, str(caught.exception))
        self.assertFalse((self.repo / DEFAULT_MEMORY_FILE).exists())

    def test_credential_in_the_source_is_refused(self):
        with self.assertRaises(MemoryRefused):
            self._remember("A decision.", source="postgresql://user:hunter2@db/app")

    def test_invalid_entries_are_refused(self):
        with self.assertRaises(MemoryRefused):
            self._remember("A decision.", source=" ")
        with self.assertRaises(MemoryRefused):
            self._remember("A decision.", kind="rumor")
        with self.assertRaises(MemoryRefused):
            self._remember("x" * 2001)
        with self.assertRaises(MemoryRefused):
            self._remember("A decision.", supersedes="mem_unknown")

    def test_memory_without_a_vector_matches_by_text_and_is_embedded_later(self):
        class Offline(NGramEmbedder):
            def embed(self, text):
                raise RuntimeError("Ollama unavailable")

        offline = Offline(dim=EMBED_DIM)
        offline.model_id = self.embedder.model_id
        memory, embedded = remember("Offline decision about retries.", "shop", "PR 12", embedder=offline, store=self.store)
        self.assertFalse(embedded)
        self.assertEqual(self._recall("offline decision")[0].memory_id, memory.id)
        self.assertEqual(self._sync().embedded, 1)

    def test_recall_includes_feature_logs_but_not_other_documents(self):
        hits = self._recall("retries")
        sources = {hit.source for hit in hits}
        self.assertIn("docs/harness/features/login/progress.md", sources)
        self.assertIn("docs/harness/features/login/handoff.md", sources)
        self.assertNotIn("docs/other.md", sources)
        self.assertNotIn("app.ts", sources)

    def test_recall_filters_by_kind(self):
        self._remember("Retries are a decision.", kind="decision")
        self.assertEqual({hit.origin for hit in self._recall("retries", kind="decision")}, {"memory"})
        self.assertEqual({hit.kind for hit in self._recall("retries", kind="progress")}, {"progress"})
        self.assertEqual({hit.kind for hit in self._recall("retries", kind="handoff")}, {"handoff"})

    def test_a_memory_removed_from_the_file_leaves_the_database(self):
        keep = self._remember("Keep this retries decision.")
        drop = self._remember("Drop this retries decision.")
        path = self.repo / DEFAULT_MEMORY_FILE
        write_memories(path, [memory for memory in read_memories(path) if memory.id == keep.id])
        self._sync()
        ids = {hit.memory_id for hit in self._recall("retries decision")}
        self.assertIn(keep.id, ids)
        self.assertNotIn(drop.id, ids)

    def test_damaged_file_stops_the_sync_and_stays_untouched(self):
        self._remember("A decision.")
        path = self.repo / DEFAULT_MEMORY_FILE
        path.write_text("<<<<<<< HEAD\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self._sync()
        self.assertEqual(path.read_text(encoding="utf-8"), "<<<<<<< HEAD\n")

    def test_dropping_the_database_loses_nothing(self):
        old = self._remember("The cache lives in Redis.", kind="decision")
        new = self._remember("The cache lives in Postgres.", kind="decision", supersedes=old.id)
        note = self._remember("Retries live in the client.", kind="convention", source="login handoff")
        before = read_memories(self.repo / DEFAULT_MEMORY_FILE)

        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE "{self.database}" WITH (FORCE)')
            conn.execute(f'CREATE DATABASE "{self.database}"')

        report = self._sync()
        self.assertEqual(report.memories, 3)
        self.assertEqual(read_memories(self.repo / DEFAULT_MEMORY_FILE), before)
        current = {hit.memory_id for hit in self._recall("cache lives retries client")}
        self.assertTrue({new.id, note.id} <= current)
        self.assertNotIn(old.id, current)
        self.assertEqual(self._recall("retries client", kind="convention")[0].source, "login handoff")
        self.assertEqual(self._sync().embedded, 0)

    def test_line_separators_in_the_text_keep_the_file_readable(self):
        for separator in ("\u2028", "\u2029", "\u0085", "\x0c"):
            self._remember(f"first{separator}second")
        self.assertEqual(len(read_memories(self.repo / DEFAULT_MEMORY_FILE)), 4)
        self.assertEqual(self._sync().memories, 4)

    def test_a_nul_in_the_source_does_not_damage_the_file(self):
        memory = self._remember("A decision.", source="pa\x00ste")
        self.assertEqual(memory.source, "paste")
        self._sync()

    def test_text_that_cannot_be_saved_is_refused(self):
        with self.assertRaises(MemoryRefused):
            self._remember("broken \ud800 text")
        self.assertFalse((self.repo / DEFAULT_MEMORY_FILE).exists())

    def test_a_replaced_memory_cannot_be_replaced_again(self):
        old = self._remember("Decision A.", kind="decision")
        self._remember("Decision B.", kind="decision", supersedes=old.id)
        with self.assertRaisesRegex(MemoryRefused, "already replaced"):
            self._remember("Decision C.", kind="decision", supersedes=old.id)

    def test_repeating_a_replaced_text_does_not_revive_it(self):
        old = self._remember("Decision A.", kind="decision")
        new = self._remember("Decision B.", kind="decision", supersedes=old.id)
        with self.assertRaisesRegex(MemoryRefused, new.id):
            self._remember("Decision A.", kind="decision", source="other")
        memories = {memory.id: memory for memory in read_memories(self.repo / DEFAULT_MEMORY_FILE)}
        self.assertEqual(memories[old.id].superseded_by, new.id)
        self.assertEqual(memories[old.id].source, "PR 12")

    def test_repeating_a_current_memory_keeps_its_first_source(self):
        first = self._remember("Decision A.")
        again = self._remember("Decision A.", source="other")
        self.assertEqual((again.id, again.source), (first.id, "PR 12"))

    def test_index_applies_a_hand_edit_of_the_text(self):
        memory = self._remember("Retries live in the client.", kind="decision")
        path = self.repo / DEFAULT_MEMORY_FILE
        path.write_text(path.read_text(encoding="utf-8").replace("in the client", "in the gateway"), encoding="utf-8")
        self.assertEqual(self._sync().embedded, 1)
        hit = self._recall("gateway", kind="decision")[0]
        self.assertEqual((hit.memory_id, hit.text), (memory.id, "Retries live in the gateway."))


if __name__ == "__main__":
    unittest.main()
