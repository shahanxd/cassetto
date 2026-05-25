<p align="center">
  <h1 align="center">Cassetto</h1>
  <p align="center">
    <strong>Give your LLM structural awareness of any codebase.</strong>
    <br/>
    AST-based code intelligence with hybrid search, call graphs, and blast radius analysis — via MCP.
  </p>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#connect-to-your-llm">Connect to LLM</a> •
  <a href="#tools">Tools</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#evaluation">Evaluation</a>
</p>

---

## What is this?

Cassetto indexes your codebase into a local search + graph database, then exposes it to LLMs via [MCP](https://modelcontextprotocol.io/) (Model Context Protocol). Your LLM gets:

- **Hybrid search** — semantic similarity + keyword matching, fused with Reciprocal Rank Fusion
- **Call graph** — who calls what, and what calls who
- **Blast radius** — "if I change this function, what breaks?" (recursive, up to 3 hops)
- **Dead code detection** — functions nothing calls
- **Repo map** — PageRank-ranked overview of the most important symbols
- **12 language support** — Python, JS, TS, TSX, Go, Rust, Java, Ruby, PHP, C#, C++, C

**100% local.** No API keys needed. No cloud. Runs on Ollama.

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- [Ollama](https://ollama.ai/) running locally with an embedding model:

```bash
ollama pull nomic-embed-text
ollama serve
```

### 2. Install

```bash
git clone https://github.com/shahanxd/cassetto.git
cd cassetto
pip install .
```

### 3. Index your project

```bash
cassetto index /path/to/your/project --project myproject
```

### 4. Search it

```bash
cassetto search "authentication flow" --project myproject
```

That's it. Your codebase is now searchable.

---

## Connect to Your LLM

Cassetto works as an MCP server that LLMs connect to automatically. 

### Claude Code

Add to your Claude Code MCP settings:

```json
{
  "mcpServers": {
    "cassetto": {
      "command": "python",
      "args": ["/path/to/cassetto/server.py"],
      "env": {
        "CASSETTO_PROJECT_ID": "myproject"
      }
    }
  }
}
```

### Antigravity

Add to `~/.gemini/antigravity/mcp_config.json`:

```json
{
  "mcpServers": {
    "cassetto": {
      "command": "python",
      "args": ["/path/to/cassetto/server.py"],
      "env": {
        "CASSETTO_PROJECT_ID": "myproject"
      }
    }
  }
}
```

After connecting, your LLM automatically has access to all 6 tools. Try asking it:
> "What are the most important functions in this codebase?"

---

## Tools

| Tool | What it does | Example |
|---|---|---|
| `search_code(query)` | Hybrid BM25 + vector search. Works for exact names and fuzzy concepts. | `search_code("user authentication")` |
| `get_call_graph_tool(symbol)` | Shows callers and callees of a function. | `get_call_graph_tool("apiFetch")` |
| `blast_radius(symbol)` | What breaks if you change this? Recursive up to 3 hops. | `blast_radius("getAqiColor")` |
| `find_dead_code()` | Functions nothing calls. Excludes main, __init__, tests. | `find_dead_code()` |
| `get_repo_map(n)` | Top N symbols by PageRank importance. | `get_repo_map(20)` |
| `get_index_status()` | How many files/chunks are indexed. | `get_index_status()` |

---

## Live File Watching

Keep your index up-to-date as you code:

```bash
cassetto watch /path/to/your/project --project myproject
```

Changes are debounced (0.4s), and PageRank is recomputed every 30 seconds.

---

## How It Works

```
source files
    → tree-sitter AST parser (12 languages)
    → one chunk per function/class/method
    → embedded into 768-dim vectors (Ollama nomic-embed-text)
    → stored in LanceDB (vectors) + SQLite FTS5 (keywords)
    → call graph edges stored in DuckDB
    → PageRank computed over the call graph (NetworkX)
    → served to LLMs via FastMCP
```

**Three databases**, each doing what it's best at:

| Database | Purpose |
|---|---|
| **LanceDB** | Vector similarity search (semantic) |
| **SQLite FTS5** | BM25 keyword search (exact matches) |
| **DuckDB** | Call graph, blast radius (recursive SQL), PageRank |

Search results from LanceDB and SQLite are combined using **Reciprocal Rank Fusion** — a result that's top-5 in both lists beats one that's #1 in just one list.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full deep dive.

---

## Evaluation

Tested against a real project (57 files, React + Django) with 15 natural developer questions:

| | Cassetto (MCP) | Baseline (grep) |
|---|---|---|
| **Avg Recall** | **66.8%** | 10.2% |
| **Win / Loss** | **14** | 1 |

Cassetto found **6.5x more relevant results** than grep across search, call graph, blast radius, dead code, and architecture questions.

The one grep win: searching for "color" literally matches file content. Cassetto's blast radius missed JSX `<Component>` syntax (known limitation).

Full report in [`eval/`](eval/).

---

## Supported Languages

Python · JavaScript · TypeScript · TSX · JSX · Go · Rust · Java · Ruby · PHP · C# · C++ · C

---

## Configuration

All config is via environment variables (or edit `config.py`):

| Variable | Default | Description |
|---|---|---|
| `CASSETTO_PROJECT_ID` | `default` | Project ID for MCP server |
| `CASSETTO_DATA_DIR` | `~/.cassetto/` | Where index data is stored |
| `CASSETTO_EMBEDDING_BACKEND` | `ollama` | `ollama` or `voyage` |
| `CASSETTO_OLLAMA_URL` | `http://localhost:11434` | Ollama API endpoint |
| `CASSETTO_OLLAMA_MODEL` | `nomic-embed-text` | Embedding model |
| `VOYAGE_API_KEY` | *(none)* | Optional: Voyage AI API key |

---

## Data Storage

```
~/.cassetto/<project-id>/
├── vectors/           # LanceDB embeddings
├── index.db           # SQLite FTS5 + file metadata
└── graph.duckdb       # Call graph + PageRank
```

Each project is fully isolated. Delete the project directory to reset.

---

## License

MIT — see [LICENSE](LICENSE).
