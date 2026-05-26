"""
Graph database for call graph + imports + git intel, stored in DuckDB.

Tables:
  - symbols: every function/class we found during indexing
  - relationships: "X calls Y", "X extends Y", "X renders Y" edges
  - imports: module import relationships between files
  - git_churn: file change frequency from git history
  - git_coupling: files that frequently change together

On top of this we compute PageRank (via networkx) to rank symbol importance.
We also support blast radius queries, dead code detection, cycle detection,
and import-aware dependency analysis.
"""
import hashlib
import json
import duckdb
from pathlib import Path
from config import DATA_DIR


def get_conn(project_id: str) -> duckdb.DuckDBPyConnection:
    db_path = str(DATA_DIR / project_id / "graph.duckdb")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    _setup(conn)
    return conn


def _setup(conn: duckdb.DuckDBPyConnection):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS symbols (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            file VARCHAR NOT NULL,
            symbol_type VARCHAR,
            start_line INTEGER,
            end_line INTEGER,
            pagerank_score DOUBLE DEFAULT 0.0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id VARCHAR PRIMARY KEY,
            from_id VARCHAR NOT NULL,
            to_id VARCHAR NOT NULL,
            rel_type VARCHAR NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS imports (
            id VARCHAR PRIMARY KEY,
            file VARCHAR NOT NULL,
            module VARCHAR NOT NULL,
            resolved_file VARCHAR,
            names TEXT,
            is_external BOOLEAN DEFAULT FALSE,
            line INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS git_churn (
            file VARCHAR PRIMARY KEY,
            change_count INTEGER DEFAULT 0,
            last_modified TEXT,
            authors TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS git_coupling (
            file_a VARCHAR,
            file_b VARCHAR,
            co_change_count INTEGER DEFAULT 0,
            PRIMARY KEY (file_a, file_b)
        )
    """)


# ── writes ─────────────────────────────────────────────────────

def upsert_symbol(conn: duckdb.DuckDBPyConnection, chunk):
    conn.execute("""
        INSERT OR REPLACE INTO symbols (id, name, file, symbol_type, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (chunk.id, chunk.symbol, chunk.file, chunk.symbol_type,
          chunk.start_line, chunk.end_line))


def upsert_relationship(conn: duckdb.DuckDBPyConnection,
                         from_id: str, to_id: str, rel_type: str):
    # deterministic ID from the edge triple so we don't insert duplicates
    rel_id = hashlib.sha256(
        f"{from_id}:{to_id}:{rel_type}".encode()
    ).hexdigest()[:16]
    conn.execute("""
        INSERT OR IGNORE INTO relationships (id, from_id, to_id, rel_type)
        VALUES (?, ?, ?, ?)
    """, (rel_id, from_id, to_id, rel_type))


def upsert_import(conn: duckdb.DuckDBPyConnection, imp):
    """Store an import relationship from import_extractor."""
    imp_id = hashlib.sha256(
        f"{imp.file}:{imp.module}:{imp.line}".encode()
    ).hexdigest()[:16]
    conn.execute("""
        INSERT OR REPLACE INTO imports (id, file, module, names, is_external, line)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (imp_id, imp.file, imp.module,
          json.dumps(imp.names) if imp.names else '[]',
          not imp.is_relative, imp.line))


def update_import_resolved(conn: duckdb.DuckDBPyConnection,
                            imp_id: str, resolved_file: str):
    """Set the resolved_file for an import after resolution pass."""
    conn.execute("""
        UPDATE imports SET resolved_file = ? WHERE id = ?
    """, (resolved_file, imp_id))


def store_git_churn(conn: duckdb.DuckDBPyConnection, churn_data: list[dict]):
    """Store file churn data from git analysis."""
    for item in churn_data:
        conn.execute("""
            INSERT OR REPLACE INTO git_churn (file, change_count)
            VALUES (?, ?)
        """, (item['file'], item['change_count']))


def store_git_coupling(conn: duckdb.DuckDBPyConnection,
                        coupling_data: list[dict]):
    """Store change coupling data from git analysis."""
    for item in coupling_data:
        conn.execute("""
            INSERT OR REPLACE INTO git_coupling (file_a, file_b, co_change_count)
            VALUES (?, ?, ?)
        """, (item['file_a'], item['file_b'], item['co_changes']))


def delete_file_symbols(conn: duckdb.DuckDBPyConnection, file_path: str):
    """Nuke all symbols + their edges for a file (used before re-indexing it)."""
    ids = conn.execute(
        "SELECT id FROM symbols WHERE file = ?", (file_path,)
    ).fetchall()
    id_list = [r[0] for r in ids]

    if id_list:
        placeholders = ','.join(['?'] * len(id_list))
        conn.execute(
            f"DELETE FROM relationships WHERE from_id IN ({placeholders}) "
            f"OR to_id IN ({placeholders})",
            id_list + id_list
        )

    conn.execute("DELETE FROM symbols WHERE file = ?", (file_path,))


def delete_file_imports(conn: duckdb.DuckDBPyConnection, file_path: str):
    """Remove all imports for a file."""
    conn.execute("DELETE FROM imports WHERE file = ?", (file_path,))


def resolve_symbol_name(conn: duckdb.DuckDBPyConnection,
                         name: str) -> str | None:
    """Look up a symbol ID by name. If there are multiple with the same
    name (common for 'main', '__init__', etc) we just grab the first one."""
    result = conn.execute(
        "SELECT id FROM symbols WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    return result[0] if result else None


# ── queries ────────────────────────────────────────────────────

def get_call_graph(conn: duckdb.DuckDBPyConnection,
                    symbol_name: str) -> dict:
    """Who calls this, and what does it call."""
    callers = conn.execute("""
        SELECT s.name, s.file, s.start_line
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE t.name = ? AND r.rel_type IN ('calls', 'renders')
        LIMIT 25
    """, (symbol_name,)).fetchall()

    callees = conn.execute("""
        SELECT t.name, t.file, t.start_line
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE s.name = ? AND r.rel_type IN ('calls', 'renders')
        LIMIT 25
    """, (symbol_name,)).fetchall()

    return {
        "symbol": symbol_name,
        "called_by": [{"name": r[0], "file": r[1], "line": r[2]}
                      for r in callers],
        "calls": [{"name": r[0], "file": r[1], "line": r[2]}
                  for r in callees],
    }


def get_blast_radius(conn: duckdb.DuckDBPyConnection,
                      symbol_name: str, max_depth: int = 3) -> dict:
    """
    The "what breaks if I touch this?" query.
    Walks the call graph backwards recursively: who calls me, who calls
    them, etc. up to max_depth hops. Includes 'calls', 'renders', 'extends'.
    """
    dependents = conn.execute("""
        WITH RECURSIVE deps AS (
            SELECT r.from_id AS dep_id, 1 AS depth
            FROM relationships r
            JOIN symbols s ON r.to_id = s.id
            WHERE s.name = ? AND r.rel_type IN ('calls', 'renders', 'extends')

            UNION ALL

            SELECT r.from_id, deps.depth + 1
            FROM relationships r
            JOIN deps ON r.to_id = deps.dep_id
            WHERE deps.depth < ?
        )
        SELECT DISTINCT s.name, s.file, MIN(deps.depth) AS depth
        FROM deps
        JOIN symbols s ON deps.dep_id = s.id
        GROUP BY s.name, s.file
        ORDER BY depth
        LIMIT 50
    """, (symbol_name, max_depth)).fetchall()

    return {
        "symbol": symbol_name,
        "blast_radius": [
            {"name": r[0], "file": r[1], "depth": r[2]} for r in dependents
        ],
        "affected_count": len(dependents)
    }


def get_dead_code(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Functions nothing calls. Excludes obvious entry points, tests,
    and overridden methods (extends relationships)."""
    results = conn.execute("""
        SELECT s.name, s.file, s.start_line
        FROM symbols s
        LEFT JOIN relationships r ON r.to_id = s.id
            AND r.rel_type IN ('calls', 'renders', 'extends')
        WHERE r.to_id IS NULL
          AND s.symbol_type IN ('function_definition', 'function_declaration',
                                 'method_definition', 'method_declaration',
                                 'decorated_definition', 'arrow_function')
          AND s.name NOT IN ('main', '__init__', 'setup', 'teardown',
                              'index', 'handler', 'middleware',
                              'module_level', 'render', 'constructor')
          AND s.name NOT LIKE 'test_%'
          AND s.name NOT LIKE '%_test'
          AND s.file NOT LIKE '%test%'
        LIMIT 100
    """).fetchall()
    return [{"name": r[0], "file": r[1], "line": r[2]} for r in results]


def find_references(conn: duckdb.DuckDBPyConnection,
                     symbol_name: str) -> list[dict]:
    """Find all usages of a symbol — everything that calls/renders/extends it."""
    refs = conn.execute("""
        SELECT s.name, s.file, s.start_line, r.rel_type
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE t.name = ?
        ORDER BY r.rel_type, s.file
        LIMIT 50
    """, (symbol_name,)).fetchall()

    return [{"name": r[0], "file": r[1], "line": r[2], "type": r[3]}
            for r in refs]


def goto_definition(conn: duckdb.DuckDBPyConnection,
                     symbol_name: str) -> dict | None:
    """Find where a symbol is defined."""
    result = conn.execute("""
        SELECT name, file, symbol_type, start_line, end_line
        FROM symbols WHERE name = ?
        LIMIT 5
    """, (symbol_name,)).fetchall()

    if not result:
        return None

    return {
        "definitions": [
            {"name": r[0], "file": r[1], "type": r[2],
             "start_line": r[3], "end_line": r[4]}
            for r in result
        ]
    }


def find_implementations(conn: duckdb.DuckDBPyConnection,
                          class_name: str) -> list[dict]:
    """Find all classes that extend/implement a given class/interface."""
    results = conn.execute("""
        SELECT s.name, s.file, s.start_line, s.symbol_type
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE t.name = ? AND r.rel_type = 'extends'
        LIMIT 50
    """, (class_name,)).fetchall()

    return [{"name": r[0], "file": r[1], "line": r[2], "type": r[3]}
            for r in results]


def get_symbol_detail(conn: duckdb.DuckDBPyConnection,
                       symbol_name: str) -> dict:
    """Comprehensive symbol info: definition + callers + callees + hierarchy."""
    defn = goto_definition(conn, symbol_name)
    graph = get_call_graph(conn, symbol_name)
    refs = find_references(conn, symbol_name)
    impls = find_implementations(conn, symbol_name)

    # pagerank
    pr = conn.execute(
        "SELECT pagerank_score FROM symbols WHERE name = ? LIMIT 1",
        (symbol_name,)
    ).fetchone()

    return {
        "symbol": symbol_name,
        "definition": defn,
        "called_by": graph["called_by"],
        "calls": graph["calls"],
        "references": refs,
        "implementations": impls,
        "pagerank": round(pr[0], 6) if pr else 0.0,
    }


def get_imports_for_file(conn: duckdb.DuckDBPyConnection,
                          file_path: str) -> list[dict]:
    """What does this file import?"""
    results = conn.execute("""
        SELECT module, names, resolved_file, is_external, line
        FROM imports WHERE file = ?
        ORDER BY line
    """, (file_path,)).fetchall()

    return [{"module": r[0], "names": json.loads(r[1]) if r[1] else [],
             "resolved_file": r[2], "is_external": r[3], "line": r[4]}
            for r in results]


def get_importers_of(conn: duckdb.DuckDBPyConnection,
                      file_path: str) -> list[dict]:
    """What files import this file/module?"""
    # match by resolved_file or by module name substring
    module_stem = Path(file_path).stem
    results = conn.execute("""
        SELECT DISTINCT file, module, line
        FROM imports
        WHERE resolved_file = ? OR module LIKE ?
        ORDER BY file
        LIMIT 50
    """, (file_path, f"%{module_stem}%")).fetchall()

    return [{"file": r[0], "module": r[1], "line": r[2]}
            for r in results]


def get_graph_neighbors(conn: duckdb.DuckDBPyConnection,
                         symbol_name: str) -> set[str]:
    """Get IDs of all symbols connected to this one (callers + callees)."""
    rows = conn.execute("""
        SELECT s.id FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE t.name = ?
        UNION
        SELECT t.id FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE s.name = ?
    """, (symbol_name, symbol_name)).fetchall()

    return {r[0] for r in rows}


def find_cycles(conn: duckdb.DuckDBPyConnection) -> list[list[str]]:
    """Detect circular dependencies in the import graph."""
    import networkx as nx

    # build import graph from resolved imports
    edges = conn.execute("""
        SELECT DISTINCT file, resolved_file
        FROM imports
        WHERE resolved_file IS NOT NULL
    """).fetchall()

    G = nx.DiGraph()
    for src, dst in edges:
        # normalize to basenames for readability
        G.add_edge(Path(src).name, Path(dst).name)

    try:
        cycles = list(nx.simple_cycles(G))
        # sort by length, limit to 20
        cycles.sort(key=len)
        return cycles[:20]
    except Exception:
        return []


def get_change_coupling_for_file(conn: duckdb.DuckDBPyConnection,
                                  file_path: str) -> list[dict]:
    """Files that frequently change together with this file."""
    # normalize to relative-ish path
    stem = Path(file_path).name
    results = conn.execute("""
        SELECT file_a, file_b, co_change_count
        FROM git_coupling
        WHERE file_a LIKE ? OR file_b LIKE ?
        ORDER BY co_change_count DESC
        LIMIT 20
    """, (f"%{stem}%", f"%{stem}%")).fetchall()

    return [{"file_a": r[0], "file_b": r[1], "co_changes": r[2]}
            for r in results]


# ── pagerank ───────────────────────────────────────────────────

def compute_pagerank(conn: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Build a networkx graph from all edges and run PageRank."""
    import networkx as nx

    edges = conn.execute(
        "SELECT from_id, to_id FROM relationships"
    ).fetchall()

    G = nx.DiGraph()
    G.add_edges_from(edges)

    if not G.nodes:
        return {}

    return nx.pagerank(G, alpha=0.85, max_iter=100)


def update_pagerank_scores(conn: duckdb.DuckDBPyConnection):
    """Recompute PageRank and write scores back to the symbols table."""
    scores = compute_pagerank(conn)
    if not scores:
        return 0
    # batch update via executemany instead of one query per symbol
    conn.executemany(
        "UPDATE symbols SET pagerank_score = ? WHERE id = ?",
        [(score, sid) for sid, score in scores.items()]
    )
    return len(scores)
