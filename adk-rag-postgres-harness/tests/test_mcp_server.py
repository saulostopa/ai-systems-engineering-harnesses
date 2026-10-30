"""The MCP tools, called through a real MCP client session."""

from __future__ import annotations

import asyncio
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
from adk_rag_postgres_harness.memory import read_memories
from adk_rag_postgres_harness.retrieval import MAX_READ_LINES
from adk_rag_postgres_harness.store import PostgresStore, database_url
from rag_harness.embeddings import NGramEmbedder

try:
    import psycopg
    from adk_rag_postgres_harness.mcp_server import build_server
    from mcp.shared.memory import create_connected_server_and_client_session as connect
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


@unittest.skipUnless(_database_available(), "PostgreSQL is not running: docker compose up -d postgres")
class McpToolTests(unittest.TestCase):
    def setUp(self):
        self.database = f"harness_test_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{self.database}"')
        self.store = PostgresStore(urlunsplit(urlsplit(database_url())._replace(path=f"/{self.database}")))
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "shop"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "cart.ts").write_text(
            "export function addToCart(item: string) {\n  return item;\n}\n", encoding="utf-8"
        )
        (self.repo / "src" / "page.ts").write_text(
            "import { addToCart } from './cart';\nexport const open = () => addToCart('book');\n", encoding="utf-8"
        )
        (self.repo / "long.txt").write_text("line\n" * (MAX_READ_LINES + 50), encoding="utf-8")
        (self.repo / ".env").write_text("SECRET_VALUE=do-not-serve\n", encoding="utf-8")
        (self.repo / ".gitignore").write_text(".env\n", encoding="utf-8")
        (Path(self.temp.name) / "outside.txt").write_text("outside\n", encoding="utf-8")
        self.embedder = NGramEmbedder(dim=EMBED_DIM)
        sync(str(self.repo), embedder=self.embedder, store=self.store)
        self.server = build_server("shop", embedder=self.embedder, store=self.store)

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(database_url(), autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{self.database}" WITH (FORCE)')

    def _call(self, tool: str, /, **arguments):
        async def run():
            async with connect(self.server._mcp_server) as session:
                return await session.call_tool(tool, arguments)

        return asyncio.run(run())

    def _ok(self, tool: str, /, **arguments) -> dict:
        result = self._call(tool, **arguments)
        self.assertFalse(result.isError, result.content)
        return json.loads(result.content[0].text)

    def test_lists_exactly_the_agreed_tools(self):
        async def run():
            async with connect(self.server._mcp_server) as session:
                return await session.list_tools()

        tools = asyncio.run(run()).tools
        self.assertEqual({tool.name for tool in tools}, {"search_code", "find_symbol", "read_lines", "remember", "recall"})
        for tool in tools:
            self.assertTrue(tool.meta["anthropic/alwaysLoad"], tool.name)

    def test_search_returns_lines_from_disk(self):
        hits = self._ok("search_code", query="addToCart", collection="code")["hits"]
        by_path = {hit["path"]: hit for hit in hits}
        self.assertIn("return item", by_path["src/cart.ts"]["text"])

    def test_find_symbol_returns_definition_and_importers(self):
        found = self._ok("find_symbol", name="addToCart")
        self.assertEqual(found["definitions"][0]["path"], "src/cart.ts")
        self.assertEqual([row["path"] for row in found["importers"]], ["src/page.ts"])

    def test_read_lines_serves_a_range(self):
        result = self._ok("read_lines", path="src/cart.ts", start_line=2, end_line=2)
        self.assertEqual(result["text"], "  return item;")
        self.assertEqual(result["total_lines"], 3)
        self.assertFalse(result["stale"])

    def test_read_lines_marks_a_changed_file_as_stale(self):
        (self.repo / "src" / "cart.ts").write_text("// moved\n", encoding="utf-8")
        self.assertTrue(self._ok("read_lines", path="src/cart.ts")["stale"])

    def test_read_lines_cuts_long_ranges(self):
        result = self._ok("read_lines", path="long.txt")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["end_line"], MAX_READ_LINES)

    def test_read_lines_refuses_what_is_not_indexed(self):
        for path in (".env", "../outside.txt", str(Path(self.temp.name) / "outside.txt"), "src/../.env"):
            result = self._call("read_lines", path=path)
            self.assertTrue(result.isError, path)
            self.assertNotIn("do-not-serve", result.content[0].text)
            self.assertNotIn("outside\n", result.content[0].text)

    def test_read_lines_refuses_an_indexed_link_that_leaves_the_repository(self):
        link = self.repo / "src" / "link.ts"
        link.symlink_to(Path(self.temp.name) / "outside.txt")
        with self.store.connect() as conn:
            conn.execute(
                "INSERT INTO files (project_id, path, content_hash, collection, language, chunker_version) "
                "SELECT project_id, 'src/link.ts', content_hash, collection, language, chunker_version "
                "FROM files WHERE path = 'src/cart.ts'"
            )
        self.assertTrue(self._call("read_lines", path="src/link.ts").isError)

    def test_remember_and_recall_share_the_versioned_file(self):
        saved = self._ok("remember", text="Carts are saved on the server.", source="PR 7", kind="decision")
        self.assertEqual(saved["file"], "docs/harness/memories.jsonl")
        self.assertEqual(read_memories(self.repo / saved["file"])[0].id, saved["id"])

        hits = self._ok("recall", query="where are carts saved", kind="decision")["hits"]
        self.assertEqual(hits[0]["memory_id"], saved["id"])

    def test_remember_refuses_a_credential_without_repeating_it(self):
        secret = "sk-or-v1-abcdef0123456789abcdef"
        result = self._call("remember", text=f"the key is {secret}", source="chat")
        self.assertTrue(result.isError)
        self.assertNotIn(secret, result.content[0].text)
        self.assertFalse((self.repo / "docs" / "harness" / "memories.jsonl").exists())

    def test_an_unknown_project_is_a_tool_error(self):
        self.server = build_server("nope", embedder=self.embedder, store=self.store)
        result = self._call("find_symbol", name="addToCart")
        self.assertTrue(result.isError)
        self.assertIn("index it first", result.content[0].text)

    def test_an_unreachable_database_says_what_to_do(self):
        down = PostgresStore("postgresql://harness:harness@localhost:1/none")
        self.server = build_server("shop", embedder=self.embedder, store=down)
        result = self._call("find_symbol", name="addToCart")
        self.assertTrue(result.isError)
        self.assertIn("docker compose up", result.content[0].text)


if __name__ == "__main__":
    unittest.main()
