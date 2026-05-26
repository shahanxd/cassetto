# Cassetto

**Give your LLM structural awareness of any codebase via MCP.**

Cassetto is a local-first code intelligence server that connects to AI coding assistants (Antigravity, Claude, Cursor) through the [Model Context Protocol](https://modelcontextprotocol.io/). It indexes your codebase into semantic search + call graphs + import graphs, then exposes 18 tools your LLM calls automatically to answer code questions with real structural intelligence.

**Eval results** (Llama 3.2, 10-question benchmark, React+Django project):
- LLM + project files in context: 17.5% accuracy
- LLM + Cassetto: **76.7% accuracy** (4.4x uplift, 10-0 wins)

---

## Setup (3 steps)

### Prerequisites
- **Python 3.11+**
- **Ollama** running locally: https://ollama.com
- **Git** installed

### Step 1: Install

```bash
pip install cassetto
```

Pull the embedding model:
```bash
ollama pull nomic-embed-text
```

### Step 2: Index your project

```bash
cd /path/to/your/project
cassetto index .
```

This parses all source files, generates embeddings, builds call/import graphs, analyzes git history, and stores everything locally in `~/.cassetto/`.

### Step 3: Connect to your AI assistant

```bash
cassetto setup
```

This auto-configures MCP for every AI assistant it finds on your system (Antigravity, Claude Desktop, Cursor). Restart your assistant and you're done.

That's it. Just talk to your AI normally — it calls Cassetto tools automatically.

---

## What changes

Without Cassetto, your AI can only read files. With Cassetto, it can:

| You ask | Without Cassetto | With Cassetto |
|---|---|---|
| "What breaks if I refactor `auth`?" | Guesses from nearby code | **10 exact callers with file:line** |
| "What are the riskiest files?" | Can't know | **Ranked by git churn x authors** |
| "Show me `getColor` source code" | Searches through files | **Jumps to exact line instantly** |
| "Find dead code" | Can't do cross-file analysis | **Lists unused functions** |
| "What frameworks does this use?" | Infers from filenames | **Auto-detected: React + Django** |
| "Trace the data pipeline" | Struggles with cross-file flow | **Call graph + import graph** |

---

## CLI Reference

```bash
cassetto index [dir]           # Index a project (default: current dir)
cassetto index . --force       # Force full re-index
cassetto setup                 # Auto-configure MCP for your AI assistant
cassetto setup -p myproject    # Configure with specific project ID
cassetto serve                 # Start MCP server manually
cassetto search "auth flow"    # Quick search from terminal
cassetto watch .               # Watch for changes, re-index live
```

The `--project` / `-p` flag is optional everywhere. Defaults to the folder name.

---

## All 18 Tools

Your AI calls these automatically. You never need to know they exist.

### Code Search
- **`search_code`** — Hybrid BM25 + semantic search with graph-aware reranking
- **`get_repo_map`** — PageRank-ranked map of the most important symbols

### Symbol Intelligence
- **`find_references`** — All callers/renderers/extenders of a symbol
- **`goto_definition`** — Jump to source with full code
- **`find_implementations`** — Classes extending a base class
- **`explain_symbol`** — Deep dive: definition + callers + callees + PageRank

### Graph Analysis
- **`get_call_graph`** — What calls this function and what it calls
- **`blast_radius`** — Everything that transitively depends on a symbol
- **`find_dead_code`** — Unreferenced functions (candidates for deletion)
- **`find_cycles`** — Circular dependencies in the import graph

### Git Intelligence
- **`get_hotspots`** — Riskiest files (high churn x many authors)
- **`get_change_history`** — Git log per file/symbol
- **`get_ownership`** — Who wrote this code
- **`get_change_coupling`** — Files that always change together

### Architecture
- **`get_architecture_summary`** — Frameworks, layers, entry points, top symbols
- **`find_entry_points`** — Routes, main functions, CLI commands
- **`get_imports`** — Module dependency graph
- **`get_index_status`** — Index health check

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CASSETTO_PROJECT_ID` | folder name | Which indexed project to query |
| `CASSETTO_DATA_DIR` | `~/.cassetto` | Where indexes are stored |
| `CASSETTO_EMBEDDING_BACKEND` | `ollama` | `ollama` or `voyage` |
| `CASSETTO_OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `CASSETTO_GIT` | `true` | Enable git analysis |

## Supported Languages

Python, JavaScript, TypeScript, JSX, TSX, Go, Rust, Java, Ruby, PHP, C#, C, C++

## How it works

1. **AST Parsing** (tree-sitter) — Extracts functions, classes, methods as structured chunks
2. **Embeddings** (Ollama/Voyage) — Generates semantic vectors for each chunk
3. **Call Graph** (DuckDB) — Tracks who-calls-what, component renders, class inheritance
4. **Import Graph** — Maps module dependencies across 12 languages
5. **Git Analysis** — Churn rates, ownership, change coupling from git history
6. **PageRank** — Ranks symbols by structural importance
7. **MCP Server** (FastMCP) — Exposes all intelligence as tools via stdio protocol

Everything runs locally. No cloud, no API keys required (unless using Voyage embeddings).

## License

MIT
