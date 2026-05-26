"""
Cassetto — MCP server.
Exposes 18 tools: search, call graph, blast radius, dead code, repo map, status,
plus symbol intelligence, git intelligence, architecture intelligence, and more.
"""
import os
import json
from mcp.server.fastmcp import FastMCP
from embedder import embed_text, check_embedding_ready
from store import hybrid_search, get_indexed_files, get_sqlite_conn

PROJECT_ID = os.getenv("CASSETTO_PROJECT_ID", "default")

mcp = FastMCP("cassetto")


# ── Search ─────────────────────────────────────────────────────

@mcp.tool()
def search_code(query: str, limit: int = 10) -> str:
    """
    Search the indexed codebase using hybrid BM25 + semantic search with graph-aware reranking.
    Returns relevant code chunks with file locations and line numbers.
    Use this to find code related to a concept, feature, function name, or pattern.
    Works for both exact names ('validateUser') and semantic queries ('user authentication logic').
    """
    ok, msg = check_embedding_ready()
    if not ok:
        return f"ERROR: Embedding not available — {msg}"

    # get graph connection for graph-aware reranking
    graph_conn = None
    try:
        from graph_store import get_conn
        graph_conn = get_conn(PROJECT_ID)
    except Exception:
        pass

    embedding = embed_text(query)
    results = hybrid_search(PROJECT_ID, query, embedding, limit=limit,
                            graph_conn=graph_conn)

    if graph_conn:
        graph_conn.close()

    if not results:
        return ("No results found. Has the codebase been indexed?\n"
                "Run: cassetto index /path/to/project --project <id>")

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


# ── Status ─────────────────────────────────────────────────────

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

    # also check graph stats
    try:
        from graph_store import get_conn
        gc = get_conn(PROJECT_ID)
        sym_count = gc.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        rel_count = gc.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        imp_count = gc.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
        gc.close()
        graph_info = (f"\n- {sym_count} symbols in graph"
                      f"\n- {rel_count} relationships (calls/extends/renders)"
                      f"\n- {imp_count} import relationships")
    except Exception:
        graph_info = ""

    return (
        f"Index status:\n"
        f"- {len(files)} files indexed\n"
        f"- {chunk_count} total chunks"
        f"{graph_info}\n"
        f"- Project: {PROJECT_ID}"
    )


# ── Call Graph ─────────────────────────────────────────────────

@mcp.tool()
def get_call_graph_tool(symbol_name: str) -> str:
    """
    Get the call graph for a specific function or class.
    Shows what functions call it (callers) and what it calls (callees).
    Includes JSX component renders and inheritance relationships.
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


# ── Blast Radius ───────────────────────────────────────────────

@mcp.tool()
def blast_radius(symbol_name: str) -> str:
    """
    Find everything that depends on this symbol — what breaks if you change it.
    Returns all functions and files that transitively call, render, or extend
    this symbol, up to 3 hops away.
    ALWAYS call this before modifying a function to understand the impact.
    """
    from graph_store import get_conn, get_blast_radius
    conn = get_conn(PROJECT_ID)
    result = get_blast_radius(conn, symbol_name)
    conn.close()
    if result["affected_count"] == 0:
        return f"'{symbol_name}' has no known dependents. Safe to modify (or not indexed yet)."
    return json.dumps(result, indent=2)


# ── Dead Code ──────────────────────────────────────────────────

@mcp.tool()
def find_dead_code() -> str:
    """
    Find functions that nothing calls — potential dead code to remove.
    Excludes common entry points (main, __init__, test_ functions, route handlers).
    Also excludes overridden methods in class hierarchies.
    """
    from graph_store import get_conn, get_dead_code
    conn = get_conn(PROJECT_ID)
    results = get_dead_code(conn)
    conn.close()
    if not results:
        return "No obvious dead code found."
    lines = [f"- {r['name']} ({r['file']}:{r['line']})" for r in results[:20]]
    return f"Potential dead code ({len(results)} functions):\n" + "\n".join(lines)


# ── Repo Map ───────────────────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════
# v2 TOOLS
# ═══════════════════════════════════════════════════════════════


# ── Symbol Intelligence ───────────────────────────────────────

@mcp.tool()
def find_references(symbol_name: str) -> str:
    """
    Find all usages of a symbol across the codebase.
    Returns every file and line where this symbol is called, rendered (JSX), or extended.
    Use this to understand how widely used a function is before changing its signature.
    """
    from graph_store import get_conn, find_references as _find_refs
    conn = get_conn(PROJECT_ID)
    refs = _find_refs(conn, symbol_name)
    conn.close()
    if not refs:
        return f"No references found for '{symbol_name}'."
    lines = [f"- {r['name']} ({r['file']}:{r['line']}) [{r['type']}]" for r in refs]
    return f"References to '{symbol_name}' ({len(refs)} found):\n" + "\n".join(lines)


@mcp.tool()
def goto_definition(symbol_name: str) -> str:
    """
    Jump to where a symbol is defined.
    Returns the file, line number, type, and full source code of the definition.
    """
    from graph_store import get_conn, goto_definition as _goto_def
    conn = get_conn(PROJECT_ID)
    result = _goto_def(conn, symbol_name)
    conn.close()
    if not result:
        return f"No definition found for '{symbol_name}'."

    parts = []
    for d in result["definitions"]:
        # try to read the actual source
        source = ""
        try:
            lines = open(d["file"], errors='ignore').readlines()
            source = "".join(lines[d["start_line"]:d["end_line"]+1])[:2000]
        except Exception:
            pass
        parts.append(
            f"FILE: {d['file']} (lines {d['start_line']}–{d['end_line']})\n"
            f"TYPE: {d['type']}\n"
            f"```\n{source}\n```"
        )
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def find_implementations(class_or_interface: str) -> str:
    """
    Find all classes that extend or implement a given class/interface.
    Use this to understand the full type hierarchy before refactoring a base class.
    """
    from graph_store import get_conn, find_implementations as _find_impls
    conn = get_conn(PROJECT_ID)
    impls = _find_impls(conn, class_or_interface)
    conn.close()
    if not impls:
        return f"No implementations found for '{class_or_interface}'."
    lines = [f"- {r['name']} ({r['file']}:{r['line']}) [{r['type']}]" for r in impls]
    return (f"Implementations of '{class_or_interface}' ({len(impls)} found):\n" +
            "\n".join(lines))


@mcp.tool()
def explain_symbol(symbol_name: str) -> str:
    """
    Get a comprehensive view of a symbol: definition, callers, callees,
    references, type hierarchy, and PageRank importance.
    The single best tool for understanding what a function does and why it matters.
    """
    from graph_store import get_conn, get_symbol_detail
    conn = get_conn(PROJECT_ID)
    detail = get_symbol_detail(conn, symbol_name)
    conn.close()

    if not detail["definition"]:
        return f"Symbol '{symbol_name}' not found in the index."

    return json.dumps(detail, indent=2)


# ── Git Intelligence ──────────────────────────────────────────

@mcp.tool()
def get_hotspots(limit: int = 15) -> str:
    """
    Find the riskiest files in the codebase — high churn + many authors.
    These are the files most likely to have bugs and most in need of refactoring.
    Risk score = change_count × number_of_authors.
    """
    from graph_store import get_conn
    conn = get_conn(PROJECT_ID)
    try:
        rows = conn.execute("""
            SELECT file, change_count FROM git_churn
            ORDER BY change_count DESC LIMIT ?
        """, (limit,)).fetchall()
    except Exception:
        rows = []
    conn.close()

    if not rows:
        # fall back to live git analysis
        try:
            from git_intel import get_hotspots as _get_hotspots
            project_dir = _find_project_root()
            if project_dir:
                hotspots = _get_hotspots(project_dir, limit)
                if hotspots:
                    lines = [f"- {h['file']} (changes: {h['change_count']}, "
                             f"authors: {h['authors']}, risk: {h['risk_score']})"
                             for h in hotspots]
                    return f"Hotspots (high churn × many authors):\n" + "\n".join(lines)
        except Exception:
            pass
        return "No git churn data available. Make sure the project is a git repo."

    lines = [f"- {r[0]} ({r[1]} changes)" for r in rows]
    return f"Highest churn files:\n" + "\n".join(lines)


@mcp.tool()
def get_change_history(file_or_symbol: str) -> str:
    """
    Get the git history for a specific file or symbol.
    Shows who changed it, when, and what the commit message was.
    Use this to understand the evolution of code before making changes.
    """
    from git_intel import get_file_history
    project_dir = _find_project_root()
    if not project_dir:
        return "Could not find project root directory."

    # try as file path first
    history = get_file_history(project_dir, file_or_symbol)

    if not history:
        # try to resolve symbol to file
        try:
            from graph_store import get_conn, goto_definition
            conn = get_conn(PROJECT_ID)
            defn = goto_definition(conn, file_or_symbol)
            conn.close()
            if defn and defn["definitions"]:
                fpath = defn["definitions"][0]["file"]
                history = get_file_history(project_dir, fpath)
        except Exception:
            pass

    if not history:
        return f"No git history found for '{file_or_symbol}'."

    lines = [f"- [{h['date']}] {h['author']}: {h['message']} ({h['hash']})"
             for h in history]
    return f"Git history for '{file_or_symbol}':\n" + "\n".join(lines)


@mcp.tool()
def get_ownership(file_or_symbol: str) -> str:
    """
    Find who owns a piece of code — the contributor with the most commits.
    Use this to know who to ask about code you don't understand.
    """
    from git_intel import get_ownership as _get_ownership
    project_dir = _find_project_root()
    if not project_dir:
        return "Could not find project root directory."

    owners = _get_ownership(project_dir)
    if file_or_symbol in owners:
        o = owners[file_or_symbol]
        return (f"Owner of '{file_or_symbol}':\n"
                f"- Primary author: {o['author']} ({o['commits']} commits)\n"
                f"- Total authors: {o['total_authors']}")

    # partial match
    matches = {k: v for k, v in owners.items() if file_or_symbol in k}
    if matches:
        lines = [f"- {f}: {o['author']} ({o['commits']} commits, "
                 f"{o['total_authors']} total authors)"
                 for f, o in list(matches.items())[:10]]
        return f"Ownership matches:\n" + "\n".join(lines)

    return f"No ownership data found for '{file_or_symbol}'."


@mcp.tool()
def get_change_coupling(file_path: str) -> str:
    """
    Find files that frequently change together with this file.
    If file A always changes when file B changes, they're coupled —
    even if there's no import between them. This reveals hidden dependencies.
    """
    from graph_store import get_conn, get_change_coupling_for_file
    conn = get_conn(PROJECT_ID)
    results = get_change_coupling_for_file(conn, file_path)
    conn.close()

    if not results:
        return f"No change coupling data found for '{file_path}'."

    lines = [f"- {r['file_a']} ↔ {r['file_b']} ({r['co_changes']} co-changes)"
             for r in results]
    return f"Files that change together with '{file_path}':\n" + "\n".join(lines)


# ── Architecture Intelligence ────────────────────────────────

@mcp.tool()
def get_architecture_summary() -> str:
    """
    Get a high-level overview of the codebase architecture.
    Detects frameworks (Django, React, Express, etc.), identifies layers
    (controllers/services/models), finds entry points, and ranks the most
    important symbols. Call this first when working with an unfamiliar codebase.
    """
    from architecture import generate_architecture_summary
    from store import get_indexed_files

    files = get_indexed_files(PROJECT_ID)
    if not files:
        return "No files indexed. Run cassetto index first."

    project_dir = _find_project_root()
    if not project_dir:
        return "Could not determine project root."

    graph_conn = None
    try:
        from graph_store import get_conn
        graph_conn = get_conn(PROJECT_ID)
    except Exception:
        pass

    summary = generate_architecture_summary(project_dir, files, graph_conn)

    if graph_conn:
        graph_conn.close()

    return json.dumps(summary, indent=2)


@mcp.tool()
def find_entry_points() -> str:
    """
    Find all entry points: route handlers, CLI commands, main functions,
    exported components, test files. These are where execution starts.
    Use this to understand how a codebase is structured.
    """
    from architecture import find_entry_points as _find_entries
    from store import get_indexed_files

    files = get_indexed_files(PROJECT_ID)
    project_dir = _find_project_root()
    if not project_dir or not files:
        return "No files indexed or could not find project root."

    entries = _find_entries(project_dir, files)
    if not entries:
        return "No entry points detected."

    # group by type
    by_type = {}
    for e in entries:
        t = e["type"]
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(e)

    parts = []
    for t, items in by_type.items():
        lines = [f"  - {e['file']}:{e['line']}" for e in items[:10]]
        parts.append(f"{t} ({len(items)}):\n" + "\n".join(lines))

    return "Entry points:\n\n" + "\n\n".join(parts)


@mcp.tool()
def get_imports(file_or_symbol: str) -> str:
    """
    Show what a file imports and what imports it.
    Use this to understand module dependencies before refactoring.
    """
    from graph_store import (get_conn, get_imports_for_file,
                             get_importers_of)
    conn = get_conn(PROJECT_ID)
    imports = get_imports_for_file(conn, file_or_symbol)
    importers = get_importers_of(conn, file_or_symbol)
    conn.close()

    parts = []
    if imports:
        lines = [f"  - {i['module']}"
                 + (f" ({', '.join(i['names'])})" if i['names'] else "")
                 + (f" → {i['resolved_file']}" if i['resolved_file'] else " (external)")
                 for i in imports]
        parts.append(f"Imports ({len(imports)}):\n" + "\n".join(lines))

    if importers:
        lines = [f"  - {i['file']} (imports {i['module']})" for i in importers]
        parts.append(f"\nImported by ({len(importers)}):\n" + "\n".join(lines))

    if not parts:
        return f"No import data found for '{file_or_symbol}'."

    return "\n".join(parts)


# ── Graph Intelligence ────────────────────────────────────────

@mcp.tool()
def find_cycles() -> str:
    """
    Detect circular dependencies in the import graph.
    Circular dependencies are architectural debt — A imports B imports C imports A.
    Returns all cycles found, sorted by length.
    """
    from graph_store import get_conn, find_cycles as _find_cycles
    conn = get_conn(PROJECT_ID)
    cycles = _find_cycles(conn)
    conn.close()

    if not cycles:
        return "No circular dependencies detected. The import graph is acyclic."

    lines = [f"- {' → '.join(c)} → {c[0]}" for c in cycles]
    return f"Circular dependencies ({len(cycles)} found):\n" + "\n".join(lines)


# ── helpers ────────────────────────────────────────────────────

def _find_project_root() -> str | None:
    """Try to find the project root from indexed files."""
    files = get_indexed_files(PROJECT_ID)
    if not files:
        return None
    # find common prefix of all indexed files
    from os.path import commonpath
    try:
        return commonpath(files)
    except ValueError:
        return str(Path(files[0]).parent)


if __name__ == "__main__":
    mcp.run()
