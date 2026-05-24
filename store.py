"""
Codebase Intelligence — Dual Store
Stores code chunks in two places for hybrid search:
  - LanceDB: vector embeddings for semantic similarity
  - SQLite FTS5: BM25 keyword search for exact matches
Results are fused using Reciprocal Rank Fusion (RRF).
"""
import sqlite3
import lancedb
from pathlib import Path
from config import DATA_DIR


# ── Project directory helpers ──────────────────────────────────

def get_project_dir(project_id: str) -> Path:
    """Get or create the data directory for a project."""
    d = DATA_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── LanceDB (vector search) ───────────────────────────────────

def _get_lance_db(project_id: str):
    return lancedb.connect(str(get_project_dir(project_id) / "vectors"))


def get_lance_table(project_id: str):
    """Open the chunks table if it exists, else return None."""
    db = _get_lance_db(project_id)
    if "chunks" in db.table_names():
        return db.open_table("chunks")
    return None


# ── SQLite (BM25 + metadata) ──────────────────────────────────

def get_sqlite_conn(project_id: str) -> sqlite3.Connection:
    """Open SQLite connection with FTS5 and metadata tables initialized."""
    db_path = str(get_project_dir(project_id) / "index.db")
    conn = sqlite3.connect(db_path)

    # FTS5 virtual table for BM25 search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            id, symbol, chunk, file, start_line, end_line,
            language, ast_hash, symbol_type,
            tokenize='porter unicode61'
        )
    """)

    # File metadata table for tracking indexed files
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


# ── Store operations ───────────────────────────────────────────

def store_chunks(project_id: str, chunks: list, embeddings: list[list[float]]):
    """
    Store chunks in BOTH LanceDB (vectors) and SQLite (BM25).
    Both stores must stay in sync.
    """
    db = _get_lance_db(project_id)
    conn = get_sqlite_conn(project_id)

    # Build LanceDB records
    records = []
    for chunk, emb in zip(chunks, embeddings):
        records.append({
            "id": chunk.id,
            "file": chunk.file,
            "symbol": chunk.symbol,
            "symbol_type": getattr(chunk, 'symbol_type', 'unknown'),
            "chunk": chunk.chunk,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "language": chunk.language,
            "ast_hash": getattr(chunk, 'ast_hash', ''),
            "pagerank_score": 0.0,
            "stale": False,
            "vector": emb,
        })

    # LanceDB: create or append
    if "chunks" in db.table_names():
        db.open_table("chunks").add(records)
    else:
        db.create_table("chunks", records)

    # SQLite FTS5: insert each chunk
    for chunk in chunks:
        conn.execute("""
            INSERT OR REPLACE INTO chunks_fts
            (id, symbol, chunk, file, start_line, end_line,
             language, ast_hash, symbol_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chunk.id, chunk.symbol, chunk.chunk, chunk.file,
            str(chunk.start_line), str(chunk.end_line), chunk.language,
            getattr(chunk, 'ast_hash', ''), getattr(chunk, 'symbol_type', 'unknown'),
        ))

    conn.commit()


# ── Search operations ──────────────────────────────────────────

def search_vector(project_id: str, embedding: list[float], limit: int = 20) -> list[dict]:
    """Dense vector search via LanceDB."""
    table = get_lance_table(project_id)
    if not table:
        return []
    return table.search(embedding).limit(limit).to_list()


def search_bm25(project_id: str, query: str, limit: int = 20) -> list[dict]:
    """BM25 keyword search via SQLite FTS5."""
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
        # FTS5 MATCH can fail on some query syntax — return empty
        return []

    cols = ["id", "symbol", "chunk", "file", "start_line", "end_line",
            "language", "bm25_score"]
    return [dict(zip(cols, row)) for row in rows]


def hybrid_search(project_id: str, query: str, embedding: list[float],
                  limit: int = 10) -> list[dict]:
    """
    Combine BM25 and vector results using Reciprocal Rank Fusion.
    RRF score = sum of 1/(rank + k) across result lists, where k=60 (standard).
    Higher is better.
    """
    k = 60

    vector_results = search_vector(project_id, embedding, limit=limit * 2)
    bm25_results = search_bm25(project_id, query, limit=limit * 2)

    scores: dict[str, float] = {}
    result_map: dict[str, dict] = {}

    # Score vector results
    for rank, result in enumerate(vector_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        result_map[rid] = result

    # Score BM25 results
    for rank, result in enumerate(bm25_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        if rid not in result_map:
            result_map[rid] = result

    # Sort by fused score (highest first) and return top N
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [result_map[rid] for rid in sorted_ids[:limit]]


# ── Delete / query helpers ─────────────────────────────────────

def delete_file_chunks(project_id: str, file_path: str):
    """Remove all chunks for a file from BOTH stores."""
    # LanceDB
    table = get_lance_table(project_id)
    if table:
        try:
            table.delete(f"file = '{file_path}'")
        except Exception:
            pass  # Table may be empty or file not found

    # SQLite FTS5
    conn = get_sqlite_conn(project_id)
    conn.execute("DELETE FROM chunks_fts WHERE file = ?", (file_path,))
    conn.commit()


def get_indexed_files(project_id: str) -> list[str]:
    """Get list of all files currently in the index."""
    conn = get_sqlite_conn(project_id)
    rows = conn.execute("SELECT DISTINCT file FROM chunks_fts").fetchall()
    return [r[0] for r in rows]


def get_chunks_for_file(project_id: str, file_path: str) -> list[dict]:
    """Get stored chunks for a file (used for diffing in incremental updates)."""
    conn = get_sqlite_conn(project_id)
    rows = conn.execute(
        "SELECT id, symbol, ast_hash FROM chunks_fts WHERE file = ?",
        (file_path,)
    ).fetchall()
    return [{"id": r[0], "symbol": r[1], "ast_hash": r[2]} for r in rows]


def update_file_metadata(project_id: str, file_path: str,
                         last_modified: float, file_hash: str,
                         symbol_count: int, error: str | None = None):
    """Track indexing state for a file."""
    import time
    conn = get_sqlite_conn(project_id)
    conn.execute("""
        INSERT OR REPLACE INTO files
        (path, last_modified, last_indexed, file_hash, symbol_count, error)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_path, last_modified, time.time(), file_hash, symbol_count, error))
    conn.commit()
