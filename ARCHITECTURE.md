# How Cassetto Works

This is a local code intelligence system. You index a codebase once, and then any LLM connected via MCP can search it, understand the call graph, and check what breaks before making changes.

## The Pipeline

There are three phases: **index**, **serve**, and **watch**.

### Phase 1: Indexing (`cassetto index <dir> --project <id>`)

The indexer walks your project directory and processes every supported source file through this pipeline:

```
source file
    → tree-sitter AST parser (ast_chunker.py)
    → one chunk per function/class/method
    → each chunk gets embedded into a 768-dim vector (embedder.py → Ollama)
    → vectors stored in LanceDB, text stored in SQLite FTS5 (store.py)
    → symbols + call relationships stored in DuckDB (graph_store.py)
    → PageRank computed over the call graph (networkx)
```

**What each piece does:**

| File | Job |
|---|---|
| `ast_chunker.py` | Parses source code into its real structure using tree-sitter. Each function, class, or method becomes one "chunk" with exact line boundaries. No regex guessing. |
| `embedder.py` | Turns chunk text into 768-dimensional vectors using Ollama's `nomic-embed-text` model running locally. Used for semantic search ("find code that handles authentication"). |
| `store.py` | Dual storage — LanceDB for vector similarity search, SQLite FTS5 for keyword/BM25 search. Results from both are combined using Reciprocal Rank Fusion (RRF). |
| `graph_store.py` | DuckDB database holding the call graph. Every function is a node, every function call is an edge. PageRank scores tell you which functions are most central. |
| `graph_extractor.py` | Walks the AST looking for function calls and maps each call back to the chunk that contains it. Produces "X calls Y" edges for the graph. |

### Phase 2: Serving (`python server.py` or via MCP config)

The MCP server exposes 6 tools that LLMs can call:

| Tool | What it does |
|---|---|
| `search_code("query")` | Hybrid search — combines vector similarity + keyword matching. Works for both exact function names and fuzzy concepts. |
| `get_call_graph_tool("funcName")` | Shows who calls this function and what it calls. |
| `blast_radius("funcName")` | Walks the call graph backwards: "if I change this, what else might break?" Up to 3 hops deep. |
| `find_dead_code()` | Functions that nothing calls. Skips obvious entry points like `main`, `__init__`, test functions. |
| `get_repo_map(50)` | Top N most important symbols ranked by PageRank. Good for getting oriented in a new codebase. |
| `get_index_status()` | How many files and chunks are indexed. |

### Phase 3: Watching (`cassetto watch <dir> --project <id>`)

The file watcher uses Watchdog to monitor the directory. When you save a file:

1. Debounce (0.4s) — wait for the save to finish
2. Parse the file with tree-sitter
3. Diff against stored chunks (what was added/modified/deleted?)
4. Delete old chunks from all three databases
5. Re-embed and store the new chunks
6. Rebuild graph edges for this file
7. PageRank is recomputed every 30 seconds (not every save — too expensive)

## Where Data Lives

```
~/.cassetto/<project-id>/
├── vectors/              # LanceDB — 768-dim embedding vectors
│   └── chunks.lance/
├── index.db              # SQLite — FTS5 keyword index + file metadata
└── graph.duckdb          # DuckDB — symbols, call edges, PageRank scores
```

## How Search Works (RRF)

When you search, two things happen in parallel:
1. Your query gets embedded → LanceDB finds semantically similar chunks
2. Your query runs through FTS5 → SQLite finds keyword matches

Then **Reciprocal Rank Fusion** combines them:
- Each result gets `score = 1/(rank + 60)` from each list
- Scores are summed across both lists
- Results ranked by combined score

This means a result that's #3 in both lists beats a result that's #1 in just one list. You get the best of both approaches.

## How the Call Graph Works

During indexing, `graph_extractor.py` walks the full AST of each file looking for call expressions (like `foo()` or `obj.bar()`). For each call it finds, it:

1. Figures out which chunk (function) the call is inside — using the line number
2. Records a relationship: "function A calls function B" (by name, not ID)
3. After all files are indexed, names are resolved to actual symbol IDs
4. Unresolved names (stdlib, builtins) are silently dropped — they're not in our index

PageRank then treats this call graph like a web of pages: functions that are called by many other functions get higher scores. This lets `get_repo_map()` tell you "these are the most important functions in the codebase."

## Key Design Decisions

- **Offline-first**: Everything runs locally. Ollama for embeddings, DuckDB/SQLite/LanceDB for storage. No API keys needed for the default setup.
- **Three databases, not one**: LanceDB is great at vector search but bad at keyword search. SQLite FTS5 is great at keywords but can't do vectors. DuckDB handles graph queries with recursive SQL. Each does what it's best at.
- **tree-sitter, not regex**: Regex can't handle nested functions, decorators, or multi-line signatures. Tree-sitter gives us the real AST, so chunk boundaries are always correct.
- **Byte offsets, not char offsets**: Tree-sitter returns UTF-8 byte positions. If you slice a Python string with byte offsets, multi-byte characters (like `—`) shift everything. We slice the raw bytes and decode at the end.
