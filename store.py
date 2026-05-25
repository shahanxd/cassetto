"""
Dual-store for code chunks: LanceDB (vectors) + SQLite FTS5 (keyword search).

Both stores are kept in sync so we can combine them with Reciprocal Rank Fusion
at query time — you get the best of semantic similarity AND exact keyword matching.
"""
import sqlite3
import time
import lancedb
from pathlib import Path
from config import DATA_DIR


def get_project_dir(project_id: str) -> Path:
    d = DATA_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── LanceDB (vector search) ───────────────────────────────────

def _get_lance_db(project_id: str):
    return lancedb.connect(str(get_project_dir(project_id) / "vectors"))


def get_lance_table(project_id: str):
    """Open the chunks table, or None if it hasn't been created yet."""
    db = _get_lance_db(project_id)
    if "chunks" in db.table_names():
        return db.open_table("chunks")
    return None


# ── SQLite (BM25 keyword search + file metadata) ──────────────

def get_sqlite_conn(project_id: str) -> sqlite3.Connection:
    """Open SQLite with FTS5 and file tracking tables."""
    db_path = str(get_project_dir(project_id) / "index.db")
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            id, symbol, chunk, file, start_line, end_line,
            language, ast_hash, symbol_type,
            tokenize='porter unicode61'
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            last_modified REAL,
            last_indexed REAL,
            file_hash TEXT,
            symbol_count INTEGER DEFAULT 0,
            error TEXT
        )
    """)

    conn.commit()
    return conn


# ── writing chunks to both stores ─────────────────────────────

def store_chunks(project_id: str, chunks: list, embeddings: list[list[float]]):
    """Write chunks to LanceDB + SQLite in one go. Must stay in sync."""
    db = _get_lance_db(project_id)
    conn = get_sqlite_conn(project_id)

    records = []
    for chunk, emb in zip(chunks, embeddings):
        records.append({
            "id": chunk.id,
            "file": chunk.file,
            "symbol": chunk.symbol,
            "symbol_type": chunk.symbol_type,
            "chunk": chunk.chunk,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "language": chunk.language,
            "ast_hash": chunk.ast_hash,
            "pagerank_score": 0.0,
            "stale": False,
            "vector": emb,
        })

    if "chunks" in db.table_names():
        db.open_table("chunks").add(records)
    else:
        db.create_table("chunks", records)

    # FTS5 doesn't support INSERT OR REPLACE — need to delete first then insert.
    # we already call delete_file_chunks before store_chunks, so these are clean inserts.
    for chunk in chunks:
        conn.execute("""
            INSERT INTO chunks_fts
            (id, symbol, chunk, file, start_line, end_line,
             language, ast_hash, symbol_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk.id, chunk.symbol, chunk.chunk, chunk.file,
            str(chunk.start_line), str(chunk.end_line), chunk.language,
            chunk.ast_hash, chunk.symbol_type,
        ))

    conn.commit()


# ── search ─────────────────────────────────────────────────────

def search_vector(project_id: str, embedding: list[float], limit: int = 20) -> list[dict]:
    """Dense vector search — finds semantically similar code."""
    table = get_lance_table(project_id)
    if not table:
        return []
    return table.search(embedding).limit(limit).to_list()


def search_bm25(project_id: str, query: str, limit: int = 20) -> list[dict]:
    """BM25 keyword search — finds exact name matches and literal strings."""
    conn = get_sqlite_conn(project_id)
    try:
        rows = conn.execute("""
            SELECT id, symbol, chunk, file, start_line, end_line,
                   language, rank AS bm25_score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
    except Exception:
        # FTS5 MATCH can choke on weird query syntax, just return empty
        return []

    cols = ["id", "symbol", "chunk", "file", "start_line", "end_line",
            "language", "bm25_score"]
    return [dict(zip(cols, row)) for row in rows]


def hybrid_search(project_id: str, query: str, embedding: list[float],
                  limit: int = 10) -> list[dict]:
    """
    Combine vector + BM25 results with Reciprocal Rank Fusion.
    Each result gets score = sum of 1/(rank + 60) across both lists.
    This way a result that's top-5 in both lists beats one that's #1 in
    just one list.
    """
    k = 60  # standard RRF constant

    vector_results = search_vector(project_id, embedding, limit=limit * 2)
    bm25_results = search_bm25(project_id, query, limit=limit * 2)

    scores: dict[str, float] = {}
    result_map: dict[str, dict] = {}

    for rank, result in enumerate(vector_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        result_map[rid] = result

    for rank, result in enumerate(bm25_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        if rid not in result_map:
            result_map[rid] = result

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [result_map[rid] for rid in sorted_ids[:limit]]


# ── delete + metadata helpers ──────────────────────────────────

def delete_file_chunks(project_id: str, file_path: str):
    """Remove all chunks for a file from both stores."""
    table = get_lance_table(project_id)
    if table:
        try:
            # lance uses SQL-like filter syntax. need to escape single quotes
            # in file paths to avoid injection (e.g. paths with apostrophes).
            safe_path = file_path.replace("'", "''")
            table.delete(f"file = '{safe_path}'")
        except Exception:
            pass

    conn = get_sqlite_conn(project_id)
    conn.execute("DELETE FROM chunks_fts WHERE file = ?", (file_path,))
    conn.commit()


def get_indexed_files(project_id: str) -> list[str]:
    conn = get_sqlite_conn(project_id)
    rows = conn.execute("SELECT DISTINCT file FROM chunks_fts").fetchall()
    return [r[0] for r in rows]


def get_chunks_for_file(project_id: str, file_path: str) -> list[dict]:
    """Fetch stored chunks for diffing against freshly parsed ones."""
    conn = get_sqlite_conn(project_id)
    rows = conn.execute(
        "SELECT id, symbol, ast_hash FROM chunks_fts WHERE file = ?",
        (file_path,)
    ).fetchall()
    return [{"id": r[0], "symbol": r[1], "ast_hash": r[2]} for r in rows]


def update_file_metadata(project_id: str, file_path: str,
                         last_modified: float, file_hash: str,
                         symbol_count: int, error: str | None = None):
    conn = get_sqlite_conn(project_id)
    conn.execute("""
        INSERT OR REPLACE INTO files
        (path, last_modified, last_indexed, file_hash, symbol_count, error)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_path, last_modified, time.time(), file_hash, symbol_count, error))
    conn.commit()
