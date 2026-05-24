# Codebase Intelligence System — Implementation Plan v2
### Revised after deep competitor research, paper review, and stack validation
### Last updated: May 2026

---

## CONTEXT: READ THIS FIRST (for Claude Opus)

This document is the complete implementation plan for a system called **Codebase Intelligence**. You are being given this plan so you can help build it stage by stage.

The person building this is an intermediate developer comfortable with JavaScript/TypeScript and Python. They figure things out independently but may get stuck on hard architectural problems. Your job is to help them build each stage completely before moving to the next.

**Core philosophy of this build:**
- Never build everything at once. Finish one stage, validate it works, then move on.
- Each stage must be independently useful and testable.
- When the developer gets stuck, help them debug the specific problem rather than rewriting everything.
- Prefer simple, working code over clever, broken code.

---

## WHAT CHANGED FROM v1 — READ THIS BEFORE ANYTHING ELSE

The original plan had **three critical errors** discovered during research. These are not minor tweaks — they would have caused real pain mid-build:

### ❌ CRITICAL CHANGE 1: Kuzu is dead. Do not use it.
Kuzu (KuzuDB) was acquired by Apple and **archived in October 2025**. Active development stopped. The plan originally recommended it as the graph database. Replace with **DuckDB + DuckPGQ extension** (see below).

### ❌ CRITICAL CHANGE 2: MCP server architecture was wrong (Node.js calling Python subprocess)
The original plan had a Node.js MCP server calling Python as a subprocess for every query. This adds latency, complexity, and a process management nightmare. **Use a single Python MCP server with FastMCP instead.** Python has first-class MCP support, all your AI/ML libraries are in Python anyway, and FastMCP cuts boilerplate by 80%.

### ❌ CRITICAL CHANGE 3: Pure vector search is not enough — add BM25 hybrid
Research consistently shows pure vector search fails on exact identifiers, function names, and rare terms. For code, where someone searches "validateUserSession" and needs that exact function — not semantically similar code — BM25 is essential. **Build hybrid from Stage 1**, not as an afterthought.

### ✅ ADDITIONS based on research findings:
- **PageRank on the call graph** — Aider's proven technique for ranking which symbols matter most. Adds almost no complexity but dramatically improves context quality.
- **voyage-code-3 as optional upgrade path** — Best code embedding model available (Voyage AI is now part of Anthropic). Offer as upgrade over local Ollama when privacy isn't a concern.
- **CLAUDE.md instruction file** — Tell Claude Code *how* to use your tools. Without this, it defaults to grep/file-reading even when your MCP tools would be better.
- **Dead code detection** — Free feature once you have the call graph. Very high value.
- **Blast radius tool** — "What breaks if I change this?" is the killer feature of this whole system.

### What stayed the same:
- Tree-sitter for parsing (still the right choice — 130+ languages, battle-tested)
- LanceDB for vectors (still good — embedded, fast, no server needed)
- MCP as the integration layer (now even more confirmed as the standard)
- Incremental update architecture (still correct approach)
- The 4-stage build order (Stage 1 first, validate, then expand)

---

## COMPETITIVE LANDSCAPE (what you're up against)

This is worth knowing so you understand where your tool fits and what makes it worth building.

| Tool | Stars | What it does | Gap |
|---|---|---|---|
| Repomix | 22k | Flattens whole repo into one LLM prompt | No persistent index, hits token limits on large repos |
| Aider repo-map | Built-in | PageRank-ranked symbol map, regenerated each session | No persistence, no semantic search, no call graph queries |
| Cursor @codebase | Built-in | Embeddings-based search, session-level | Proprietary, no offline, no graph traversal |
| GitNexus | 14k | Deep graph + MCP, best in class | PolyForm NC license (can't use commercially), TypeScript only |
| CodeGraphContext | 2.2k | Graph + MCP, MIT license | No incremental updates, no hybrid search |
| codebase-memory-mcp | New | Graph + SQLite, Go binary, good design | Early stage, no semantic embeddings |
| Sourcegraph Cody | Enterprise | Cloud-hosted, full codebase RAG | Your code leaves your machine |

**Your gap to fill:** The market research identified this explicitly — *"no tool has nailed incremental, real-time graph updates that keep pace with active development."* That's Stage 4 of this build. Everything else has been partially solved. The always-fresh, offline-first, hybrid-search system with real-time incremental updates does not exist yet as a polished tool.

---

## SYSTEM ARCHITECTURE (updated)

```
┌─────────────────────────────────────────────────────────────┐
│                      Developer's Machine                    │
│                                                             │
│  ┌───────────┐    ┌──────────────────────────────────────┐  │
│  │   Claude  │    │    Python MCP Server (FastMCP)       │  │
│  │   Code /  │◄──►│                                      │  │
│  │   Cursor  │    │  Tools:                              │  │
│  └───────────┘    │  - search_code (BM25 + vector + RRF) │  │
│                   │  - get_call_graph                    │  │
│                   │  - blast_radius                      │  │
│                   │  - find_dead_code                    │  │
│                   │  - get_index_status                  │  │
│                   │  - get_repo_map (PageRank ranked)    │  │
│                   └──────────────┬───────────────────────┘  │
│                                  │                          │
│              ┌───────────────────┼──────────────────┐       │
│              │                   │                  │       │
│        ┌─────▼──────┐    ┌───────▼──────┐  ┌───────▼────┐  │
│        │  LanceDB   │    │  DuckDB +    │  │  SQLite    │  │
│        │ (vectors)  │    │  DuckPGQ     │  │  (BM25 +   │  │
│        │            │    │  (graph)     │  │  metadata) │  │
│        └────────────┘    └──────────────┘  └────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Background Watcher (Watchdog)                       │   │
│  │  File change → AST diff → targeted update           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Why three stores instead of two:**
- **LanceDB** — vector search (semantic similarity, "find code like this")
- **DuckDB + DuckPGQ** — graph traversal (call chains, dependencies, blast radius)
- **SQLite** — BM25 full-text search + file metadata (exact symbol names, fast keyword search)

These three cover different query types that the others can't. Results are fused in the search tool using Reciprocal Rank Fusion.

---

## TECH STACK — FINAL CHOICES

### Parser: Tree-sitter ✅ (unchanged)
Still correct. 130+ languages. Incremental parsing. Used by GitHub, Neovim, Zed, Claude Code itself (for LSP integration). No alternative comes close.

**Note on Tree-sitter Python bindings:** Use `tree-sitter >= 0.21` and `tree-sitter-language-pack` instead of separate per-language packages. This bundles 170+ languages in one install.

```bash
pip install tree-sitter tree-sitter-language-pack
```

### Graph DB: DuckDB + DuckPGQ ✅ (replaces Kuzu)
Kuzu is dead. DuckDB is the embedded analytical database — it's the SQLite of OLAP. DuckPGQ is an official DuckDB community extension adding SQL/PGQ graph queries (the SQL:2023 standard). DuckDB already knows SQL so graph queries integrate naturally.

```python
import duckdb
conn = duckdb.connect("graph.duckdb")
conn.install_extension("duckpgq", repository="community")
conn.load_extension("duckpgq")
```

DuckPGQ is still labeled a research extension but it's stable enough for this use case. If it causes issues, the fallback is storing the graph as plain DuckDB tables and writing graph traversal in pure SQL (WITH RECURSIVE queries) — DuckDB handles those well.

### Vector DB: LanceDB ✅ (unchanged)
Still the right choice for embedded, offline-first vector storage. No alternative beats it for the local-first constraint. Works with Python directly.

### Full-text search: SQLite FTS5 (new addition)
SQLite with FTS5 (built-in full-text search extension) handles BM25. Zero extra dependencies — SQLite ships on every platform. Store the same code chunks in SQLite with FTS5 alongside LanceDB for vectors. The metadata you'd store anyway (file paths, symbol names, line numbers) goes here too.

```sql
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    symbol, chunk, file, tokenize="porter unicode61"
);
```

### Embedding model: nomic-embed-text via Ollama (local default) ✅ (updated)
`nomic-embed-code` is not reliably available via Ollama. Use `nomic-embed-text` as default — it performs well on code and is always available. 

**Upgrade path:** If the user is okay with API calls, `voyage-code-3` (Voyage AI, now part of Anthropic) is the best code embedding model available — outperforms OpenAI by 13.8% on code retrieval benchmarks. Support both as a config option:

```python
# config.py
EMBEDDING_BACKEND = "ollama"  # or "voyage"
OLLAMA_MODEL = "nomic-embed-text"
VOYAGE_MODEL = "voyage-code-3"  # requires VOYAGE_API_KEY env var
```

### MCP Server: Python + FastMCP ✅ (replaces Node.js + TypeScript)
Drop the two-language split entirely. Write the MCP server in Python — same language as the indexer, embedder, and graph store. FastMCP is an official wrapper that cuts boilerplate to near-zero.

```bash
pip install fastmcp
```

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("codebase-intelligence")

@mcp.tool()
def search_code(query: str, limit: int = 10) -> str:
    """Search the codebase for code semantically similar to a query."""
    ...
```

### Graph ranking: NetworkX PageRank (new addition)
Stolen directly from Aider's proven approach. Build an in-memory NetworkX graph from the symbol relationships, run PageRank, and use scores to rank search results and generate the repo map. Adds negligible complexity, significant value.

```bash
pip install networkx
```

---

## DATA MODELS (updated)

### CodeChunk (stored in LanceDB + SQLite FTS5)

```python
@dataclass
class CodeChunk:
    id: str              # sha256(file:symbol:start_line)[:16]
    file: str            # absolute path
    symbol: str          # function/class name
    symbol_type: str     # "function" | "class" | "method" | "module"
    chunk: str           # source code text
    start_line: int
    end_line: int
    language: str
    embedding: list[float]  # 768-dim for nomic-embed-text
    ast_hash: str        # sha256 of chunk text — change detection
    pagerank_score: float  # importance score (updated when graph is built)
    stale: bool          # flagged if a dependency changed
    last_indexed: float  # unix timestamp
```

### Graph Schema (DuckDB + DuckPGQ)

```sql
-- Plain DuckDB tables that DuckPGQ treats as a property graph
CREATE TABLE IF NOT EXISTS symbols (
    id VARCHAR PRIMARY KEY,
    name VARCHAR,
    file VARCHAR,
    symbol_type VARCHAR,
    start_line INTEGER,
    end_line INTEGER,
    pagerank_score DOUBLE DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS relationships (
    from_id VARCHAR,
    to_id VARCHAR,
    rel_type VARCHAR,  -- 'calls' | 'imports' | 'extends' | 'defines'
    FOREIGN KEY (from_id) REFERENCES symbols(id),
    FOREIGN KEY (to_id) REFERENCES symbols(id)
);

-- DuckPGQ property graph view on top
CREATE PROPERTY GRAPH code_graph
    VERTEX TABLES (symbols)
    EDGE TABLES (
        relationships
            SOURCE KEY (from_id) REFERENCES symbols(id)
            DESTINATION KEY (to_id) REFERENCES symbols(id)
            LABEL rel_type
    );
```

### FileMetadata (SQLite)

```sql
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    last_modified REAL,
    last_indexed REAL,
    file_hash TEXT,
    symbol_count INTEGER,
    error TEXT
);
```

---

## STAGE 1: DUMB BUT WORKING
### Goal: Hybrid search (BM25 + vectors) over codebase via MCP. No graph yet.
### Time estimate: 1–2 weeks
### Success criteria: LLM can call `search_code("validateUser")` and get the right function back via both exact name match and semantic search

---

### Stage 1, Step 1: Project scaffold

```
codebase-intelligence/
├── server.py          # FastMCP entry point — the whole MCP server
├── indexer.py         # Walk directory, chunk, embed, store
├── chunker.py         # Naive file splitter (Stage 1) → AST splitter (Stage 2)
├── embedder.py        # Ollama / Voyage AI embedding
├── store.py           # LanceDB + SQLite storage and query
├── config.py          # Project settings
└── requirements.txt
```

One language (Python), one directory, no Node.js, no subprocess calls.

### Stage 1, Step 2: Config

```python
# config.py
import os
from pathlib import Path

DATA_DIR = Path.home() / ".codebase-intelligence"
EMBEDDING_BACKEND = os.getenv("CI_EMBEDDING_BACKEND", "ollama")
OLLAMA_URL = os.getenv("CI_OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("CI_OLLAMA_MODEL", "nomic-embed-text")
VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
VOYAGE_MODEL = "voyage-code-3"
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
             'dist', 'build', '.next', '.nuxt', 'coverage', '.pytest_cache'}
SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go',
                        '.rs', '.java', '.rb', '.php', '.cs', '.cpp', '.c'}
```

### Stage 1, Step 3: Embedder

```python
# embedder.py
import os
import requests

def embed_text(text: str) -> list[float]:
    from config import EMBEDDING_BACKEND
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage(text)
    return _embed_ollama(text)

def embed_batch(texts: list[str]) -> list[list[float]]:
    from config import EMBEDDING_BACKEND
    if EMBEDDING_BACKEND == "voyage":
        return _embed_voyage_batch(texts)
    return [_embed_ollama(t) for t in texts]

def _embed_ollama(text: str) -> list[float]:
    from config import OLLAMA_URL, OLLAMA_MODEL
    r = requests.post(f"{OLLAMA_URL}/api/embeddings",
                      json={"model": OLLAMA_MODEL, "prompt": text},
                      timeout=30)
    r.raise_for_status()
    return r.json()["embedding"]

def _embed_voyage_batch(texts: list[str]) -> list[list[float]]:
    from config import VOYAGE_API_KEY, VOYAGE_MODEL
    import voyageai
    client = voyageai.Client(api_key=VOYAGE_API_KEY)
    result = client.embed(texts, model=VOYAGE_MODEL, input_type="document")
    return result.embeddings

def _embed_voyage(text: str) -> list[float]:
    return _embed_voyage_batch([text])[0]

def check_embedding_ready() -> tuple[bool, str]:
    from config import EMBEDDING_BACKEND, OLLAMA_URL, VOYAGE_API_KEY
    if EMBEDDING_BACKEND == "voyage":
        if not VOYAGE_API_KEY:
            return False, "VOYAGE_API_KEY env var not set"
        return True, "voyage ready"
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200, "ollama ready"
    except Exception:
        return False, "Ollama not running. Start with: ollama serve"
```

### Stage 1, Step 4: Storage (LanceDB + SQLite hybrid)

```python
# store.py
import sqlite3
import lancedb
import json
from pathlib import Path
from config import DATA_DIR

def get_project_dir(project_id: str) -> Path:
    d = DATA_DIR / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_lance_table(project_id: str):
    db = lancedb.connect(str(get_project_dir(project_id) / "vectors"))
    if "chunks" in db.table_names():
        return db.open_table("chunks")
    return None

def get_sqlite_conn(project_id: str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(get_project_dir(project_id) / "index.db"))
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            id, symbol, chunk, file, start_line, end_line, language,
            ast_hash, symbol_type, tokenize='porter unicode61'
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

def store_chunks(project_id: str, chunks: list, embeddings: list[list[float]]):
    """Store chunks in both LanceDB (vectors) and SQLite (BM25)."""
    project_dir = get_project_dir(project_id)
    db = lancedb.connect(str(project_dir / "vectors"))
    conn = get_sqlite_conn(project_id)

    records = []
    for chunk, emb in zip(chunks, embeddings):
        record = {
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
        }
        records.append(record)

    # LanceDB
    if "chunks" in db.table_names():
        db.open_table("chunks").add(records)
    else:
        db.create_table("chunks", records)

    # SQLite FTS5 — store everything except the vector
    for chunk in chunks:
        conn.execute("""
            INSERT OR REPLACE INTO chunks_fts
            (id, symbol, chunk, file, start_line, end_line, language, ast_hash, symbol_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (chunk.id, chunk.symbol, chunk.chunk, chunk.file,
              chunk.start_line, chunk.end_line, chunk.language,
              chunk.ast_hash, chunk.symbol_type))
    conn.commit()

def search_vector(project_id: str, embedding: list[float], limit: int = 20) -> list[dict]:
    """Dense vector search."""
    table = get_lance_table(project_id)
    if not table:
        return []
    return table.search(embedding).limit(limit).to_list()

def search_bm25(project_id: str, query: str, limit: int = 20) -> list[dict]:
    """BM25 keyword search using SQLite FTS5."""
    conn = get_sqlite_conn(project_id)
    rows = conn.execute("""
        SELECT id, symbol, chunk, file, start_line, end_line, language,
               rank AS bm25_score
        FROM chunks_fts
        WHERE chunks_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (query, limit)).fetchall()
    cols = ["id", "symbol", "chunk", "file", "start_line", "end_line", "language", "bm25_score"]
    return [dict(zip(cols, row)) for row in rows]

def hybrid_search(project_id: str, query: str, embedding: list[float], limit: int = 10) -> list[dict]:
    """
    Combine BM25 and vector results using Reciprocal Rank Fusion.
    RRF score = 1/(rank + k) where k=60 (standard constant).
    Higher is better.
    """
    k = 60

    vector_results = search_vector(project_id, embedding, limit=20)
    bm25_results = search_bm25(project_id, query, limit=20)

    scores: dict[str, float] = {}
    result_map: dict[str, dict] = {}

    for rank, result in enumerate(vector_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        result_map[rid] = result

    for rank, result in enumerate(bm25_results):
        rid = result["id"]
        scores[rid] = scores.get(rid, 0) + 1.0 / (rank + k)
        result_map[rid] = result

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [result_map[rid] for rid in sorted_ids[:limit]]

def delete_file_chunks(project_id: str, file_path: str):
    """Remove all chunks for a file from both stores."""
    table = get_lance_table(project_id)
    if table:
        table.delete(f"file = '{file_path}'")
    conn = get_sqlite_conn(project_id)
    conn.execute("DELETE FROM chunks_fts WHERE file = ?", (file_path,))
    conn.commit()

def get_indexed_files(project_id: str) -> list[str]:
    conn = get_sqlite_conn(project_id)
    rows = conn.execute("SELECT DISTINCT file FROM chunks_fts").fetchall()
    return [r[0] for r in rows]

def get_chunks_for_file(project_id: str, file_path: str) -> list[dict]:
    """Get all stored chunks for a file (for diff during incremental update)."""
    conn = get_sqlite_conn(project_id)
    rows = conn.execute(
        "SELECT id, symbol, ast_hash FROM chunks_fts WHERE file = ?", (file_path,)
    ).fetchall()
    return [{"id": r[0], "symbol": r[1], "ast_hash": r[2]} for r in rows]
```

### Stage 1, Step 5: FastMCP Server

```python
# server.py
import os
import sys
from mcp.server.fastmcp import FastMCP
from embedder import embed_text, check_embedding_ready
from store import hybrid_search, get_indexed_files, get_sqlite_conn
from indexer import index_directory

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
        return "No results found. Has the codebase been indexed? Run: python indexer.py index /path/to/project"

    parts = []
    for r in results:
        parts.append(
            f"FILE: {r['file']} (lines {r['start_line']}–{r['end_line']})\n"
            f"SYMBOL: {r['symbol']} ({r['language']})\n"
            f"```\n{r['chunk'][:2000]}\n```"
        )
    return "\n\n---\n\n".join(parts)

@mcp.tool()
def get_index_status() -> str:
    """
    Check the status of the codebase index.
    Returns how many files are indexed, which files are stale, and last update time.
    Call this if you suspect the index might be out of date.
    """
    files = get_indexed_files(PROJECT_ID)
    conn = get_sqlite_conn(PROJECT_ID)
    file_count = len(files)
    chunk_count = conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
    return f"Index status:\n- {file_count} files indexed\n- {chunk_count} total chunks\n- Project: {PROJECT_ID}"

if __name__ == "__main__":
    mcp.run()
```

### Stage 1, Step 6: Register with Claude Code

Add to `~/.claude/settings.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "codebase-intelligence": {
      "command": "python",
      "args": ["/path/to/codebase-intelligence/server.py"],
      "env": {
        "CI_PROJECT_ID": "my-project"
      }
    }
  }
}
```

### Stage 1, Step 7: CLAUDE.md — teach Claude Code to use your tools

Create `~/.claude/CLAUDE.md` (global) or `CLAUDE.md` in your project root:

```markdown
## Codebase Intelligence (codebase-intelligence MCP)

When this MCP server is available, **prefer it over grep/Glob for code questions**.
Graph queries and hybrid search return precise results in a single tool call vs file-by-file exploration.

- **Finding code by concept**: `search_code("user authentication flow")`
- **Finding a specific function**: `search_code("validateUserSession")`
- **Before making changes**: check `get_index_status` to ensure index is current
- **After large refactors**: re-run indexer: `python indexer.py index /path/to/project`

Use grep/Glob for: text search in comments, string literals, config values not in source symbols.
```

This is critical. Without it, Claude Code will use its built-in tools even when yours would be better.

### Stage 1 validation checklist:
- [ ] `python indexer.py index ./my-project --project test` runs without errors
- [ ] `search_code("functionName")` returns exact match (BM25 working)
- [ ] `search_code("user authentication logic")` returns relevant results (vectors working)
- [ ] MCP server starts: `python server.py` runs without crashing
- [ ] Claude Code sees the tool via `/mcp`
- [ ] Claude Code uses the tool when asked about code

---

## STAGE 2: AST-BASED CHUNKING
### Goal: Replace naive chunker with Tree-sitter for precise function/class chunks
### Time estimate: 1–2 weeks
### Success criteria: Every chunk maps to exactly one function or class. No mid-function splits.

---

### Stage 2, Step 1: Install

```bash
pip install tree-sitter tree-sitter-language-pack
```

Note: `tree-sitter-language-pack` bundles 170+ language grammars. No more per-language installs.

### Stage 2, Step 2: AST chunker

```python
# ast_chunker.py
import hashlib
from pathlib import Path
from dataclasses import dataclass
from tree_sitter import Language, Parser
from tree_sitter_language_pack import get_language, get_parser

SYMBOL_TYPES = {
    'python': {'function_definition', 'class_definition', 'decorated_definition'},
    'javascript': {'function_declaration', 'class_declaration', 'method_definition',
                   'arrow_function', 'variable_declaration'},
    'typescript': {'function_declaration', 'class_declaration', 'method_definition',
                   'interface_declaration', 'type_alias_declaration'},
    'go': {'function_declaration', 'method_declaration', 'type_declaration'},
    'rust': {'function_item', 'impl_item', 'struct_item', 'enum_item'},
    'java': {'method_declaration', 'class_declaration', 'interface_declaration'},
}

EXTENSION_MAP = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.tsx': 'tsx', '.jsx': 'javascript', '.go': 'go',
    '.rs': 'rust', '.java': 'java', '.rb': 'ruby',
    '.cs': 'c_sharp', '.cpp': 'cpp', '.c': 'c',
}

@dataclass
class CodeChunk:
    id: str
    file: str
    symbol: str
    symbol_type: str
    chunk: str
    start_line: int
    end_line: int
    language: str
    ast_hash: str

def chunk_file(file_path: str) -> list[CodeChunk]:
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    try:
        content = path.read_bytes()
        source = content.decode('utf-8', errors='ignore')
    except Exception:
        return []

    try:
        parser = get_parser(lang_name)
        tree = parser.parse(content)
    except Exception:
        return []

    symbol_types = SYMBOL_TYPES.get(lang_name, set())
    chunks: list[CodeChunk] = []
    _walk(tree.root_node, source, file_path, lang_name, symbol_types, chunks)

    # Whole-file fallback if no symbols found
    if not chunks and source.strip():
        file_hash = hashlib.sha256(content).hexdigest()[:16]
        chunk_id = hashlib.sha256(f"{file_path}:module".encode()).hexdigest()[:16]
        chunks.append(CodeChunk(
            id=chunk_id, file=file_path, symbol="module_level",
            symbol_type="module", chunk=source[:4000],
            start_line=0, end_line=source.count('\n'),
            language=lang_name, ast_hash=file_hash
        ))

    return chunks

def _walk(node, source, file_path, lang_name, symbol_types, chunks):
    if node.type in symbol_types:
        chunk_text = source[node.start_byte:node.end_byte]
        symbol = _symbol_name(node, source) or f"anon_{node.start_point[0]}"
        ast_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
        chunk_id = hashlib.sha256(
            f"{file_path}:{symbol}:{node.start_point[0]}".encode()
        ).hexdigest()[:16]
        chunks.append(CodeChunk(
            id=chunk_id, file=file_path, symbol=symbol,
            symbol_type=node.type, chunk=chunk_text,
            start_line=node.start_point[0], end_line=node.end_point[0],
            language=lang_name, ast_hash=ast_hash
        ))
        return  # Don't recurse into found symbols

    for child in node.children:
        _walk(child, source, file_path, lang_name, symbol_types, chunks)

def _symbol_name(node, source) -> str | None:
    for child in node.children:
        if child.type in ('identifier', 'property_identifier', 'name', 'field_identifier'):
            return source[child.start_byte:child.end_byte]
    return None

def diff_chunks(old_chunks: list[dict], new_chunks: list[CodeChunk]):
    """
    Compare old (from DB) and new (freshly parsed) chunks.
    Returns (added, modified, deleted_ids).
    old_chunks: list of dicts with 'id' and 'ast_hash'
    """
    old = {c['id']: c['ast_hash'] for c in old_chunks}
    new = {c.id: c for c in new_chunks}

    added = [c for cid, c in new.items() if cid not in old]
    deleted_ids = [cid for cid in old if cid not in new]
    modified = [c for cid, c in new.items()
                if cid in old and old[cid] != c.ast_hash]

    return added, modified, deleted_ids
```

### Stage 2 validation checklist:
- [ ] Chunks now map exactly to function/class boundaries
- [ ] `ast_hash` is populated and changes when code changes
- [ ] Nested functions don't create duplicate chunks
- [ ] At least 5 languages parse correctly
- [ ] Search quality noticeably improved over naive chunking

---

## STAGE 3: GRAPH + PAGERANK
### Goal: Call graph in DuckDB, PageRank scoring, 3 new MCP tools
### Time estimate: 2–3 weeks
### Success criteria: `blast_radius("functionName")` tells the LLM what breaks if it changes that function

---

### Stage 3, Step 1: DuckDB graph store

```python
# graph_store.py
import duckdb
from pathlib import Path
from config import DATA_DIR

def get_conn(project_id: str) -> duckdb.DuckDBPyConnection:
    db_path = str(DATA_DIR / project_id / "graph.duckdb")
    conn = duckdb.connect(db_path)
    _setup(conn)
    return conn

def _setup(conn):
    conn.execute("""
        INSTALL duckpgq FROM community;
        LOAD duckpgq;
    """)
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

def upsert_symbol(conn, chunk):
    conn.execute("""
        INSERT OR REPLACE INTO symbols (id, name, file, symbol_type, start_line, end_line)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (chunk.id, chunk.symbol, chunk.file, chunk.symbol_type,
          chunk.start_line, chunk.end_line))

def upsert_relationship(conn, from_id: str, to_id: str, rel_type: str):
    import hashlib
    rel_id = hashlib.sha256(f"{from_id}:{to_id}:{rel_type}".encode()).hexdigest()[:16]
    conn.execute("""
        INSERT OR IGNORE INTO relationships (id, from_id, to_id, rel_type)
        VALUES (?, ?, ?, ?)
    """, (rel_id, from_id, to_id, rel_type))

def delete_file(conn, file_path: str):
    conn.execute("DELETE FROM symbols WHERE file = ?", (file_path,))
    # Note: relationships with deleted nodes become dangling — clean up periodically

def get_call_graph(conn, symbol_name: str) -> dict:
    """Who calls this, and what does it call."""
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
        "called_by": [{"name": r[0], "file": r[1], "line": r[2]} for r in callers],
        "calls": [{"name": r[0], "file": r[1], "line": r[2]} for r in callees],
    }

def get_blast_radius(conn, symbol_name: str, max_depth: int = 3) -> dict:
    """
    Find everything that transitively depends on this symbol.
    Uses WITH RECURSIVE SQL (DuckDB supports this natively).
    This is the 'what breaks if I change X' query.
    """
    dependents = conn.execute("""
        WITH RECURSIVE deps AS (
            SELECT to_id AS id, from_id AS dep_id, 1 AS depth
            FROM relationships
            JOIN symbols ON symbols.id = relationships.to_id
            WHERE symbols.name = ? AND relationships.rel_type = 'calls'
            UNION ALL
            SELECT r.to_id, r.from_id, deps.depth + 1
            FROM relationships r
            JOIN deps ON deps.dep_id = r.to_id
            WHERE deps.depth < ?
        )
        SELECT DISTINCT s.name, s.file, deps.depth
        FROM deps
        JOIN symbols s ON deps.dep_id = s.id
        ORDER BY deps.depth
        LIMIT 50
    """, (symbol_name, max_depth)).fetchall()

    return {
        "symbol": symbol_name,
        "blast_radius": [
            {"name": r[0], "file": r[1], "depth": r[2]} for r in dependents
        ],
        "affected_count": len(dependents)
    }

def get_dead_code(conn) -> list[dict]:
    """Find functions that nothing calls (excluding entry points)."""
    results = conn.execute("""
        SELECT s.name, s.file, s.start_line
        FROM symbols s
        LEFT JOIN relationships r ON r.to_id = s.id AND r.rel_type = 'calls'
        WHERE r.to_id IS NULL
          AND s.symbol_type IN ('function_definition', 'function_declaration',
                                 'method_definition', 'method_declaration')
          AND s.name NOT IN ('main', '__init__', 'setup', 'teardown',
                              'index', 'handler', 'middleware')
          AND s.name NOT LIKE 'test_%'
          AND s.name NOT LIKE '%_test'
        LIMIT 100
    """).fetchall()
    return [{"name": r[0], "file": r[1], "line": r[2]} for r in results]

def compute_pagerank(conn) -> dict[str, float]:
    """
    Compute PageRank over the call graph using NetworkX.
    Returns dict of symbol_id -> score.
    """
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

def update_pagerank_scores(conn):
    """Recompute and store PageRank scores in the symbols table."""
    scores = compute_pagerank(conn)
    for symbol_id, score in scores.items():
        conn.execute(
            "UPDATE symbols SET pagerank_score = ? WHERE id = ?",
            (score, symbol_id)
        )
```

### Stage 3, Step 2: Relationship extractor

```python
# graph_extractor.py
from dataclasses import dataclass
from tree_sitter_language_pack import get_parser

@dataclass
class Relationship:
    from_symbol_id: str
    to_symbol_name: str   # resolve to ID later
    rel_type: str          # 'calls' | 'imports' | 'extends'

def extract_relationships(file_path: str, chunks: list) -> list[Relationship]:
    """
    Extract relationships from a file.
    Simple approach: look for call expressions inside each function chunk.
    """
    from pathlib import Path
    from ast_chunker import EXTENSION_MAP
    path = Path(file_path)
    lang_name = EXTENSION_MAP.get(path.suffix)
    if not lang_name:
        return []

    try:
        content = path.read_bytes()
        source = content.decode('utf-8', errors='ignore')
        parser = get_parser(lang_name)
        tree = parser.parse(content)
    except Exception:
        return []

    # Build a map of line -> chunk_id for this file
    line_to_chunk = {}
    for chunk in chunks:
        for line in range(chunk.start_line, chunk.end_line + 1):
            line_to_chunk[line] = chunk.id

    rels = []
    _find_calls(tree.root_node, source, line_to_chunk, lang_name, rels)
    return rels

def _find_calls(node, source, line_to_chunk, lang_name, rels):
    """Find all function calls and map them to their containing chunk."""
    call_types = {
        'python': 'call',
        'javascript': 'call_expression',
        'typescript': 'call_expression',
    }
    call_type = call_types.get(lang_name, 'call_expression')

    if node.type == call_type:
        func_node = node.child(0)
        if func_node:
            called_name = source[func_node.start_byte:func_node.end_byte]
            # Strip method chains: obj.method -> method
            called_name = called_name.split('.')[-1].split('(')[0].strip()
            if called_name and called_name.isidentifier():
                caller_line = node.start_point[0]
                caller_id = line_to_chunk.get(caller_line)
                if caller_id:
                    rels.append(Relationship(
                        from_symbol_id=caller_id,
                        to_symbol_name=called_name,
                        rel_type='calls'
                    ))

    for child in node.children:
        _find_calls(child, source, line_to_chunk, lang_name, rels)
```

### Stage 3, Step 3: New MCP tools

Add these to `server.py`:

```python
import json
from graph_store import get_conn, get_call_graph, get_blast_radius, get_dead_code

@mcp.tool()
def get_call_graph_tool(symbol_name: str) -> str:
    """
    Get the call graph for a specific function or class.
    Shows what functions call it (callers) and what it calls (callees).
    Use this to understand the context of a function before modifying it.
    """
    conn = get_conn(PROJECT_ID)
    result = get_call_graph(conn, symbol_name)
    if not result["called_by"] and not result["calls"]:
        return f"No call graph data found for '{symbol_name}'. The symbol may not be indexed or has no known callers/callees."
    return json.dumps(result, indent=2)

@mcp.tool()
def blast_radius(symbol_name: str) -> str:
    """
    Find everything that depends on this symbol — what breaks if you change it.
    Returns all functions and files that transitively call this symbol, up to 3 hops away.
    ALWAYS call this before modifying a function to understand the impact.
    """
    conn = get_conn(PROJECT_ID)
    result = get_blast_radius(conn, symbol_name)
    if result["affected_count"] == 0:
        return f"'{symbol_name}' has no known dependents. Safe to modify (or not indexed yet)."
    return json.dumps(result, indent=2)

@mcp.tool()
def find_dead_code() -> str:
    """
    Find functions that nothing calls — potential dead code to remove.
    Excludes common entry points (main, __init__, test_ functions, route handlers).
    """
    conn = get_conn(PROJECT_ID)
    results = get_dead_code(conn)
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
    conn = get_conn(PROJECT_ID)
    results = conn.execute("""
        SELECT name, file, symbol_type, pagerank_score
        FROM symbols
        ORDER BY pagerank_score DESC
        LIMIT ?
    """, (max_symbols,)).fetchall()
    if not results:
        return "No symbols indexed yet."
    lines = [f"- {r[0]} ({r[2]}) in {r[1]} [rank: {r[3]:.4f}]" for r in results]
    return "Top symbols by importance (PageRank):\n" + "\n".join(lines)
```

Update `CLAUDE.md` with new tools:

```markdown
## Codebase Intelligence (codebase-intelligence MCP)

Prefer these tools over grep/Glob for structural code questions.

- **Semantic search**: `search_code("user authentication flow")`
- **Exact name search**: `search_code("validateUserSession")`  
- **Before ANY change**: `blast_radius("functionName")` — see what breaks
- **Understanding a function**: `get_call_graph_tool("functionName")`
- **New codebase orientation**: `get_repo_map()` — see the most important symbols
- **Cleanup tasks**: `find_dead_code()` — find unused functions
- **Index health**: `get_index_status()`

Rule: Call `blast_radius` before modifying any function with more than one dependent.
```

### Stage 3 validation checklist:
- [ ] `blast_radius("functionName")` returns dependents for a known function
- [ ] `get_call_graph_tool` shows callers and callees
- [ ] `get_repo_map` returns PageRank-ranked symbols
- [ ] `find_dead_code` returns plausible candidates (spot check a few)
- [ ] Graph survives restart (persisted in DuckDB file)

---

## STAGE 4: REAL-TIME INCREMENTAL UPDATES
### Goal: File saves trigger targeted updates in < 1 second
### Time estimate: 2–3 weeks
### Success criteria: Edit a function → save → search returns updated code within 1s, without re-indexing the whole project

---

### Stage 4, Step 1: File watcher

```python
# watcher.py
import time
import hashlib
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ast_chunker import chunk_file, diff_chunks, EXTENSION_MAP
from store import store_chunks, delete_file_chunks, get_chunks_for_file
from graph_store import get_conn as get_graph_conn, upsert_symbol, delete_file, \
    upsert_relationship, update_pagerank_scores
from graph_extractor import extract_relationships
from embedder import embed_batch
from config import SKIP_DIRS

DEBOUNCE_SECONDS = 0.4

class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.pending: dict[str, float] = {}

    def on_modified(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._schedule(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._handle_delete(event.src_path)

    def _schedule(self, path: str):
        if Path(path).suffix in EXTENSION_MAP:
            if not any(skip in Path(path).parts for skip in SKIP_DIRS):
                self.pending[path] = time.time()

    def _handle_delete(self, path: str):
        print(f"[DELETE] {path}")
        delete_file_chunks(self.project_id, path)
        conn = get_graph_conn(self.project_id)
        delete_file(conn, path)

    def flush(self):
        now = time.time()
        to_process = [p for p, t in list(self.pending.items())
                      if now - t >= DEBOUNCE_SECONDS]
        for path in to_process:
            del self.pending[path]
            try:
                self._handle_change(path)
            except Exception as e:
                print(f"[ERROR] Failed to update {path}: {e}")

    def _handle_change(self, file_path: str):
        print(f"[CHANGE] {file_path}")

        # 1. Parse new chunks
        new_chunks = chunk_file(file_path)

        # 2. Get old chunks from index
        old_chunks = get_chunks_for_file(self.project_id, file_path)

        # 3. Diff
        added, modified, deleted_ids = diff_chunks(old_chunks, new_chunks)
        print(f"  +{len(added)} modified:{len(modified)} -{len(deleted_ids)}")

        # 4. Delete removed chunks from stores
        conn = get_graph_conn(self.project_id)
        delete_file(conn, file_path)   # Remove all file nodes from graph (re-add below)
        delete_file_chunks(self.project_id, file_path)  # Remove from vector + FTS

        if not new_chunks:
            return

        # 5. Re-embed all chunks for this file (simpler than partial update)
        texts = [f"File: {c.file}\nSymbol: {c.symbol}\n\n{c.chunk}" for c in new_chunks]
        embeddings = embed_batch(texts)
        store_chunks(self.project_id, new_chunks, embeddings)

        # 6. Re-build graph nodes for this file
        for chunk in new_chunks:
            upsert_symbol(conn, chunk)

        # 7. Re-extract relationships
        rels = extract_relationships(file_path, new_chunks)
        # Resolve relationship to_symbol_name -> id
        for rel in rels:
            # Find the target symbol's id
            row = conn.execute(
                "SELECT id FROM symbols WHERE name = ? LIMIT 1",
                (rel.to_symbol_name,)
            ).fetchone()
            if row:
                upsert_relationship(conn, rel.from_symbol_id, row[0], rel.rel_type)

        # 8. Recompute PageRank (async in prod, sync here for simplicity)
        update_pagerank_scores(conn)

        print(f"  ✓ Updated {len(new_chunks)} chunks")

def watch(directory: str, project_id: str):
    handler = CodeChangeHandler(project_id)
    observer = Observer()
    observer.schedule(handler, directory, recursive=True)
    observer.start()
    print(f"Watching {directory} for changes...")
    try:
        while True:
            time.sleep(0.1)
            handler.flush()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

### Stage 4, Step 2: Add watch command to indexer.py

```python
# At the bottom of indexer.py
elif args.command == 'watch':
    from watcher import watch
    watch(args.directory, args.project)
```

### Stage 4, Step 3: Optimise PageRank updates

PageRank on every file save is wasteful for large graphs. Batch it:

```python
# In watcher.py — track dirty state and recompute on a timer
class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, project_id: str):
        ...
        self.graph_dirty = False
        self.last_pagerank = 0.0

    def _handle_change(self, file_path: str):
        ...
        self.graph_dirty = True

    def flush(self):
        ...
        # Recompute PageRank at most once per 30 seconds
        if self.graph_dirty and time.time() - self.last_pagerank > 30:
            conn = get_graph_conn(self.project_id)
            update_pagerank_scores(conn)
            self.last_pagerank = time.time()
            self.graph_dirty = False
```

### Stage 4 validation checklist:
- [ ] Edit a function, save → update appears in search within 1 second
- [ ] Only changed symbols are re-processed (check logs show `+0 modified:1 -0` for single-function edits)
- [ ] Delete a file → its chunks disappear from search
- [ ] Rename a function → old name gone, new name appears
- [ ] Watcher runs for 30+ minutes without crashing or memory leak
- [ ] PageRank scores update after changes (check `get_repo_map` before and after)

---

## UPDATED FULL STACK SUMMARY

| Component | Tool | Why |
|---|---|---|
| Parser | tree-sitter + tree-sitter-language-pack | 170+ languages, one install |
| MCP server | Python + FastMCP | No subprocess overhead, all in one language |
| Vector search | LanceDB | Embedded, offline, Python native |
| Keyword search | SQLite FTS5 | Built-in BM25, zero deps |
| Result fusion | RRF (Reciprocal Rank Fusion) | Simple, proven, no tuning required |
| Graph DB | DuckDB + DuckPGQ | Replaces dead Kuzu, SQL-native graph queries |
| Graph ranking | NetworkX PageRank | Same algorithm as Aider (proven at scale) |
| Embeddings (local) | nomic-embed-text via Ollama | Free, offline, good on code |
| Embeddings (quality) | voyage-code-3 via Voyage AI | Best code embedding model, now part of Anthropic |
| File watching | Watchdog | Cross-platform, Python-native |

**Dependencies to install (everything):**

```bash
pip install fastmcp lancedb duckdb tree-sitter tree-sitter-language-pack \
    networkx watchdog requests voyageai
```

---

## KEY INSIGHTS FROM RESEARCH

### 1. The codebase-memory-mcp paper (arXiv:2603.27277) is directly relevant
Published March 2026. Built almost exactly what this plan describes. Key findings: graph-based approach achieved 83% answer quality vs 92% for pure file exploration, but used 10x fewer tokens and 2.1x fewer tool calls. The token efficiency is the real win — the LLM is much faster and cheaper when it queries your graph instead of reading files.

The benchmark also shows you don't need to be perfect. 83% quality at 10x efficiency is a good trade.

### 2. Hybrid search is non-negotiable for code
Pure vector search fails when someone searches for an exact function name, error code, or variable. BM25 catches what vectors miss. The two are complementary and RRF fusion costs almost nothing to implement. The original plan's omission of this was a real gap.

### 3. The PageRank insight from Aider is underrated
Aider processes 15 billion tokens per week with this system. The key insight: not all symbols are equally important. A function called by 50 others is more important context than a helper called once. PageRank quantifies this automatically. Adding it to the graph takes ~20 lines of code (NetworkX) and makes `get_repo_map` genuinely useful.

### 4. The CLAUDE.md file is not optional
The biggest mistake developers make with MCP tools is not telling the LLM when to use them. Claude Code defaults to grep and file reading — fast, familiar, always available. Without a CLAUDE.md instruction, your tools get ignored even when they'd give better results. Write the CLAUDE.md on Day 1.

### 5. Kuzu's death revealed a broader lesson
Always check that your infrastructure dependencies are actively maintained before building on them. For any library central to your system: check its GitHub last commit date and issue activity. The replacement (DuckDB + DuckPGQ) is actually better — DuckDB has major corporate backing, its own extension ecosystem, and SQL familiarity that Kuzu's Cypher didn't have.

---

## ERROR HANDLING AND EDGE CASES

**Tree-sitter partial parse (syntax errors in code):** `tree.root_node.has_error` is True. Log it, don't crash. Parse what's valid and skip errored nodes.

**DuckPGQ not available:** DuckPGQ is a community extension — it could fail to install in some environments. Implement fallback: replace all graph queries with plain DuckDB SQL (WITH RECURSIVE for traversal). The data model works either way.

**Embedding model unavailable:** Return a clear error from the MCP tool rather than crashing the server. The LLM can tell the user to start Ollama.

**Very large functions:** Cap chunk size at 6000 characters. If a function is larger, split at inner class or method boundaries, or truncate with a note.

**Concurrent write conflicts:** DuckDB allows only one writer. The watcher and server should share a connection pool or use WAL mode. For simplicity: the server opens read-only connections, the watcher opens write connections.

**First-run cold start:** Indexing a large repo takes time. Add a progress bar and an estimated time. Users who wait 5 minutes for initial index will be annoyed — set expectations.

---

## TESTING APPROACH

Test each stage with a real open-source project:
- **Small/Python:** https://github.com/pallets/flask (~200 files)
- **Medium/JS:** https://github.com/expressjs/express (~100 files)
- **Large/TS:** https://github.com/microsoft/TypeScript (stress test)

For each stage, validate:
1. Spot-check 5 search results for relevance
2. Verify call graph for 3 functions you know
3. Time file update after a single function edit
4. Confirm dead code list has plausible candidates

---

## GETTING STUCK — HOW TO GET HELP

Describe your problem to Opus with:
1. Which stage and step you're on
2. The exact error message (paste it)
3. What you expected to happen
4. What actually happened

Common traps:
- **DuckPGQ install fails:** Try `conn.execute("FORCE INSTALL duckpgq FROM community")`. If still fails, use plain DuckDB SQL as fallback.
- **Tree-sitter language not found:** Check `tree_sitter_language_pack.AVAILABLE_LANGUAGES` — the name might differ (e.g. 'c_sharp' not 'csharp').
- **LanceDB schema conflicts:** If you changed the chunk schema, delete the `vectors/` folder and re-index.
- **MCP server not showing in Claude Code:** Check `~/.claude/settings.json` syntax (valid JSON?). Test with `npx @modelcontextprotocol/inspector python server.py`.
- **FastMCP tool not found:** Ensure `mcp.run()` is at the bottom of `server.py` and the file is run directly, not imported.
- **Watchdog not firing on macOS:** Use `ObserverType = FSEventsObserver` explicitly on macOS — the default may fall back to polling.
