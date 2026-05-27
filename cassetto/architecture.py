"""
Architecture intelligence — framework detection, entry points, layer analysis.

Auto-detects what frameworks a project uses, where execution starts,
and how the codebase is layered (controllers → services → models).
"""
import re
import json
from pathlib import Path
from collections import defaultdict


# ── Framework Detection ────────────────────────────────────────

FRAMEWORK_SIGNATURES = {
    'django': {
        'files': {'manage.py', 'wsgi.py', 'asgi.py'},
        'dirs': set(),
        'imports': {'django'},
    },
    'flask': {
        'files': set(),
        'dirs': set(),
        'imports': {'flask'},
    },
    'fastapi': {
        'files': set(),
        'dirs': set(),
        'imports': {'fastapi'},
    },
    'react': {
        'files': set(),
        'dirs': set(),
        'imports': {'react'},
        'package_deps': {'react'},
    },
    'vue': {
        'files': set(),
        'dirs': set(),
        'imports': {'vue'},
        'package_deps': {'vue'},
    },
    'nextjs': {
        'files': {'next.config.js', 'next.config.mjs', 'next.config.ts'},
        'dirs': set(),
        'imports': set(),
        'package_deps': {'next'},
    },
    'express': {
        'files': set(),
        'dirs': set(),
        'imports': {'express'},
        'package_deps': {'express'},
    },
    'spring': {
        'files': {'pom.xml', 'build.gradle'},
        'dirs': set(),
        'imports': {'org.springframework'},
    },
    'rails': {
        'files': {'Gemfile', 'Rakefile'},
        'dirs': {'config'},
        'imports': set(),
    },
}


def detect_frameworks(project_root: str,
                       indexed_files: list[str] = None) -> list[dict]:
    """Detect frameworks from file patterns + import analysis."""
    root = Path(project_root)
    detected = []

    # check for package.json deps
    pkg_deps = set()
    pkg_path = root / 'package.json'
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text(errors='ignore'))
            all_deps = {}
            all_deps.update(pkg.get('dependencies', {}))
            all_deps.update(pkg.get('devDependencies', {}))
            pkg_deps = set(all_deps.keys())
        except Exception:
            pass

    # collect all file basenames in the project
    all_files = set()
    for f in (indexed_files or []):
        all_files.add(Path(f).name)
        # also add relative paths
        try:
            all_files.add(str(Path(f).relative_to(root)))
        except ValueError:
            pass

    for framework, sigs in FRAMEWORK_SIGNATURES.items():
        confidence = 0.0
        reasons = []

        # file signature matches
        file_matches = sigs['files'] & all_files
        if file_matches:
            confidence += 0.6
            reasons.append(f"files: {', '.join(file_matches)}")

        # package.json dependency matches
        if 'package_deps' in sigs:
            dep_matches = sigs['package_deps'] & pkg_deps
            if dep_matches:
                confidence += 0.8
                reasons.append(f"package.json: {', '.join(dep_matches)}")

        # import matches — check actual indexed files for import patterns
        if sigs.get('imports') and indexed_files:
            for f in indexed_files[:200]:  # don't scan all files
                try:
                    content = Path(f).read_text(errors='ignore')[:2000]
                    for imp_name in sigs['imports']:
                        if imp_name in content:
                            confidence += 0.5
                            reasons.append(f"import: {imp_name}")
                            break
                except Exception:
                    pass
                if confidence > 0:
                    break

        if confidence >= 0.5:
            detected.append({
                "framework": framework,
                "confidence": min(confidence, 1.0),
                "evidence": reasons,
            })

    detected.sort(key=lambda x: x['confidence'], reverse=True)
    return detected


# ── Entry Point Detection ──────────────────────────────────────

_ENTRY_PATTERNS = {
    'python': {
        'cli_main': re.compile(r'if\s+__name__\s*==\s*["\']__main__["\']'),
        'django_urls': re.compile(r'urlpatterns\s*='),
        'flask_route': re.compile(r'@app\.(get|post|put|delete|route)\s*\('),
        'fastapi_route': re.compile(r'@(app|router)\.(get|post|put|delete)\s*\('),
        'click_command': re.compile(r'@click\.(command|group)'),
        'pytest_fixture': re.compile(r'@pytest\.fixture'),
    },
    'javascript': {
        'express_route': re.compile(r'(app|router)\.(get|post|put|delete|use)\s*\('),
        'react_root': re.compile(r'(createRoot|ReactDOM\.render)'),
        'default_export': re.compile(r'export\s+default\s+function'),
        'module_export': re.compile(r'module\.exports'),
    },
    'typescript': {
        'express_route': re.compile(r'(app|router)\.(get|post|put|delete|use)\s*\('),
        'react_root': re.compile(r'(createRoot|ReactDOM\.render)'),
        'default_export': re.compile(r'export\s+default\s+function'),
    },
}
# TSX uses the same patterns as typescript
_ENTRY_PATTERNS['tsx'] = _ENTRY_PATTERNS['typescript']


def find_entry_points(project_root: str,
                       indexed_files: list[str]) -> list[dict]:
    """Detect all entry points: routes, CLI commands, main functions, tests."""
    from .ast_chunker import EXTENSION_MAP

    entries = []
    for f in indexed_files:
        ext = Path(f).suffix
        lang = EXTENSION_MAP.get(ext)
        if not lang:
            continue

        patterns = _ENTRY_PATTERNS.get(lang, {})
        if not patterns:
            continue

        try:
            content = Path(f).read_text(errors='ignore')[:5000]
        except Exception:
            continue

        for pattern_name, regex in patterns.items():
            match = regex.search(content)
            if match:
                try:
                    rel = str(Path(f).relative_to(project_root))
                except ValueError:
                    rel = f
                entries.append({
                    "file": rel,
                    "type": pattern_name,
                    "language": lang,
                    "line": content[:match.start()].count('\n'),
                })

        # test files
        name = Path(f).stem
        if name.startswith('test_') or name.endswith('_test') or \
           name.endswith('.spec') or name.endswith('.test'):
            try:
                rel = str(Path(f).relative_to(project_root))
            except ValueError:
                rel = f
            entries.append({
                "file": rel,
                "type": "test_file",
                "language": lang,
                "line": 0,
            })

    return entries


# ── Layer Detection ────────────────────────────────────────────

_LAYER_KEYWORDS = {
    'controllers': {'controller', 'controllers', 'views', 'view', 'routes',
                    'route', 'handlers', 'handler', 'endpoints', 'api'},
    'services': {'service', 'services', 'logic', 'business', 'usecase',
                 'usecases', 'interactors'},
    'models': {'model', 'models', 'entities', 'entity', 'schema', 'schemas',
               'types', 'interfaces'},
    'data': {'repository', 'repositories', 'dao', 'database', 'db', 'store',
             'storage', 'migration', 'migrations'},
    'utils': {'util', 'utils', 'helpers', 'helper', 'lib', 'libs', 'common',
              'shared', 'tools'},
    'config': {'config', 'configuration', 'settings', 'env', 'constants'},
    'tests': {'test', 'tests', 'spec', 'specs', '__tests__', 'testing'},
    'ui': {'components', 'component', 'pages', 'page', 'layouts', 'layout',
           'widgets', 'screens'},
}


def detect_layers(project_root: str,
                   indexed_files: list[str]) -> dict[str, list[str]]:
    """Classify files into architectural layers by directory name."""
    root = Path(project_root)
    layers: dict[str, list[str]] = defaultdict(list)

    for f in indexed_files:
        try:
            rel = Path(f).relative_to(root)
        except ValueError:
            continue

        parts = set(p.lower() for p in rel.parts[:-1])  # dir names only
        classified = False

        for layer, keywords in _LAYER_KEYWORDS.items():
            if parts & keywords:
                layers[layer].append(str(rel))
                classified = True
                break

        if not classified:
            layers['other'].append(str(rel))

    return dict(layers)


# ── Architecture Summary ──────────────────────────────────────

def generate_architecture_summary(project_root: str,
                                    indexed_files: list[str],
                                    graph_conn=None) -> dict:
    """
    Combine all intelligence into a structured codebase overview.
    """
    from collections import Counter
    from .ast_chunker import EXTENSION_MAP

    # language breakdown
    lang_counts: Counter = Counter()
    for f in indexed_files:
        ext = Path(f).suffix
        lang = EXTENSION_MAP.get(ext, 'other')
        lang_counts[lang] += 1

    # frameworks
    frameworks = detect_frameworks(project_root, indexed_files)

    # entry points
    entries = find_entry_points(project_root, indexed_files)

    # layers
    layers = detect_layers(project_root, indexed_files)

    # top symbols from PageRank
    top_symbols = []
    if graph_conn:
        try:
            rows = graph_conn.execute("""
                SELECT name, file, symbol_type, pagerank_score
                FROM symbols
                ORDER BY pagerank_score DESC
                LIMIT 10
            """).fetchall()
            top_symbols = [{"name": r[0], "file": r[1], "type": r[2],
                           "pagerank": round(r[3], 4)} for r in rows]
        except Exception:
            pass

    return {
        "file_count": len(indexed_files),
        "languages": dict(lang_counts.most_common()),
        "frameworks": frameworks,
        "entry_points": entries[:20],
        "layers": {k: len(v) for k, v in layers.items()},
        "top_symbols": top_symbols,
    }
