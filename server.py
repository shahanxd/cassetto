"""
Codebase Intelligence — MCP Server
FastMCP server exposing search and status tools to LLMs.

Run directly: python server.py
Register with Claude Code in ~/.claude/settings.json
"""
import os
from mcp.server.fastmcp import FastMCP
from embedder import embed_text, check_embedding_ready
from store import hybrid_search, get_indexed_files, get_sqlite_conn

PROJECT_ID = os.getenv("CI_PROJECT_ID", "default")

mcp = FastMCP("codebase-intelligence")


@mcp.tool()
def search_code(query: str, limit: int = 10) -> str:
    """
    Search the indexed codebase using hybrid BM25 + semantic search.
    Returns relevant code chunks with file locations and line numbers.
    Use this to find code related to a concept, feature, function name, or pattern.
    Works for both exact names ('validateUser') and semantic queries ('user authentication logic').
    """
    ok, msg = check_embedding_ready()
    if not ok:
        return f"ERROR: Embedding not available — {msg}"

    embedding = embed_text(query)
    results = hybrid_search(PROJECT_ID, query, embedding, limit=limit)

    if not results:
        return ("No results found. Has the codebase been indexed?\n"
                "Run: python indexer.py index /path/to/project --project <id>")

    parts = []
    for r in results:
        chunk_text = r.get('chunk', '')[:2000]
        parts.append(
            f"FILE: {r.get('file', '?')} (lines {r.get('start_line', '?')}"
            f"–{r.get('end_line', '?')})\n"
            f"SYMBOL: {r.get('symbol', '?')} ({r.get('language', '')})\n"
            f"```\n{chunk_text}\n```"
        )
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def get_index_status() -> str:
    """
    Check the status of the codebase index.
    Returns how many files are indexed, total chunks, and project ID.
    Call this if you suspect the index might be out of date.
    """
    files = get_indexed_files(PROJECT_ID)
    conn = get_sqlite_conn(PROJECT_ID)
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    return (
        f"Index status:\n"
        f"- {len(files)} files indexed\n"
        f"- {chunk_count} total chunks\n"
        f"- Project: {PROJECT_ID}"
    )


if __name__ == "__main__":
    mcp.run()
