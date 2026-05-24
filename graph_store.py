"""
Codebase Intelligence — Graph Store (Stage 3)
DuckDB-backed call graph with PageRank scoring.

Stores:
  - symbols: every function/class extracted by AST chunker
  - relationships: calls/imports edges between symbols
  - pagerank_score: how central each symbol is in the codebase

Queries:
  - Call graph: who calls X, what does X call
  - Blast radius: what breaks if X changes (recursive traversal)
  - Dead code: functions nothing calls
  - Repo map: PageRank-ranked overview of most important symbols
"""
import hashlib
import duckdb
from pathlib import Path
from config import DATA_DIR


# ── Connection management ──────────────────────────────────────

def get_conn(project_id: str) -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB graph database for a project."""
    db_path = str(DATA_DIR / project_id / "graph.duckdb")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(db_path)
    _setup(conn)
    return conn


def _setup(conn: duckdb.DuckDBPyConnection):
    """Create tables if they don't exist."""
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


# ── Write operations ───────────────────────────────────────────

def upsert_symbol(conn: duckdb.DuckDBPyConnection, chunk):
    """Insert or update a symbol from an AST chunk."""
    conn.execute("""
        INSERT OR REPLACE INTO symbols (id, name, file, symbol_type, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (chunk.id, chunk.symbol, chunk.file, chunk.symbol_type,
          chunk.start_line, chunk.end_line))


def upsert_relationship(conn: duckdb.DuckDBPyConnection,
                         from_id: str, to_id: str, rel_type: str):
    """Insert a relationship edge (idempotent via hash-based ID)."""
    rel_id = hashlib.sha256(
        f"{from_id}:{to_id}:{rel_type}".encode()
    ).hexdigest()[:16]
    conn.execute("""
        INSERT OR IGNORE INTO relationships (id, from_id, to_id, rel_type)
        VALUES (?, ?, ?, ?)
    """, (rel_id, from_id, to_id, rel_type))


def delete_file_symbols(conn: duckdb.DuckDBPyConnection, file_path: str):
    """Remove all symbols and their relationships for a file."""
    # Get symbol IDs for this file
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


def resolve_symbol_name(conn: duckdb.DuckDBPyConnection,
                         name: str) -> str | None:
    """Look up a symbol ID by name. Returns first match or None."""
    result = conn.execute(
        "SELECT id FROM symbols WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    return result[0] if result else None


# ── Query operations ───────────────────────────────────────────

def get_call_graph(conn: duckdb.DuckDBPyConnection,
                    symbol_name: str) -> dict:
    """Who calls this symbol, and what does it call."""
    callers = conn.execute("""
        SELECT s.name, s.file, s.start_line
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE t.name = ? AND r.rel_type = 'calls'
        LIMIT 25
    """, (symbol_name,)).fetchall()

    callees = conn.execute("""
        SELECT t.name, t.file, t.start_line
        FROM relationships r
        JOIN symbols s ON r.from_id = s.id
        JOIN symbols t ON r.to_id = t.id
        WHERE s.name = ? AND r.rel_type = 'calls'
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
    Find everything that transitively depends on this symbol.
    Uses WITH RECURSIVE — the 'what breaks if I change X' query.
    """
    dependents = conn.execute("""
        WITH RECURSIVE deps AS (
            -- Base case: direct callers of the target symbol
            SELECT r.from_id AS dep_id, 1 AS depth
            FROM relationships r
            JOIN symbols s ON r.to_id = s.id
            WHERE s.name = ? AND r.rel_type = 'calls'

            UNION ALL

            -- Recursive case: callers of callers
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
    """Find functions that nothing calls (excluding common entry points)."""
    results = conn.execute("""
        SELECT s.name, s.file, s.start_line
        FROM symbols s
        LEFT JOIN relationships r ON r.to_id = s.id AND r.rel_type = 'calls'
        WHERE r.to_id IS NULL
          AND s.symbol_type IN ('function_definition', 'function_declaration',
                                 'method_definition', 'method_declaration',
                                 'decorated_definition')
          AND s.name NOT IN ('main', '__init__', 'setup', 'teardown',
                              'index', 'handler', 'middleware')
          AND s.name NOT LIKE 'test_%'
          AND s.name NOT LIKE '%_test'
        LIMIT 100
    """).fetchall()
    return [{"name": r[0], "file": r[1], "line": r[2]} for r in results]


# ── PageRank ───────────────────────────────────────────────────

def compute_pagerank(conn: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Compute PageRank over the call graph using NetworkX."""
    import networkx as nx

    edges = conn.execute(
        "SELECT from_id, to_id FROM relationships WHERE rel_type = 'calls'"
    ).fetchall()

    G = nx.DiGraph()
    G.add_edges_from(edges)

    if not G.nodes:
        return {}

    scores = nx.pagerank(G, alpha=0.85, max_iter=100)
    return scores


def update_pagerank_scores(conn: duckdb.DuckDBPyConnection):
    """Recompute and persist PageRank scores in the symbols table."""
    scores = compute_pagerank(conn)
    for symbol_id, score in scores.items():
        conn.execute(
            "UPDATE symbols SET pagerank_score = ? WHERE id = ?",
            (score, symbol_id)
        )
    return len(scores)
