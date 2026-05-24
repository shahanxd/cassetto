"""
Codebase Intelligence — AST Chunker (Stage 2)
Replaces naive chunker with Tree-sitter AST parsing.
Every chunk maps to exactly one function, class, method, or interface.

Uses tree-sitter-language-pack for 170+ language support in one install.
Same chunk_file() interface as chunker.py — drop-in replacement.

NOTE: Built for tree-sitter >= 0.25.x API where node properties are methods:
  node.kind(), node.start_byte(), node.child(i), node.child_count(), etc.
"""
import hashlib
from pathlib import Path
from dataclasses import dataclass
from config import SUPPORTED_EXTENSIONS, MAX_CHUNK_SIZE, MIN_CHUNK_SIZE

# --- Language configuration ---

EXTENSION_MAP = {
    '.py': 'python',
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'tsx',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.rb': 'ruby',
    '.php': 'php',
    '.cs': 'c_sharp',
    '.cpp': 'cpp',
    '.c': 'c',
    '.h': 'c',
    '.hpp': 'cpp',
}

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

# Identifier node types used to extract symbol names
_NAME_KINDS = {'identifier', 'property_identifier', 'name',
               'field_identifier', 'type_identifier'}


@dataclass
class Chunk:
    """A chunk of source code extracted from a file via AST parsing."""
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
    """
    Parse a source file with Tree-sitter and extract one chunk per symbol.
    Drop-in replacement for chunker.chunk_file() — same interface.
    """
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

    # Parse with tree-sitter (accepts str in 0.25.x)
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(lang_name)
        tree = parser.parse(source)
    except Exception as e:
        print(f"  [WARN] Tree-sitter parse failed for {file_path}: {e}")
        return []

    root = tree.root_node()

    # Log parse errors but don't skip — tree-sitter is error-tolerant
    if root.has_error():
        print(f"  [WARN] Syntax errors in {file_path} — parsing what's valid")

    # Walk AST and extract symbol nodes
    # IMPORTANT: pass source_bytes for slicing — tree-sitter byte offsets
    # are UTF-8 byte positions, not Python string character positions
    symbol_types = SYMBOL_TYPES.get(lang_name, set())
    chunks: list[Chunk] = []
    _walk(root, source_bytes, file_path, lang_name, symbol_types, chunks)

    # Whole-file fallback if no symbols found
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
    Recursively walk the AST and extract symbol nodes as chunks.
    When a symbol is found, DON'T recurse into it — prevents duplicates.

    source_bytes must be the raw UTF-8 bytes — tree-sitter byte offsets
    are positions in the byte stream, not character positions.
    """
    node_kind = node.kind()

    if node_kind in symbol_types:
        chunk_text = source_bytes[node.start_byte():node.end_byte()].decode(
            'utf-8', errors='ignore')

        # Truncate oversized chunks
        if len(chunk_text) > MAX_CHUNK_SIZE:
            chunk_text = chunk_text[:MAX_CHUNK_SIZE] + \
                "\n# [truncated — function too large]"

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
        return  # Don't recurse into found symbols

    # Recurse into children
    for i in range(node.child_count()):
        _walk(node.child(i), source_bytes, file_path, lang_name,
              symbol_types, chunks)


def _symbol_name(node, source_bytes: bytes) -> str | None:
    """Extract the identifier name from a symbol AST node."""
    # Primary: use tree-sitter's field-based access (most reliable)
    name_node = node.child_by_field_name('name')
    if name_node:
        return source_bytes[name_node.start_byte():name_node.end_byte()].decode(
            'utf-8', errors='ignore')

    # Fallback: scan direct children for identifier nodes
    for i in range(node.child_count()):
        child = node.child(i)
        if child.kind() in _NAME_KINDS:
            return source_bytes[child.start_byte():child.end_byte()].decode(
                'utf-8', errors='ignore')

    # For decorated definitions (Python @decorator), look inside the
    # wrapped function/class definition
    if node.kind() == 'decorated_definition':
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() in ('function_definition', 'class_definition'):
                return _symbol_name(child, source_bytes)
    return None


def diff_chunks(old_chunks: list[dict], new_chunks: list[Chunk]):
    """
    Compare old (from DB) and new (freshly parsed) chunks for a file.
    Used for incremental updates in Stage 4.

    Args:
        old_chunks: list of dicts with 'id' and 'ast_hash'
        new_chunks: list of Chunk instances (freshly parsed)

    Returns:
        (added, modified, deleted_ids)
    """
    old = {c['id']: c['ast_hash'] for c in old_chunks}
    new = {c.id: c for c in new_chunks}

    added = [c for cid, c in new.items() if cid not in old]
    deleted_ids = [cid for cid in old if cid not in new]
    modified = [c for cid, c in new.items()
                if cid in old and old[cid] != c.ast_hash]

    return added, modified, deleted_ids
