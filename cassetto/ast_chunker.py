"""
AST-based code chunker using tree-sitter.

Parses source files into their actual structure (functions, classes, methods)
instead of guessing with regex. Each chunk = one real symbol with exact
line boundaries.

Supports 13 languages via tree-sitter-language-pack.
Built for tree-sitter 0.25.x where most node accessors are methods, not properties.
"""
import hashlib
from pathlib import Path
from dataclasses import dataclass
from .config import MAX_CHUNK_SIZE, MIN_CHUNK_SIZE

# which file extension maps to which tree-sitter grammar
EXTENSION_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.kt': 'kotlin',
    '.kts': 'kotlin',
    '.rb': 'ruby',
    '.php': 'php',
    '.cs': 'c_sharp',
    '.cpp': 'cpp',
    '.c': 'c',
    '.h': 'c',
    '.hpp': 'cpp',
}

# AST node types worth extracting as standalone chunks, per language
SYMBOL_TYPES = {
    'python': {
        'function_definition', 'class_definition', 'decorated_definition',
    },
    'javascript': {
        'function_declaration', 'class_declaration', 'method_definition',
        'arrow_function', 'variable_declaration',
    },
    'typescript': {
        'function_declaration', 'class_declaration', 'method_definition',
        'interface_declaration', 'type_alias_declaration',
    },
    'tsx': {
        'function_declaration', 'class_declaration', 'method_definition',
        'interface_declaration', 'type_alias_declaration',
    },
    'go': {
        'function_declaration', 'method_declaration', 'type_declaration',
    },
    'rust': {
        'function_item', 'impl_item', 'struct_item', 'enum_item',
    },
    'java': {
        'method_declaration', 'class_declaration', 'interface_declaration',
    },
    'kotlin': {
        'function_declaration', 'class_declaration',
        'object_declaration', 'companion_object',
    },
    'ruby': {
        'method', 'class', 'module',
    },
    'php': {
        'function_definition', 'class_declaration', 'method_declaration',
    },
    'c_sharp': {
        'method_declaration', 'class_declaration', 'interface_declaration',
    },
    'cpp': {
        'function_definition', 'struct_specifier', 'class_specifier',
    },
    'c': {
        'function_definition', 'struct_specifier',
    },
}

# node types that hold a symbol's name
_NAME_KINDS = {'identifier', 'property_identifier', 'name', 'simple_identifier',
               'field_identifier', 'type_identifier'}


@dataclass
class Chunk:
    id: str
    file: str
    symbol: str
    symbol_type: str
    chunk: str
    start_line: int
    end_line: int
    language: str
    ast_hash: str


def chunk_file(file_path: str) -> list[Chunk]:
    """Parse a source file and return one Chunk per top-level symbol."""
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    try:
        source_bytes = path.read_bytes()
        source = source_bytes.decode('utf-8', errors='ignore')
    except Exception:
        return []

    if not source.strip():
        return []

    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(lang_name)
        tree = parser.parse(source)
    except Exception as e:
        print(f"  [WARN] tree-sitter failed on {file_path}: {e}")
        return []

    root = tree.root_node()

    if root.has_error():
        print(f"  [WARN] syntax errors in {file_path}, parsing what we can")

    # byte offsets from tree-sitter are UTF-8 byte positions, not python
    # string indices. we pass source_bytes everywhere so slicing is correct
    # even when the file has multi-byte chars (like em-dashes in docstrings).
    symbol_types = SYMBOL_TYPES.get(lang_name, set())
    chunks: list[Chunk] = []
    _walk(root, source_bytes, file_path, lang_name, symbol_types, chunks)

    # if the file has no functions/classes (e.g. a config file), treat the
    # whole thing as one chunk so it still shows up in search
    if not chunks:
        file_hash = hashlib.sha256(source_bytes).hexdigest()[:16]
        chunk_id = hashlib.sha256(
            f"{file_path}:module_level".encode()
        ).hexdigest()[:16]
        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol='module_level',
            symbol_type='module',
            chunk=source[:MAX_CHUNK_SIZE],
            start_line=0,
            end_line=source.count('\n'),
            language=lang_name,
            ast_hash=file_hash,
        ))

    return chunks


def _walk(node, source_bytes: bytes, file_path: str, lang_name: str,
          symbol_types: set[str], chunks: list[Chunk]):
    """
    Walk the AST recursively. When we hit a symbol node (function, class, etc),
    grab it as a chunk and stop recursing into it — otherwise nested methods
    would show up twice.
    """
    node_kind = node.kind()

    if node_kind in symbol_types:
        chunk_text = source_bytes[node.start_byte():node.end_byte()].decode(
            'utf-8', errors='ignore')

        if len(chunk_text) > MAX_CHUNK_SIZE:
            chunk_text = chunk_text[:MAX_CHUNK_SIZE] + "\n# [truncated]"

        symbol = _symbol_name(node, source_bytes) or f"anon_{node.start_position().row}"
        ast_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
        chunk_id = hashlib.sha256(
            f"{file_path}:{symbol}:{node.start_position().row}".encode()
        ).hexdigest()[:16]

        if len(chunk_text.strip()) >= MIN_CHUNK_SIZE:
            chunks.append(Chunk(
                id=chunk_id,
                file=file_path,
                symbol=symbol,
                symbol_type=node_kind,
                chunk=chunk_text,
                start_line=node.start_position().row,
                end_line=node.end_position().row,
                language=lang_name,
                ast_hash=ast_hash,
            ))
        return

    for i in range(node.child_count()):
        _walk(node.child(i), source_bytes, file_path, lang_name,
              symbol_types, chunks)


def _symbol_name(node, source_bytes: bytes) -> str | None:
    """Pull the name out of a function/class/method AST node."""
    # tree-sitter grammars tag the name with a 'name' field
    name_node = node.child_by_field_name('name')
    if name_node:
        return source_bytes[name_node.start_byte():name_node.end_byte()].decode(
            'utf-8', errors='ignore')

    # fallback: scan direct children for identifier-like nodes
    for i in range(node.child_count()):
        child = node.child(i)
        if child.kind() in _NAME_KINDS:
            return source_bytes[child.start_byte():child.end_byte()].decode(
                'utf-8', errors='ignore')

    # python decorated definitions (@decorator above a def/class) — dig
    # one level deeper to find the actual function name
    if node.kind() == 'decorated_definition':
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() in ('function_definition', 'class_definition'):
                return _symbol_name(child, source_bytes)
    return None


def diff_chunks(old_chunks: list[dict], new_chunks: list[Chunk]):
    """
    Compare what's stored vs what we just parsed.
    Returns (added, modified, deleted_ids) so the watcher knows
    what actually changed.
    """
    old = {c['id']: c['ast_hash'] for c in old_chunks}
    new = {c.id: c for c in new_chunks}

    added = [c for cid, c in new.items() if cid not in old]
    deleted_ids = [cid for cid in old if cid not in new]
    modified = [c for cid, c in new.items()
                if cid in old and old[cid] != c.ast_hash]

    return added, modified, deleted_ids
