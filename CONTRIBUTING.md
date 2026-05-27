# Contributing to Cassetto

Thanks for your interest in contributing! Cassetto is a solo project that welcomes community help.

## Quick Setup

```bash
# Clone and install in dev mode
git clone https://github.com/shahanxd/cassetto.git
cd cassetto
pip install -e ".[dev]"

# You'll also need Ollama running for full tests
ollama pull nomic-embed-text

# Run the test suite
pytest tests/ -v
```

## How to Contribute

1. **Find an issue** — Check [Good First Issues](https://github.com/shahanxd/cassetto/labels/good%20first%20issue) if you're new
2. **Fork the repo** and create a branch from `main`
3. **Make your changes** — follow existing code style (no linter config, just match the patterns)
4. **Run tests** — `pytest tests/ -v` should pass
5. **Submit a PR** — describe what you changed and why

## Project Structure

The entire codebase is 12 Python files. Here's what each does:

| File | Purpose |
|---|---|
| `server.py` | MCP server — 18 tools the AI calls |
| `indexer.py` | CLI entry point (`cassetto index`, `cassetto setup`, etc.) |
| `ast_chunker.py` | Tree-sitter parsing → code chunks |
| `embedder.py` | Text → 768-dim vectors (Ollama/Voyage) |
| `store.py` | LanceDB + SQLite FTS5 hybrid search |
| `graph_store.py` | DuckDB call graph, imports, git data |
| `graph_extractor.py` | AST → call/extends/renders edges |
| `import_extractor.py` | Import statement extraction |
| `git_intel.py` | Git history analysis (churn, coupling) |
| `architecture.py` | Framework/layer detection |
| `watcher.py` | Live file watcher for incremental updates |
| `config.py` | All configuration and env var overrides |

## What We Need Help With

- **New language support** — Adding grammars to `ast_chunker.py`
- **New MCP tools** — Adding tools to `server.py`
- **Performance** — Caching, batch optimization
- **Error handling** — Better messages when things go wrong
- **Documentation** — Examples, tutorials, blog posts

## Code Style

- No specific formatter enforced — just match the existing style
- Use docstrings on public functions
- Keep functions focused — one function, one job
- Preserve existing comments when editing

## Running Benchmarks

```bash
# Requires an indexed project (e.g. sparrow)
python eval/benchmark.py

# Generate HTML report
python eval/benchmark_report.py
```

## Questions?

Open a [GitHub Issue](https://github.com/shahanxd/cassetto/issues) or start a [Discussion](https://github.com/shahanxd/cassetto/discussions).
