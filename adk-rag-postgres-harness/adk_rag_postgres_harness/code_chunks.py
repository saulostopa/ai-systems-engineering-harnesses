"""Syntax-aware chunks, symbols and imports for TS, TSX and JS, through tree-sitter."""

from __future__ import annotations

import ast
import json
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path

from .embeddings import _RAG_ROOT  # noqa: F401  (puts rag_harness on the path)

from rag_harness.chunker import Chunk  # noqa: E402

# Bump to chunk every file again on the next sync.
CHUNKER_VERSION = 2
TREE_SITTER_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
RESOLVE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".json", ".d.ts")
# A chunk near this size embeds well; larger definitions split along their body.
MAX_LINES = 80
OVERLAP_LINES = 10
# Definitions shorter than this are grouped with their neighbors in one chunk.
MIN_OWN_CHUNK_LINES = 4

_DECLARATIONS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
_FUNCTION_VALUES = {"arrow_function", "function", "function_expression", "generator_function"}
_HOOK = re.compile(r"^use[A-Z0-9]")


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    exported: bool = False
    parent: str = ""


@dataclass(frozen=True)
class ImportRef:
    specifier: str
    name: str  # the name in the source module; "default" or "*" when there is none
    alias: str  # the name in this file


@dataclass
class ParsedFile:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)


@dataclass
class _Item:
    start: int  # zero-based rows, inclusive
    end: int
    kind: str = "module"
    name: str = ""
    node: object = None


def _parser(path: str):
    try:
        import tree_sitter
        import tree_sitter_javascript
        import tree_sitter_typescript
    except ImportError as exc:
        raise RuntimeError("Install the postgres extra: uv sync --extra postgres") from exc
    if path.endswith((".ts", ".mts", ".cts")):
        language = tree_sitter_typescript.language_typescript()
    elif path.endswith(".tsx"):
        language = tree_sitter_typescript.language_tsx()
    else:
        language = tree_sitter_javascript.language()
    return tree_sitter.Parser(tree_sitter.Language(language))


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _unquote(node) -> str:
    return _text(node).strip("'\"`")


def _contains_jsx(node) -> bool:
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in ("jsx_element", "jsx_self_closing_element", "jsx_fragment"):
            return True
        stack.extend(current.children)
    return False


def _callable_value(value):
    """The function behind `() => ...` or a wrapper such as `memo(() => ...)`."""

    if value is None:
        return None
    if value.type in _FUNCTION_VALUES:
        return value
    if value.type == "call_expression":
        arguments = value.child_by_field_name("arguments")
        for argument in arguments.named_children if arguments is not None else ():
            found = _callable_value(argument)
            if found is not None:
                return found
    return None


def _function_kind(name: str, node) -> str:
    if _HOOK.match(name):
        return "hook"
    if name[:1].isupper() and _contains_jsx(node):
        return "component"
    return "function"


def _declared(node) -> list[tuple[str, str, object]]:
    """(name, kind, node with the body) for what a top-level statement declares."""

    if node.type in _DECLARATIONS:
        name = _text(node.child_by_field_name("name"))
        kind = _DECLARATIONS[node.type]
        return [(name, _function_kind(name, node) if kind == "function" else kind, node)]
    if node.type in ("lexical_declaration", "variable_declaration"):
        found = []
        for declarator in node.named_children:
            if declarator.type != "variable_declarator":
                continue
            name_node = declarator.child_by_field_name("name")
            if name_node is None or name_node.type != "identifier":
                continue
            name = _text(name_node)
            function = _callable_value(declarator.child_by_field_name("value"))
            if function is not None:
                found.append((name, _function_kind(name, function), function))
            else:
                found.append((name, "const", declarator))
        return found
    if node.type == "ambient_declaration":
        return [item for child in node.named_children for item in _declared(child)]
    return []


def _import_refs(statement) -> list[ImportRef]:
    source = statement.child_by_field_name("source")
    if source is None:
        return []
    specifier = _unquote(source)
    refs: list[ImportRef] = []
    for child in statement.named_children:
        if child.type == "import_clause":
            for part in child.named_children:
                if part.type == "identifier":
                    refs.append(ImportRef(specifier, "default", _text(part)))
                elif part.type == "namespace_import":
                    refs.append(ImportRef(specifier, "*", _text(part.named_children[-1])))
                elif part.type == "named_imports":
                    for item in part.named_children:
                        if item.type == "import_specifier":
                            name = _text(item.child_by_field_name("name"))
                            refs.append(ImportRef(specifier, name, _text(item.child_by_field_name("alias")) or name))
        elif child.type == "export_clause":
            for item in child.named_children:
                if item.type == "export_specifier":
                    name = _text(item.child_by_field_name("name"))
                    refs.append(ImportRef(specifier, name, _text(item.child_by_field_name("alias")) or name))
    # `import "./x"` and `export * from "./x"` still depend on the module.
    return refs or [ImportRef(specifier, "*", "")]


def _body_of(node):
    return node.child_by_field_name("body") if node is not None else None


def _pieces(start: int, end: int, node) -> list[tuple[int, int]]:
    """Cut a long definition between the statements of its body, or by lines as a last resort."""

    if end - start + 1 <= MAX_LINES:
        return [(start, end)]
    body = _body_of(node)
    children = body.named_children if body is not None else []
    if len(children) < 2:
        return _windows(start, end)
    pieces: list[tuple[int, int]] = []
    current = start
    last = start
    for child in children:
        child_end = child.end_point[0]
        if child_end - current + 1 > MAX_LINES and last >= current:
            pieces.append((current, last))
            current = last + 1
        last = child_end
    pieces.append((current, end))
    return [window for piece in pieces for window in _windows(*piece)]


def _windows(start: int, end: int) -> list[tuple[int, int]]:
    if end - start + 1 <= MAX_LINES:
        return [(start, end)]
    windows = []
    current = start
    while True:
        stop = min(current + MAX_LINES - 1, end)
        windows.append((current, stop))
        if stop == end:
            return windows
        current = stop - OVERLAP_LINES + 1


def _top_level(root, parsed: ParsedFile) -> list[_Item]:
    items: list[_Item] = []
    exported_later: set[str] = set()
    pending_comment: int | None = None
    for statement in root.named_children:
        start = statement.start_point[0]
        end = statement.end_point[0]
        if statement.type == "comment":
            pending_comment = start if pending_comment is None else pending_comment
            continue
        begin = pending_comment if pending_comment is not None else start
        pending_comment = None

        if statement.type == "import_statement":
            parsed.imports.extend(_import_refs(statement))
            items.append(_Item(begin, end))
            continue

        declaration = statement
        exported = False
        if statement.type == "export_statement":
            exported = True
            parsed.imports.extend(_import_refs(statement))
            declaration = statement.child_by_field_name("declaration")
            if declaration is None:
                value = statement.child_by_field_name("value")
                function = _callable_value(value)
                if value is not None and value.type == "identifier":
                    exported_later.add(_text(value))
                elif function is not None:
                    declaration = None
                    parsed.symbols.append(Symbol(
                        "default", _function_kind("default", function), start + 1, end + 1, True
                    ))
                    items.append(_Item(begin, end, "function", "default", function))
                    continue
                for clause in statement.named_children:
                    if clause.type == "export_clause" and statement.child_by_field_name("source") is None:
                        for specifier in clause.named_children:
                            exported_later.add(_text(specifier.child_by_field_name("name")))
                items.append(_Item(begin, end))
                continue

        declared = _declared(declaration)
        if not declared:
            items.append(_Item(begin, end))
            continue
        for name, kind, _ in declared:
            parsed.symbols.append(Symbol(name, kind, start + 1, end + 1, exported))
        name, kind, body_node = declared[0]
        if kind == "class":
            parsed.symbols.extend(_class_members(body_node, name))
        items.append(_Item(begin, end, kind, name, body_node))

    if exported_later:
        parsed.symbols = [
            Symbol(s.name, s.kind, s.start_line, s.end_line, s.exported or s.name in exported_later, s.parent)
            for s in parsed.symbols
        ]
    return items


def _class_members(node, class_name: str) -> list[Symbol]:
    members = []
    body = _body_of(node)
    for member in body.named_children if body is not None else ():
        if member.type in ("method_definition", "abstract_method_signature", "method_signature"):
            name = _text(member.child_by_field_name("name"))
            members.append(Symbol(name, "method", member.start_point[0] + 1, member.end_point[0] + 1, parent=class_name))
    return members


def _build_chunks(path: str, lines: list[str], items: list[_Item]) -> list[Chunk]:
    chunks: list[Chunk] = []
    group: list[_Item] = []

    def add(start: int, end: int, kind: str, name: str) -> None:
        text = "\n".join(lines[start:end + 1])
        if text.strip():
            chunks.append(Chunk(path=path, kind=kind, name=name, text=text, start_line=start + 1, end_line=end + 1))

    def flush() -> None:
        if not group:
            return
        for start, end in _windows(group[0].start, group[-1].end):
            add(start, end, "module", group[0].name or "module")
        group.clear()

    for item in items:
        size = item.end - item.start + 1
        if item.kind == "module" or (item.kind == "const" and size < MIN_OWN_CHUNK_LINES) or size < MIN_OWN_CHUNK_LINES:
            if group and item.end - group[0].start + 1 > MAX_LINES:
                flush()
            group.append(item)
            continue
        flush()
        for start, end in _pieces(item.start, item.end, item.node):
            add(start, end, item.kind, item.name)
    flush()
    return chunks


def parse_tree_sitter(path: str, source: str) -> ParsedFile:
    parsed = ParsedFile()
    tree = _parser(path).parse(source.encode("utf-8"))
    items = _top_level(tree.root_node, parsed)
    parsed.chunks = _build_chunks(path, source.splitlines(), items)
    return parsed


def parse_python_imports(source: str) -> list[ImportRef]:
    try:
        module = ast.parse(source)
    except SyntaxError:
        return []
    refs: list[ImportRef] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            refs.extend(ImportRef(alias.name, "*", alias.asname or alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            specifier = "." * node.level + (node.module or "")
            refs.extend(ImportRef(specifier, alias.name, alias.asname or alias.name) for alias in node.names)
    return refs


def load_aliases(root: Path) -> list[tuple[str, str]]:
    """`compilerOptions.paths` of tsconfig.json as (pattern, target), the most specific first."""

    path = root / "tsconfig.json"
    if not path.is_file():
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        config = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r"^\s*//.*$", "", raw, flags=re.MULTILINE)
        try:
            config = json.loads(re.sub(r",(\s*[}\]])", r"\1", cleaned))
        except json.JSONDecodeError:
            return []
    options = config.get("compilerOptions") or {}
    base = options.get("baseUrl") or "."
    aliases = []
    for pattern, targets in (options.get("paths") or {}).items():
        if targets:
            aliases.append((pattern, posixpath.normpath(posixpath.join(base, targets[0]))))
    return sorted(aliases, key=lambda item: (-len(item[0].replace("*", "")), item[0]))


def _candidates(base: str) -> list[str]:
    base = posixpath.normpath(base)
    return [base, *(base + ext for ext in RESOLVE_EXTS), *(f"{base}/index{ext}" for ext in RESOLVE_EXTS)]


def resolve_import(from_path: str, specifier: str, paths: set[str], aliases: list[tuple[str, str]]) -> str | None:
    """The indexed file an import points to; None for packages and unknown modules."""

    bases: list[str] = []
    if specifier.startswith("."):
        bases.append(posixpath.join(posixpath.dirname(from_path), specifier))
    else:
        for pattern, target in aliases:
            if "*" in pattern:
                prefix, _, suffix = pattern.partition("*")
                if specifier.startswith(prefix) and specifier.endswith(suffix):
                    middle = specifier[len(prefix):len(specifier) - len(suffix)]
                    bases.append(target.replace("*", middle))
            elif specifier == pattern:
                bases.append(target)
    for base in bases:
        for candidate in _candidates(base):
            if candidate in paths:
                return candidate
    return None
