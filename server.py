"""
Codebase Intelligence — MCP Server
FastMCP server exposing search, graph, and status tools to LLMs.

Run directly: python server.py
Register in Antigravity's mcp_config.json
"""
import os
import json
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


# ── Stage 3: Graph tools ──────────────────────────────────────

@mcp.tool()
def get_call_graph_tool(symbol_name: str) -> str:
    """
    Get the call graph for a specific function or class.
    Shows what functions call it (callers) and what it calls (callees).
    Use this to understand the context of a function before modifying it.
    """
    from graph_store import get_conn, get_call_graph
    conn = get_conn(PROJECT_ID)
    result = get_call_graph(conn, symbol_name)
    conn.close()
    if not result["called_by"] and not result["calls"]:
        return (f"No call graph data found for '{symbol_name}'. "
                "The symbol may not be indexed or has no known callers/callees.")
    return json.dumps(result, indent=2)


@mcp.tool()
def blast_radius(symbol_name: str) -> str:
    """
    Find everything that depends on this symbol — what breaks if you change it.
    Returns all functions and files that transitively call this symbol, up to 3 hops away.
    ALWAYS call this before modifying a function to understand the impact.
    """
    from graph_store import get_conn, get_blast_radius
    conn = get_conn(PROJECT_ID)
    result = get_blast_radius(conn, symbol_name)
    conn.close()
    if result["affected_count"] == 0:
        return f"'{symbol_name}' has no known dependents. Safe to modify (or not indexed yet)."
    return json.dumps(result, indent=2)


@mcp.tool()
def find_dead_code() -> str:
    """
    Find functions that nothing calls — potential dead code to remove.
    Excludes common entry points (main, __init__, test_ functions, route handlers).
    """
    from graph_store import get_conn, get_dead_code
    conn = get_conn(PROJECT_ID)
    results = get_dead_code(conn)
    conn.close()
    if not results:
        return "No obvious dead code found."
    lines = [f"- {r['name']} ({r['file']}:{r['line']})" for r in results[:20]]
    return f"Potential dead code ({len(results)} functions):\n" + "\n".join(lines)


@mcp.tool()
def get_repo_map(max_symbols: int = 50) -> str:
    """
    Get a PageRank-ranked map of the most important symbols in the codebase.
    Higher-ranked symbols are referenced by more code and are more central to the architecture.
    Call this at the start of a session to orient yourself in an unfamiliar codebase.
    """
    from graph_store import get_conn
    conn = get_conn(PROJECT_ID)
    results = conn.execute("""
        SELECT name, file, symbol_type, pagerank_score
        FROM symbols
        ORDER BY pagerank_score DESC
        LIMIT ?
    """, (max_symbols,)).fetchall()
    conn.close()
    if not results:
        return "No symbols indexed yet."
    lines = [f"- {r[0]} ({r[2]}) in {r[1]} [rank: {r[3]:.4f}]" for r in results]
    return "Top symbols by importance (PageRank):\n" + "\n".join(lines)


if __name__ == "__main__":
    mcp.run()

