"""
Call graph + inheritance + JSX component extraction using tree-sitter.

Walks the full AST of a file and extracts three types of relationships:
  - 'calls': function X calls function Y
  - 'extends': class X extends/inherits from class Y
  - 'renders': component X renders component Y (JSX <Component />)

Called names are just strings at this point — they get resolved to
actual symbol IDs later in the indexer, once all symbols are stored.
"""
from dataclasses import dataclass
from pathlib import Path
from .ast_chunker import EXTENSION_MAP, Chunk


@dataclass
class Relationship:
    from_symbol_id: str       # chunk ID of the function making the call
    to_symbol_name: str        # name of what's being called (resolved later)
    rel_type: str              # 'calls', 'extends', or 'renders'


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

# JSX component render nodes — <Component /> or <Component>...</Component>
_JSX_COMPONENT_TYPES = {
    'jsx_self_closing_element',
    'jsx_opening_element',
}

# class inheritance nodes per language
_INHERITANCE_EXTRACTORS = {
    'python', 'javascript', 'typescript', 'tsx', 'java', 'c_sharp', 'ruby',
}


def extract_relationships(file_path: str,
                           chunks: list[Chunk]) -> list[Relationship]:
    """
    Find all function calls, JSX renders, and inheritance in a file.
    Returns unresolved relationships (names, not IDs).
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

    # map each source line number to the chunk it belongs to
    line_to_chunk: dict[int, str] = {}
    for chunk in chunks:
        for line in range(chunk.start_line, chunk.end_line + 1):
            line_to_chunk[line] = chunk.id

    call_type = _CALL_TYPES.get(lang_name, 'call_expression')
    is_jsx = lang_name in ('tsx', 'javascript')
    rels: list[Relationship] = []

    _find_all(tree.root_node(), source_bytes, line_to_chunk,
              call_type, is_jsx, lang_name, chunks, rels)

    return rels


def _find_all(node, source_bytes: bytes, line_to_chunk: dict[int, str],
              call_type: str, is_jsx: bool, lang_name: str,
              chunks: list[Chunk], rels: list[Relationship]):
    """Recurse through AST looking for calls, JSX renders, and inheritance."""
    kind = node.kind()

    # --- function calls ---
    if kind == call_type:
        _extract_call(node, source_bytes, line_to_chunk, rels)

    # --- JSX component renders: <MyComponent /> ---
    elif is_jsx and kind in _JSX_COMPONENT_TYPES:
        _extract_jsx_render(node, source_bytes, line_to_chunk, rels)

    # --- class inheritance: class Foo(Bar) / class Foo extends Bar ---
    elif kind in ('class_definition', 'class_declaration'):
        _extract_inheritance(node, source_bytes, lang_name, chunks, rels)

    for i in range(node.child_count()):
        _find_all(node.child(i), source_bytes, line_to_chunk,
                  call_type, is_jsx, lang_name, chunks, rels)


def _extract_call(node, source_bytes, line_to_chunk, rels):
    """Extract a function call relationship."""
    if node.child_count() == 0:
        return

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


def _extract_jsx_render(node, source_bytes, line_to_chunk, rels):
    """Extract JSX component render: <MyComponent /> → 'renders' edge."""
    if node.child_count() == 0:
        return

    # first child after '<' is the component name
    for i in range(node.child_count()):
        child = node.child(i)
        if child.kind() == 'identifier':
            name = source_bytes[
                child.start_byte():child.end_byte()
            ].decode('utf-8', errors='ignore')

            # only track PascalCase names (React components), not html tags
            if name and name[0].isupper() and name.isidentifier():
                render_line = node.start_position().row
                caller_id = line_to_chunk.get(render_line)
                if caller_id:
                    rels.append(Relationship(
                        from_symbol_id=caller_id,
                        to_symbol_name=name,
                        rel_type='renders'
                    ))
            break


def _extract_inheritance(node, source_bytes, lang_name, chunks, rels):
    """Extract class inheritance: class Foo(Bar) → 'extends' edge."""
    # find which chunk this class belongs to
    class_line = node.start_position().row
    class_chunk_id = None
    for chunk in chunks:
        if chunk.start_line <= class_line <= chunk.end_line:
            class_chunk_id = chunk.id
            break

    if not class_chunk_id:
        return

    if lang_name == 'python':
        # class Foo(Bar, Baz): → argument_list has identifiers
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() == 'argument_list':
                for j in range(child.child_count()):
                    arg = child.child(j)
                    if arg.kind() == 'identifier':
                        parent_name = source_bytes[
                            arg.start_byte():arg.end_byte()
                        ].decode('utf-8', errors='ignore')
                        if parent_name and parent_name.isidentifier():
                            rels.append(Relationship(
                                from_symbol_id=class_chunk_id,
                                to_symbol_name=parent_name,
                                rel_type='extends'
                            ))

    else:
        # JS/TS/Java: look for extends_clause or implements_clause
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() in ('extends_clause', 'implements_clause',
                                'superclass', 'class_heritage'):
                for j in range(child.child_count()):
                    ident = child.child(j)
                    if ident.kind() in ('identifier', 'type_identifier'):
                        parent_name = source_bytes[
                            ident.start_byte():ident.end_byte()
                        ].decode('utf-8', errors='ignore')
                        if parent_name and parent_name.isidentifier():
                            rels.append(Relationship(
                                from_symbol_id=class_chunk_id,
                                to_symbol_name=parent_name,
                                rel_type='extends'
                            ))
