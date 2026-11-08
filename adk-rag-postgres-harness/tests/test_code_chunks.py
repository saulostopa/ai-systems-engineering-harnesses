from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from adk_rag_postgres_harness.code_chunks import (
    MAX_LINES,
    load_aliases,
    parse_python_imports,
    parse_tree_sitter,
    resolve_import,
)

SCREEN = """import React, { useState as useLocalState } from 'react';
import * as api from '@lib/api';
import type { User } from './types';
export { helper } from './helper';

// The login screen.
export function LoginScreen({ user }: { user: User }) {
  const [name] = useLocalState(user.name);
  const label = name.trim();
  return <Text>{label}</Text>;
}

export const useSession = () => {
  const session = api.current();
  const active = Boolean(session);
  return { session, active };
};

const Card = memo(() => {
  const a = 1;
  const b = 2;
  return <View />;
});
export default Card;

interface Props {
  title: string;
  subtitle: string;
  footer: string;
}

export class Store {
  load() {
    return 1;
  }
  save() {
    return 2;
  }
}

const LIMIT = 10;
"""


class TreeSitterTests(unittest.TestCase):
    def setUp(self):
        self.parsed = parse_tree_sitter("screen.tsx", SCREEN)
        self.symbols = {symbol.name: symbol for symbol in self.parsed.symbols}

    def test_definitions_have_kinds(self):
        kinds = {name: symbol.kind for name, symbol in self.symbols.items()}
        self.assertEqual(kinds["LoginScreen"], "component")
        self.assertEqual(kinds["useSession"], "hook")
        self.assertEqual(kinds["Card"], "component")
        self.assertEqual(kinds["Props"], "interface")
        self.assertEqual(kinds["Store"], "class")
        self.assertEqual(kinds["LIMIT"], "const")

    def test_exports_include_later_default(self):
        self.assertTrue(self.symbols["LoginScreen"].exported)
        self.assertTrue(self.symbols["Card"].exported)
        self.assertFalse(self.symbols["Props"].exported)

    def test_class_methods_are_symbols(self):
        self.assertEqual((self.symbols["load"].kind, self.symbols["load"].parent), ("method", "Store"))

    def test_imports_keep_names_and_aliases(self):
        refs = {(ref.specifier, ref.name, ref.alias) for ref in self.parsed.imports}
        self.assertIn(("react", "default", "React"), refs)
        self.assertIn(("react", "useState", "useLocalState"), refs)
        self.assertIn(("@lib/api", "*", "api"), refs)
        self.assertIn(("./types", "User", "User"), refs)
        self.assertIn(("./helper", "helper", "helper"), refs)

    def test_component_is_one_chunk_with_its_comment(self):
        chunk = next(chunk for chunk in self.parsed.chunks if chunk.name == "LoginScreen")
        self.assertEqual(chunk.kind, "component")
        self.assertTrue(chunk.text.startswith("// The login screen."))
        self.assertTrue(chunk.text.rstrip().endswith("}"))

    def test_chunk_lines_match_the_source(self):
        lines = SCREEN.splitlines()
        for chunk in self.parsed.chunks:
            self.assertEqual(chunk.text, "\n".join(lines[chunk.start_line - 1:chunk.end_line]))

    def test_every_statement_is_covered(self):
        covered = {line for c in self.parsed.chunks for line in range(c.start_line, c.end_line + 1)}
        for number, line in enumerate(SCREEN.splitlines(), 1):
            if line.strip():
                self.assertIn(number, covered, line)

    def test_long_function_splits_between_statements_and_keeps_its_name(self):
        body = "\n".join(f"  const value{i} = {i};" for i in range(200))
        parsed = parse_tree_sitter("long.ts", f"export function longOne() {{\n{body}\n}}\n")
        self.assertGreater(len(parsed.chunks), 1)
        for chunk in parsed.chunks:
            self.assertEqual(chunk.name, "longOne")
            self.assertLessEqual(chunk.end_line - chunk.start_line + 1, MAX_LINES)
        self.assertEqual(parsed.chunks[-1].end_line, 202)
        self.assertEqual(len(parsed.symbols), 1)

    def test_broken_code_still_produces_chunks(self):
        self.assertTrue(parse_tree_sitter("bad.ts", "function ok() {\n  return 1;\n}\nconst = ;;\n").chunks)

    def test_javascript_uses_its_own_grammar(self):
        parsed = parse_tree_sitter("a.js", "const { x } = require('y');\nexport function run() {\n  return <A />;\n}\n")
        self.assertIn("run", [symbol.name for symbol in parsed.symbols])


class ImportResolutionTests(unittest.TestCase):
    PATHS = {"src/a/index.tsx", "src/a/b.ts", "src/lib/api/index.ts", "package.json"}
    ALIASES = [("@biometrik/api", "src/lib/api"), ("@package.json", "package.json"), ("@*", "src/*")]

    def test_relative_import(self):
        self.assertEqual(resolve_import("src/a/index.tsx", "./b", self.PATHS, []), "src/a/b.ts")
        self.assertEqual(resolve_import("src/a/b.ts", "../a", self.PATHS, []), "src/a/index.tsx")

    def test_aliases(self):
        self.assertEqual(resolve_import("x.ts", "@biometrik/api", self.PATHS, self.ALIASES), "src/lib/api/index.ts")
        self.assertEqual(resolve_import("x.ts", "@a/b", self.PATHS, self.ALIASES), "src/a/b.ts")

    def test_packages_stay_unresolved(self):
        self.assertIsNone(resolve_import("x.ts", "react", self.PATHS, self.ALIASES))
        self.assertIsNone(resolve_import("x.ts", "@react-navigation/native", self.PATHS, self.ALIASES))

    def test_tsconfig_with_comments_and_trailing_commas(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "tsconfig.json").write_text(
                '{\n  // aliases\n  "compilerOptions": {"baseUrl": ".", "paths": {"@*": ["./src/*"],},},\n}\n'
            )
            self.assertEqual(load_aliases(root), [("@*", "src/*")])

    def test_no_tsconfig_means_no_aliases(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(load_aliases(Path(temp)), [])


class PythonImportTests(unittest.TestCase):
    def test_python_imports(self):
        refs = {(r.specifier, r.name, r.alias) for r in parse_python_imports("import os\nfrom .a import b as c\n")}
        self.assertEqual(refs, {("os", "*", "os"), (".a", "b", "c")})


if __name__ == "__main__":
    unittest.main()
