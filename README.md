# Cassetto 🧠

**Give your AI assistant structural awareness of any codebase.**

[![PyPI](https://img.shields.io/pypi/v/cassetto?color=6366f1)](https://pypi.org/project/cassetto/)
[![Tests](https://img.shields.io/github/actions/workflow/status/shahanxd/cassetto/test.yml?label=tests)](https://github.com/shahanxd/cassetto/actions)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/cassetto)](https://pypi.org/project/cassetto/)

<!-- TODO: Replace with your demo recording -->
<!-- ![Cassetto Demo](demo.gif) -->

---

## The Problem

Your AI coding assistant can see your open files. It **cannot** see your architecture, call graph, or which functions break if you change something. It guesses — and gets it wrong.

## The Solution

Cassetto indexes your codebase into a **call graph + vector database + keyword index** and serves 18 intelligence tools to your AI via [MCP](https://modelcontextprotocol.io/). Three commands, 60 seconds, everything local.

```bash
pip install cassetto
ollama pull nomic-embed-text
cassetto index . && cassetto setup
```

That's it. Your AI now calls Cassetto tools **automatically** — you just talk normally.

---

## What Changes

| You ask | Without Cassetto | With Cassetto |
|---|---|---|
| "What breaks if I refactor `auth`?" | Guesses from nearby code | **10 exact callers with file:line** |
| "What are the riskiest files?" | Can't know | **Ranked by git churn × PageRank** |
| "Show me `getColor` source" | Searches through files | **Jumps to exact line, 26ms** |
| "Find dead code" | Can't do cross-file analysis | **Lists unused functions, 20ms** |
| "Trace the data pipeline" | Struggles with cross-file flow | **Call graph + import graph** |

## Benchmarks

Tested on a React + Django project (52 files, 129 symbols):

| Metric | Score |
|---|---|
| Tool Precision | **92%** |
| Tool Recall | **91%** |
| Search MRR (vs keyword baseline) | **0.475 vs 0.350 (1.4× uplift)** |
| `blast_radius` latency | **26ms** |
| `find_dead_code` latency | **20ms** |
| Index throughput | **14.6 files/sec** |
| Head-to-head vs keyword (7 questions) | **Cassetto 5 – 1** |

Full benchmark report with raw outputs: [`eval/benchmark_report.html`](eval/benchmark_report.html)

---

## Setup

### Prerequisites

- **Python 3.11+**
- **[Ollama](https://ollama.com)** running locally
- **Git** installed

### Install & Index

```bash
pip install cassetto
ollama pull nomic-embed-text

cd /path/to/your/project
cassetto index .
```

This parses all source files, generates embeddings, builds call/import graphs, analyzes git history, and stores everything locally in `~/.cassetto/`.

### Connect to Your AI

```bash
cassetto setup
```

Auto-configures MCP for **Antigravity (Gemini/Claude)**, **Claude Desktop**, and **Cursor**. Restart your assistant and you're done.

---

## All 18 Tools

Your AI calls these automatically. You never need to know they exist.

### Search
| Tool | What it does |
|---|---|
| `search_code` | Hybrid BM25 + semantic search with graph-aware reranking |
| `get_repo_map` | PageRank-ranked map of the most important symbols |

### Symbol Intelligence
| Tool | What it does |
|---|---|
| `find_references` | All callers/renderers/extenders of a symbol |
| `goto_definition` | Jump to where a symbol is defined, with full source |
| `find_implementations` | Classes that extend a base class |
| `explain_symbol` | Deep profile: definition + callers + callees + PageRank |

### Graph Analysis
| Tool | What it does |
|---|---|
| `get_call_graph` | What calls this function and what it calls |
| `blast_radius` | Everything that transitively depends on a symbol |
| `find_dead_code` | Unreferenced functions (safe to delete) |
| `find_cycles` | Circular dependencies in the import graph |

### Git Intelligence
| Tool | What it does |
|---|---|
| `get_hotspots` | Riskiest files (high churn × many authors) |
| `get_change_history` | Git log per file |
| `get_ownership` | Who owns each file |
| `get_change_coupling` | Files that always change together |

### Architecture
| Tool | What it does |
|---|---|
| `get_architecture_summary` | Frameworks, layers, entry points |
| `find_entry_points` | Main files, routes, CLI commands |
| `get_imports` | Module dependency graph |
| `get_index_status` | Index health check |

---

## How It Works

```
Your Code → tree-sitter AST → Chunks (functions, classes)
                                  ↓
                    ┌─────────────┼─────────────┐
                    ↓             ↓             ↓
              LanceDB        SQLite FTS5     DuckDB
            (vectors)        (keywords)    (call graph)
                    ↓             ↓             ↓
                    └─────────────┼─────────────┘
                                  ↓
                        MCP Server (18 tools)
                                  ↓
                        Your AI Assistant
```

1. **AST Parsing** (tree-sitter) — Extracts functions, classes, methods as structured chunks across 13 languages
2. **Embeddings** (Ollama) — 768-dim semantic vectors for each chunk
3. **Hybrid Search** (LanceDB + SQLite) — Vector similarity + BM25 keyword matching, merged with Reciprocal Rank Fusion
4. **Call Graph** (DuckDB) — Who-calls-what, component renders, class inheritance, with PageRank scoring
5. **Import Graph** — Module dependencies, resolved to actual file paths
6. **Git Intelligence** — Churn rates, ownership, change coupling from git history
7. **MCP Server** (FastMCP) — Exposes everything as tools via JSON-RPC over stdio

Everything runs locally. No cloud, no API keys required.

---

## CLI Reference

```bash
cassetto index [dir]           # Index a project (default: current dir)
cassetto index . --force       # Force full re-index
cassetto index . --verbose     # Print per-file progress and phase timings
cassetto setup                 # Auto-configure MCP for your AI assistant
cassetto setup -p myproject    # Configure with specific project ID
cassetto serve                 # Start MCP server manually
cassetto search "auth flow"    # Quick search from terminal
cassetto watch .               # Watch for changes, re-index live
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CASSETTO_PROJECT_ID` | folder name | Which indexed project to query |
| `CASSETTO_DATA_DIR` | `~/.cassetto` | Where indexes are stored |
| `CASSETTO_EMBEDDING_BACKEND` | `ollama` | `ollama` or `voyage` |
| `CASSETTO_OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `CASSETTO_GIT` | `true` | Enable git analysis |

## Supported Languages

Python · JavaScript · TypeScript · JSX · TSX · Go · Rust · Java · Ruby · PHP · C# · C · C++

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions and [Good First Issues](https://github.com/shahanxd/cassetto/labels/good%20first%20issue) if you're looking for a place to start.

## License

[Apache 2.0](LICENSE)
