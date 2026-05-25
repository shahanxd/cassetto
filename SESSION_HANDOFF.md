# Codebase Intelligence — Session Handoff Document

> This doc gives you everything you need to continue working on this project. Read it fully before making changes.

## What This Project Is

A local, offline-first code intelligence system that gives LLMs deep codebase awareness via MCP (Model Context Protocol). It indexes source code into three databases, then exposes search, call graph, blast radius, dead code detection, and repo mapping tools that Claude/Antigravity can call.

**Status: All 4 stages complete, tested, working.** The user (shahanxd) built this iteratively — stages 1 through 4, each adding a layer. It's been tested on both itself (9 Python files) and the user's Sparrow project (57 files, React + Django air quality app).

## Project Location & Environment

- **Code**: `C:\Users\shaha\Documents\codebase-intelligence\`
- **Data**: `~/.codebase-intelligence/<project-id>/` (per-project subdirectories)
- **OS**: Windows 11, Python 3.12
- **Embedding**: Ollama running locally with `nomic-embed-text` model
- **MCP Registration**: `C:\Users\shaha\.gemini\antigravity\mcp_config.json`

MCP config currently points to project `test` (the self-index). To switch to Sparrow, change `CI_PROJECT_ID` to `sparrow`:
```json
{
  "mcpServers": {
    "codebase-intelligence": {
      "command": "python",
      "args": ["C:\\Users\\shaha\\Documents\\codebase-intelligence\\server.py"],
      "env": {
        "CI_PROJECT_ID": "test"
      }
    }
  }
}
```

## Installed Dependencies

```
fastmcp, lancedb, requests, pyarrow
tree-sitter (0.25.2), tree-sitter-language-pack (1.8.1)
duckdb (1.5.3), networkx (3.6.1), scipy (1.17.1)
watchdog (6.0.0)
```

All in the global Python 3.12 install (no venv). `requirements.txt` is up to date.

---

## Architecture Overview

```
source files
    → ast_chunker.py (tree-sitter AST parsing, 12 languages)
    → embedder.py (Ollama nomic-embed-text, 768-dim vectors)
    → store.py (LanceDB vectors + SQLite FTS5 keywords)
    → graph_store.py (DuckDB call graph + PageRank via networkx)
    → server.py (FastMCP server, 6 tools exposed to LLMs)
    → watcher.py (Watchdog file watcher for live incremental updates)
```

Three databases per project, each doing what it's best at:
- **LanceDB** → vector similarity search (semantic)
- **SQLite FTS5** → BM25 keyword search (exact name matches)
- **DuckDB** → call graph, blast radius (recursive SQL), PageRank scores

Results from LanceDB and SQLite are combined via **Reciprocal Rank Fusion (RRF)** — `score = sum of 1/(rank + 60)` across both result lists.

---

## File-by-File Reference

### `config.py` (32 lines)
Central config with env var overrides. Key values:
- `DATA_DIR`: where all project data lives (`~/.codebase-intelligence/`)
- `EMBEDDING_BACKEND`: `"ollama"` (default) or `"voyage"`
- `OLLAMA_URL`: `http://localhost:11434`
- `OLLAMA_MODEL`: `nomic-embed-text`
- `SKIP_DIRS`: set of directory names to skip (.git, node_modules, __pycache__, etc.)
- `SUPPORTED_EXTENSIONS`: set of file extensions we can parse (.py, .js, .ts, .go, .rs, .java, etc.)
- `MAX_CHUNK_SIZE`: 6000 chars (truncate huge functions)
- `MIN_CHUNK_SIZE`: 20 chars (skip trivial chunks)

### `ast_chunker.py` (235 lines)
Tree-sitter based code parser. Key exports:
- `chunk_file(file_path) -> list[Chunk]` — parses a file into one Chunk per function/class/method
- `diff_chunks(old, new) -> (added, modified, deleted_ids)` — used by the watcher for incremental updates
- `Chunk` dataclass: `id, file, symbol, symbol_type, chunk, start_line, end_line, language, ast_hash`
- `EXTENSION_MAP` dict: maps file extension → tree-sitter grammar name
- `SYMBOL_TYPES` dict: which AST node types to extract per language

**Critical implementation detail**: Tree-sitter returns UTF-8 byte offsets, not Python string character positions. All text extraction uses `source_bytes[start:end].decode()` to avoid misalignment on files with multi-byte characters (like em-dashes in docstrings). This was a real bug we hit and fixed.

**tree-sitter 0.25.x API**: Node accessors are methods, not properties. `node.kind()` not `node.type`, `node.child(i)` not `node.children[i]`, `node.start_position().row` not `node.start_point[0]`, `tree.root_node()` not `tree.root_node`. The parser accepts `str` and handles encoding internally.

### `embedder.py` (82 lines)
Embedding abstraction with two backends:
- `embed_text(text) -> list[float]` — single text (search queries)
- `embed_batch(texts) -> list[list[float]]` — multiple texts (indexing)
- `check_embedding_ready() -> (bool, str)` — health check

Uses `requests.Session` for TCP connection reuse to Ollama (measurable speedup on large indexes). Ollama doesn't support true batch embedding, so `embed_batch` loops with progress logging.

### `store.py` (217 lines)
Dual store keeping LanceDB and SQLite in sync:
- `store_chunks(project_id, chunks, embeddings)` — writes to both stores
- `delete_file_chunks(project_id, file_path)` — deletes from both stores
- `search_vector(project_id, embedding, limit)` — LanceDB ANN search
- `search_bm25(project_id, query, limit)` — SQLite FTS5 MATCH
- `hybrid_search(project_id, query, embedding, limit)` — RRF fusion of both
- `get_chunks_for_file(project_id, file_path)` — used by watcher for diffing
- `update_file_metadata(...)` — tracks indexed files + hashes in SQLite `files` table

**Note**: FTS5 virtual tables don't support `INSERT OR REPLACE`. We always delete first, then insert. LanceDB delete uses SQL-like filter syntax with escaped single quotes.

### `graph_store.py` (217 lines)
DuckDB-based call graph:
- `get_conn(project_id)` — opens/creates the DuckDB file, runs schema setup
- `upsert_symbol(conn, chunk)` — insert/update a symbol node
- `upsert_relationship(conn, from_id, to_id, rel_type)` — insert an edge (deduplicated via hash-based ID)
- `delete_file_symbols(conn, file_path)` — remove a file's nodes + edges
- `resolve_symbol_name(conn, name) -> id | None` — look up symbol ID by name
- `get_call_graph(conn, name)` — callers + callees
- `get_blast_radius(conn, name, max_depth=3)` — WITH RECURSIVE traversal
- `get_dead_code(conn)` — LEFT JOIN to find uncalled functions
- `compute_pagerank(conn)` — builds networkx DiGraph, runs `nx.pagerank(alpha=0.85)`
- `update_pagerank_scores(conn)` — writes scores back via `executemany`

Schema:
```sql
symbols (id PK, name, file, symbol_type, start_line, end_line, pagerank_score)
relationships (id PK, from_id, to_id, rel_type)
```

### `graph_extractor.py` (100 lines)
Tree-sitter AST walker that finds function calls:
- `extract_relationships(file_path, chunks) -> list[Relationship]`
- `Relationship` dataclass: `from_symbol_id, to_symbol_name, rel_type`
- `_CALL_TYPES` dict: maps language → call expression node type (e.g. Python uses `'call'`, JS uses `'call_expression'`, Java uses `'method_invocation'`)

The extractor maps each call to its containing chunk via a `line_to_chunk` dict. Called function names are unresolved strings at this point — resolution to symbol IDs happens in the indexer after all files are processed.

### `indexer.py` (176 lines)
CLI entry point with three subcommands:
- `python indexer.py index <dir> --project <id>` — full index
- `python indexer.py search <query> --project <id>` — CLI search
- `python indexer.py watch <dir> --project <id>` — live file watcher

The index pipeline:
1. Walk directory, collect supported files (skip SKIP_DIRS)
2. For each file: parse → embed → delete old → store new → build graph nodes → extract relationships
3. After all files: resolve relationship names → symbol IDs (two-pass — file B might not exist when processing file A)
4. Compute PageRank over the full graph
5. Unresolved names (stdlib, builtins) are silently dropped

### `server.py` (138 lines)
FastMCP server exposing 6 tools:

| Tool | Signature | Purpose |
|---|---|---|
| `search_code` | `(query: str, limit: int = 10)` | Hybrid BM25 + vector search |
| `get_index_status` | `()` | File count, chunk count, project ID |
| `get_call_graph_tool` | `(symbol_name: str)` | Callers + callees as JSON |
| `blast_radius` | `(symbol_name: str)` | Transitive dependents (3 hops) |
| `find_dead_code` | `()` | Uncalled functions (excludes main, __init__, tests) |
| `get_repo_map` | `(max_symbols: int = 50)` | PageRank-ranked symbol list |

Graph tools use lazy imports (`from graph_store import ...` inside the function) to avoid loading DuckDB/networkx at MCP startup.

`PROJECT_ID` comes from the `CI_PROJECT_ID` env var, set in the MCP config.

### `watcher.py` (171 lines)
Watchdog-based file system observer:
- `CodeChangeHandler` — extends `FileSystemEventHandler`
- Debounces changes (0.4s) to avoid processing half-written saves
- On change: parse → diff → delete old → embed new → store → rebuild graph edges
- On delete: remove from all three databases
- PageRank is batched: recomputed at most once per 30 seconds (set by `PAGERANK_INTERVAL`)
- Full file re-index per change (not surgical partial update — not worth the complexity for single files)

### `chunker.py` (153 lines)
**Dead code** — the original Stage 1 regex-based chunker. Replaced by `ast_chunker.py` in Stage 2. Kept in the repo as reference but nothing imports it. Safe to delete.

### `CLAUDE.md` (14 lines)
Instructions for LLMs on how to use the MCP tools. Placed in project root so Claude/Antigravity auto-reads it.

### `HOW_IT_WORKS.md` (98 lines)
Human-readable explanation of the entire system for the project creator.

---

## Data Layout

```
~/.codebase-intelligence/
├── test/                    # self-index (this project's own code)
│   ├── vectors/chunks.lance/   # LanceDB — 768-dim embedding vectors
│   ├── index.db                # SQLite — FTS5 keyword index + file metadata
│   └── graph.duckdb            # DuckDB — symbols, call edges, PageRank
└── sparrow/                 # Sparrow project index
    ├── vectors/chunks.lance/
    ├── index.db
    └── graph.duckdb
```

### Current Index Stats

**test** (self-index): 9 files, 52 symbols, 63 edges, 49 PageRank-ranked
**sparrow**: 57 files, 129 chunks, 166 edges, 0 errors, indexed in 17.9s

---

## Bugs We Fixed (Don't Reintroduce These)

1. **Byte vs char offsets**: Tree-sitter returns UTF-8 byte positions. Slicing a Python `str` with byte offsets breaks on multi-byte characters (e.g. `—` in docstrings shifts everything by 2 bytes). Always slice `bytes`, then `.decode()`.

2. **tree-sitter 0.25.x API**: Properties became methods. `node.type` → `node.kind()`, `.children` → `child(i)`/`child_count()`, `.start_point` → `start_position().row`. The parser's `.parse()` accepts `str` directly.

3. **FTS5 INSERT OR REPLACE**: SQLite FTS5 virtual tables don't support `REPLACE`. Must `DELETE` first, then `INSERT`.

4. **SQL injection in LanceDB delete**: LanceDB's `.delete()` uses an f-string filter (`file = '{path}'`). File paths with single quotes break it. Fixed by escaping: `path.replace("'", "''")`.

5. **NetworkX PageRank needs scipy**: Not listed as a networkx dependency but fails without it at runtime. Added to requirements.txt.

6. **Windows stdout encoding**: `cp1252` can't encode em-dashes and other Unicode. Fixed with `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` at the top of `indexer.py` and `watcher.py`.

7. **Python stdout buffering**: Background processes buffer stdout, so watcher output was invisible. Fixed by running with `python -u` flag.

---

## What's NOT Done (Potential Next Steps)

These were discussed but not implemented:

- **Incremental index** — currently the `index` command re-indexes everything. Could skip files whose hash hasn't changed (the `files` table already tracks `file_hash`).
- **True batch embedding** — Ollama processes one text at a time. Could switch to an API backend (Voyage AI) or use a local model that supports batching for much faster indexing on large codebases.
- **Import relationship extraction** — `graph_extractor.py` only extracts call relationships. Import/extends/implements relationships were planned but not implemented. The `_IMPORT_TYPES` dict was removed during cleanup as dead code.
- **Cross-project search** — each project is isolated. No way to search across projects.
- **Connection pooling for databases** — SQLite and DuckDB connections are opened per-call in several places. Could be pooled/cached for better performance.
- **Test suite** — no automated tests. Everything was validated manually via CLI and MCP tool calls.

---

## How to Run Things

```powershell
# make sure Ollama is running
ollama serve

# full index of a project
python indexer.py index C:\path\to\project --project myproject

# CLI search
python indexer.py search "authentication" --project myproject

# live file watcher
python -u indexer.py watch C:\path\to\project --project myproject

# MCP server (auto-started by Antigravity via mcp_config.json)
python server.py
```

To switch the MCP server to a different project, edit `CI_PROJECT_ID` in `mcp_config.json`.

---

## How to Verify Everything Works

```powershell
# 1. imports
python -c "from ast_chunker import chunk_file; from store import hybrid_search; from graph_store import get_conn; from watcher import watch; import server; print('OK')"

# 2. search (requires Ollama running)
python indexer.py search "pagerank" --project test

# 3. graph tools
$env:CI_PROJECT_ID = "test"
python -c "from server import blast_radius; print(blast_radius('get_sqlite_conn'))"

# 4. MCP tools (via Antigravity)
# Just ask the LLM to call search_code, blast_radius, etc.
```
