"""
Codebase Intelligence — Graph Extractor (Stage 3)
Extracts function call relationships from source files using Tree-sitter.

Walks the full AST of a file, finds call expressions, and maps them
back to the chunk (function/class) that contains them.

Built for tree-sitter >= 0.25.x API (kind(), child(), start_byte(), etc.)
"""
from dataclasses import dataclass
from pathlib import Path
from ast_chunker import EXTENSION_MAP, Chunk


@dataclass
class Relationship:
    """A directed edge in the call graph."""
    from_symbol_id: str      # chunk ID of the caller
    to_symbol_name: str       # name of the called function (resolved to ID later)
    rel_type: str             # 'calls' | 'imports'


# Call expression node types per language
_CALL_TYPES = {
    'python': 'call',
    'javascript': 'call_expression',
    'typescript': 'call_expression',
    'tsx': 'call_expression',
    'go': 'call_expression',
    'rust': 'call_expression',
    'java': 'method_invocation',
    'ruby': 'call',
    'php': 'function_call_expression',
    'c_sharp': 'invocation_expression',
    'cpp': 'call_expression',
    'c': 'call_expression',
}

# Import node types per language
_IMPORT_TYPES = {
    'python': {'import_from_statement', 'import_statement'},
    'javascript': {'import_statement'},
    'typescript': {'import_statement'},
    'tsx': {'import_statement'},
    'go': {'import_declaration'},
    'java': {'import_declaration'},
}


def extract_relationships(file_path: str,
                           chunks: list[Chunk]) -> list[Relationship]:
    """
    Extract call relationships from a file.
    For each function call found, maps it to the containing chunk.

    Args:
        file_path: path to the source file
        chunks: list of Chunk objects from ast_chunker (for this file only)

    Returns:
        List of Relationship objects (to_symbol_name needs resolution later)
    """
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    try:
        from tree_sitter_language_pack import get_parser
        source_bytes = path.read_bytes()
        source = source_bytes.decode('utf-8', errors='ignore')
        parser = get_parser(lang_name)
        tree = parser.parse(source)
    except Exception:
        return []

    # Build line → chunk_id map for this file
    line_to_chunk: dict[int, str] = {}
    for chunk in chunks:
        for line in range(chunk.start_line, chunk.end_line + 1):
            line_to_chunk[line] = chunk.id

    call_type = _CALL_TYPES.get(lang_name, 'call_expression')
    rels: list[Relationship] = []
    _find_calls(tree.root_node(), source_bytes, line_to_chunk,
                call_type, rels)

    return rels


def _find_calls(node, source_bytes: bytes, line_to_chunk: dict[int, str],
                call_type: str, rels: list[Relationship]):
    """
    Recursively walk the AST to find function call nodes.
    For each call, extract the called function name and map it
    to the containing chunk via line number.
    """
    if node.kind() == call_type:
        # The first child of a call expression is the function being called
        if node.child_count() > 0:
            func_node = node.child(0)
            called_name = source_bytes[
                func_node.start_byte():func_node.end_byte()
            ].decode('utf-8', errors='ignore')

            # Strip method chains: obj.method → method
            # Strip parens: func( → func
            called_name = called_name.split('.')[-1].split('(')[0].strip()

            if called_name and called_name.isidentifier():
                caller_line = node.start_position().row
                caller_id = line_to_chunk.get(caller_line)
                if caller_id:
                    rels.append(Relationship(
                        from_symbol_id=caller_id,
                        to_symbol_name=called_name,
                        rel_type='calls'
                    ))

    # Recurse into all children
    for i in range(node.child_count()):
        _find_calls(node.child(i), source_bytes, line_to_chunk,
                    call_type, rels)
