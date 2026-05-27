"""
Import relationship extraction using tree-sitter.

Walks the AST to find import/require/use statements and produces
structured ImportRelationship objects. These get stored in the graph
DB and enable import-aware blast radius, dependency analysis, and
circular dependency detection.
"""
from dataclasses import dataclass, field
from pathlib import Path
from .ast_chunker import EXTENSION_MAP


@dataclass
class ImportRelationship:
    file: str               # the file doing the importing
    module: str             # what's being imported ("config", "react", "./utils")
    names: list[str] = field(default_factory=list)  # specific names imported
    is_relative: bool = False
    line: int = 0


# tree-sitter node types for imports, per language
_IMPORT_TYPES = {
    'python': ['import_statement', 'import_from_statement'],
    'javascript': ['import_statement'],
    'typescript': ['import_statement'],
    'tsx': ['import_statement'],
    'go': ['import_declaration'],
    'rust': ['use_declaration'],
    'java': ['import_declaration'],
    'ruby': [],       # require() handled via call detection
    'php': ['namespace_use_declaration'],
    'c_sharp': ['using_directive'],
    'cpp': ['preproc_include'],
    'c': ['preproc_include'],
}


def extract_imports(file_path: str) -> list[ImportRelationship]:
    """Find all import statements in a file."""
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    import_types = _IMPORT_TYPES.get(lang_name, [])
    if not import_types:
        return []

    try:
        from tree_sitter_language_pack import get_parser
        source_bytes = path.read_bytes()
        parser = get_parser(lang_name)
        tree = parser.parse(source_bytes.decode('utf-8', errors='ignore'))
    except Exception:
        return []

    results: list[ImportRelationship] = []
    _walk_imports(tree.root_node(), source_bytes, file_path, lang_name,
                  set(import_types), results)
    return results


def _walk_imports(node, source_bytes: bytes, file_path: str,
                  lang_name: str, import_types: set, results: list):
    """Recurse through AST looking for import nodes."""
    kind = node.kind()

    if kind in import_types:
        imp = _parse_import_node(node, source_bytes, file_path, lang_name)
        if imp:
            results.append(imp)
        return  # don't recurse into import nodes

    for i in range(node.child_count()):
        _walk_imports(node.child(i), source_bytes, file_path, lang_name,
                      import_types, results)


def _node_text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte():node.end_byte()].decode(
        'utf-8', errors='ignore')


def _parse_import_node(node, source_bytes: bytes, file_path: str,
                       lang_name: str) -> ImportRelationship | None:
    """Extract module and imported names from an import AST node."""
    kind = node.kind()
    line = node.start_position().row

    if lang_name == 'python':
        return _parse_python_import(node, source_bytes, file_path, kind, line)
    elif lang_name in ('javascript', 'typescript', 'tsx'):
        return _parse_js_import(node, source_bytes, file_path, line)
    elif lang_name == 'go':
        return _parse_go_import(node, source_bytes, file_path, line)
    elif lang_name == 'java':
        return _parse_java_import(node, source_bytes, file_path, line)
    elif lang_name in ('c', 'cpp'):
        return _parse_c_include(node, source_bytes, file_path, line)
    elif lang_name == 'rust':
        return _parse_rust_use(node, source_bytes, file_path, line)
    elif lang_name == 'c_sharp':
        return _parse_csharp_using(node, source_bytes, file_path, line)
    elif lang_name == 'php':
        return _parse_php_use(node, source_bytes, file_path, line)

    return None


def _parse_python_import(node, source_bytes, file_path, kind, line):
    """Parse `import foo` or `from foo import bar, baz`."""
    if kind == 'import_statement':
        # import foo / import foo.bar
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() == 'dotted_name':
                module = _node_text(child, source_bytes)
                return ImportRelationship(
                    file=file_path, module=module,
                    is_relative=False, line=line)

    elif kind == 'import_from_statement':
        # from foo import bar, baz
        module = None
        names = []
        for i in range(node.child_count()):
            child = node.child(i)
            if child.kind() == 'dotted_name' and module is None:
                module = _node_text(child, source_bytes)
            elif child.kind() == 'dotted_name' and module is not None:
                names.append(_node_text(child, source_bytes))
            elif child.kind() == 'relative_import':
                module = _node_text(child, source_bytes)

        if module:
            is_relative = module.startswith('.')
            return ImportRelationship(
                file=file_path, module=module, names=names,
                is_relative=is_relative, line=line)

    return None


def _parse_js_import(node, source_bytes, file_path, line):
    """Parse `import X from 'source'` or `import { X, Y } from 'source'`."""
    module = None
    names = []

    for i in range(node.child_count()):
        child = node.child(i)
        if child.kind() == 'string':
            # the source path — strip quotes
            module = _node_text(child, source_bytes).strip("'\"")
        elif child.kind() == 'import_clause':
            for j in range(child.child_count()):
                sub = child.child(j)
                if sub.kind() == 'identifier':
                    names.append(_node_text(sub, source_bytes))
                elif sub.kind() == 'named_imports':
                    for k in range(sub.child_count()):
                        spec = sub.child(k)
                        if spec.kind() == 'import_specifier':
                            name_node = spec.child_by_field_name('name')
                            if name_node:
                                names.append(_node_text(name_node, source_bytes))
                            elif spec.child_count() > 0:
                                names.append(_node_text(spec.child(0), source_bytes))

    if module:
        is_relative = module.startswith('.') or module.startswith('/')
        return ImportRelationship(
            file=file_path, module=module, names=names,
            is_relative=is_relative, line=line)

    return None


def _parse_go_import(node, source_bytes, file_path, line):
    """Parse Go import declarations."""
    for i in range(node.child_count()):
        child = node.child(i)
        if child.kind() == 'import_spec':
            path_node = child.child_by_field_name('path')
            if path_node:
                module = _node_text(path_node, source_bytes).strip('"')
                return ImportRelationship(
                    file=file_path, module=module, line=line)
        elif child.kind() == 'import_spec_list':
            # multi-import: import ( "foo" \n "bar" )
            # just grab the first one; caller iterates for rest
            for j in range(child.child_count()):
                spec = child.child(j)
                if spec.kind() == 'import_spec':
                    path_node = spec.child_by_field_name('path')
                    if path_node:
                        module = _node_text(path_node, source_bytes).strip('"')
                        return ImportRelationship(
                            file=file_path, module=module, line=line)
    return None


def _parse_java_import(node, source_bytes, file_path, line):
    """Parse Java import declarations."""
    text = _node_text(node, source_bytes)
    # "import com.example.Foo;" → "com.example.Foo"
    module = text.replace('import ', '').replace('static ', '').rstrip(';').strip()
    if module:
        return ImportRelationship(file=file_path, module=module, line=line)
    return None


def _parse_c_include(node, source_bytes, file_path, line):
    """Parse #include directives."""
    text = _node_text(node, source_bytes)
    # #include "foo.h" or #include <foo.h>
    for ch in ('"', '<'):
        if ch in text:
            end = '"' if ch == '"' else '>'
            start = text.index(ch) + 1
            end_idx = text.index(end, start)
            module = text[start:end_idx]
            return ImportRelationship(
                file=file_path, module=module,
                is_relative=(ch == '"'), line=line)
    return None


def _parse_rust_use(node, source_bytes, file_path, line):
    """Parse Rust use declarations."""
    text = _node_text(node, source_bytes)
    module = text.replace('use ', '').rstrip(';').strip()
    if '::' in module:
        module = module.split('::')[0]
    if module:
        return ImportRelationship(file=file_path, module=module, line=line)
    return None


def _parse_csharp_using(node, source_bytes, file_path, line):
    """Parse C# using directives."""
    text = _node_text(node, source_bytes)
    module = text.replace('using ', '').rstrip(';').strip()
    if module:
        return ImportRelationship(file=file_path, module=module, line=line)
    return None


def _parse_php_use(node, source_bytes, file_path, line):
    """Parse PHP use statements."""
    text = _node_text(node, source_bytes)
    module = text.replace('use ', '').rstrip(';').strip()
    if module:
        return ImportRelationship(file=file_path, module=module, line=line)
    return None


def resolve_import_to_file(module: str, source_file: str,
                           indexed_files: list[str]) -> str | None:
    """Try to map an import module path to an actual indexed file.
    Returns the file path if found, None if external/unresolvable."""
    # normalize module name to possible file stems
    candidates = []

    # "config" → could be config.py, config.js, config/index.js etc.
    clean = module.lstrip('.').replace('.', '/').replace('\\', '/')

    for f in indexed_files:
        normalized = f.replace('\\', '/')
        # exact stem match: "config" matches "*/config.py"
        stem = Path(normalized).stem
        if stem == clean.split('/')[-1]:
            candidates.append(f)
        # path match: "wards/services" matches "*/wards/services.py"
        elif clean in normalized:
            candidates.append(f)

    if not candidates:
        return None

    # prefer files closest to the source file
    source_dir = str(Path(source_file).parent)
    for c in candidates:
        if c.startswith(source_dir):
            return c

    return candidates[0]
