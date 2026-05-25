"""
Call graph extraction using tree-sitter.

Walks the full AST of a file, finds every function call, and maps it
back to whichever chunk (function/class) contains that line. The result
is a list of "X calls Y" relationships that get stored in the graph DB.

The called function name is just a string at this point — it gets resolved
to an actual symbol ID later in the indexer, once all symbols are stored.
"""
from dataclasses import dataclass
from pathlib import Path
from ast_chunker import EXTENSION_MAP, Chunk


@dataclass
class Relationship:
    from_symbol_id: str       # chunk ID of the function making the call
    to_symbol_name: str        # name of what's being called (resolved later)
    rel_type: str              # 'calls'


# tree-sitter uses different node names for function calls in each language
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


def extract_relationships(file_path: str,
                           chunks: list[Chunk]) -> list[Relationship]:
    """
    Find all function calls in a file and figure out which chunk each
    call lives in. Returns unresolved relationships (names, not IDs).
    """
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    try:
        from tree_sitter_language_pack import get_parser
        source_bytes = path.read_bytes()
        parser = get_parser(lang_name)
        tree = parser.parse(source_bytes.decode('utf-8', errors='ignore'))
    except Exception:
        return []

    # map each source line number to the chunk it belongs to, so when we
    # find a call on line N we know which function is making that call
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
    """Recurse through AST looking for call nodes."""
    if node.kind() == call_type:
        if node.child_count() > 0:
            func_node = node.child(0)
            called_name = source_bytes[
                func_node.start_byte():func_node.end_byte()
            ].decode('utf-8', errors='ignore')

            # "obj.method()" -> "method", "func()" -> "func"
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

    for i in range(node.child_count()):
        _find_calls(node.child(i), source_bytes, line_to_chunk,
                    call_type, rels)
