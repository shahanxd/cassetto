# Codebase Intelligence System — Full Implementation Plan
### A persistent, offline-first MCP server that gives LLMs structured memory of any codebase

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

## WHAT WE ARE BUILDING

A local MCP (Model Context Protocol) server that:

1. Watches a codebase for file changes
2. Parses code into structured chunks using AST analysis (Tree-sitter)
3. Creates vector embeddings of each chunk and stores them offline
4. Builds a graph of relationships between code symbols (call graph, dependency graph)
5. Exposes MCP tools that any LLM (Claude Code, Cursor, etc.) can call to query this structured knowledge
6. Updates incrementally when code changes — no full rebuilds

The end result: every time an LLM is working with the developer's codebase, it can call tools like `search_code("authentication logic")` or `get_call_graph("validateUser")` and get precise, structured answers from a locally maintained index — rather than having to re-read files from scratch every session.

**This is not a replacement for the LLM's own file reading.** It is an extension — a persistent memory layer that survives between sessions and gives the LLM structural knowledge it couldn't get from reading files alone.

---

## SYSTEM ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────┐
│                    Developer's Machine                   │
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │  Claude  │    │  MCP Server  │    │  File Watcher │  │
│  │   Code   │◄──►│  (Node.js)   │◄───│  (Chokidar)   │  │
│  │ /Cursor  │    │              │    └───────┬───────┘  │
│  └──────────┘    └──────┬───────┘            │          │
│                         │              ┌─────▼──────┐   │
│                  ┌──────▼───────┐      │ Tree-sitter│   │
│                  │  Query Layer │      │ AST Parser │   │
│                  └──────┬───────┘      └─────┬──────┘   │
│                         │                    │          │
│              ┌──────────┴──────────┐         │          │
│              │                     │         │          │
│        ┌─────▼──────┐    ┌────────▼──────┐  │          │
│        │  LanceDB   │    │     Kuzu      │◄─┘          │
│        │ (vectors)  │    │   (graph DB)  │             │
│        └────────────┘    └───────────────┘             │
└─────────────────────────────────────────────────────────┘
```

**Component responsibilities:**

| Component | Role | Language |
|---|---|---|
| MCP Server | Exposes tools to LLMs, orchestrates queries | Node.js / TypeScript |
| File Watcher | Detects file changes, triggers updates | Node.js (Chokidar) |
| AST Parser | Parses code into symbols, diffs ASTs | Python (Tree-sitter) |
| Embedding service | Creates vector embeddings from code chunks | Python (nomic-embed-code via Ollama) |
| LanceDB | Stores and queries vector embeddings | Python/Node.js |
| Kuzu | Stores and queries the code relationship graph | Python |
| Update pipeline | Coordinates incremental updates | Python |

---

## TECH STACK — EXACT CHOICES

### Why these specific tools:

**Tree-sitter** — Universal code parser. Supports 40+ languages. Extremely fast (milliseconds per file). Produces a concrete syntax tree you can diff. Used by Neovim, GitHub, Zed. Battle-tested. Alternative (custom parsers per language) is 10x more work.

**LanceDB** — Embedded vector database. No server to run. Stores data as files on disk. Fast enough for codebases up to millions of chunks. Has both Python and Node.js APIs. Alternative (Chroma, Qdrant) requires running a separate server process.

**Kuzu** — Embedded graph database. No server to run. Uses Cypher query language (same as Neo4j). Can handle millions of nodes. Designed for exactly this use case. Alternative (Neo4j) requires Docker or a paid service.

**Ollama + nomic-embed-code** — Local embedding model. Free. Private. Runs on CPU (slow but works) or GPU (fast). nomic-embed-code is specifically trained on code. Alternative (OpenAI embeddings) sends your code to a third party server — not acceptable for an offline-first tool.

**MCP (Model Context Protocol)** — Anthropic's open protocol for giving LLMs access to tools and data. Already supported by Claude Code, Cursor, and growing. This is the right integration layer — not a VS Code extension API, not a custom plugin format. MCP makes this tool LLM-agnostic.

### Dependencies to install:

```bash
# Python side
pip install tree-sitter tree-sitter-languages lancedb kuzu sentence-transformers

# Node.js side  
npm install @anthropic-ai/mcp-sdk chokidar better-sqlite3

# Ollama (local embedding model runner)
# Install from https://ollama.ai
ollama pull nomic-embed-text  # fallback if nomic-embed-code unavailable
```

---

## DATA MODELS

### IndexNode (stored in LanceDB)

Every chunk of code that gets embedded is stored as an IndexNode:

```typescript
interface IndexNode {
  id: string              // Stable hash: sha256(file_path + ":" + symbol_name)
  file: string            // Absolute path to file
  symbol: string          // Function/class/method name, or "module_level" for top-level code
  symbol_type: string     // "function" | "class" | "method" | "import" | "export" | "variable"
  chunk: string           // The actual source code text of this symbol
  start_line: number      // Line number where symbol starts
  end_line: number        // Line number where symbol ends
  language: string        // "python" | "javascript" | "typescript" | etc.
  embedding: number[]     // Vector embedding (768 dimensions for nomic-embed-code)
  ast_hash: string        // SHA256 of the AST node — used for change detection
  last_indexed: number    // Unix timestamp
  stale: boolean          // True if a dependency changed and this may be affected
  git_commit: string      // Git commit hash at time of indexing (empty if no git)
}
```

### GraphNode / GraphEdge (stored in Kuzu)

The graph tracks relationships between symbols:

```cypher
-- Node types
CREATE NODE TABLE Symbol(
  id STRING PRIMARY KEY,
  name STRING,
  file STRING,
  symbol_type STRING,
  start_line INT64,
  end_line INT64
)

-- Edge types
CREATE REL TABLE CALLS(FROM Symbol TO Symbol)        -- functionA calls functionB
CREATE REL TABLE IMPORTS(FROM Symbol TO Symbol)      -- moduleA imports from moduleB  
CREATE REL TABLE DEFINES(FROM Symbol TO Symbol)      -- classA defines methodB
CREATE REL TABLE EXTENDS(FROM Symbol TO Symbol)      -- classA extends classB
CREATE REL TABLE EXPORTS(FROM Symbol TO Symbol)      -- moduleA exports symbolB
```

### FileMetadata (stored in SQLite, simple)

Tracks which files have been indexed and their state:

```typescript
interface FileMetadata {
  path: string            // Absolute file path
  last_modified: number   // mtime from filesystem
  last_indexed: number    // When we last processed it
  file_hash: string       // SHA256 of file contents — change detection
  symbol_count: number    // How many symbols extracted
  error: string | null    // Any parse error from last attempt
}
```

---

## STAGE 1: DUMB BUT WORKING
### Goal: Semantic search over codebase via MCP. No AST, no graph.
### Time estimate: 1–2 weeks
### Success criteria: LLM can call `search_code("user authentication")` and get relevant code back

---

### Stage 1, Step 1: Project scaffold

Create this directory structure:

```
codebase-intelligence/
├── mcp-server/           # Node.js MCP server
│   ├── src/
│   │   ├── index.ts      # MCP server entry point
│   │   ├── tools.ts      # Tool definitions
│   │   └── client.ts     # Client that talks to Python indexer
│   ├── package.json
│   └── tsconfig.json
├── indexer/              # Python indexing pipeline
│   ├── main.py           # CLI entry point: index a directory
│   ├── chunker.py        # Split files into chunks (naive at first)
│   ├── embedder.py       # Create embeddings via Ollama
│   ├── store.py          # LanceDB interface
│   └── watcher.py        # File change watcher
├── shared/
│   └── protocol.py       # Shared data structures
└── README.md
```

### Stage 1, Step 2: Naive chunker (chunker.py)

At this stage, don't use Tree-sitter. Just split files by a simple heuristic: every function-looking block. For Python, split on `def ` and `class `. For JS/TS, split on `function `, `const `, `class `. This is imperfect but good enough for Stage 1.

```python
# chunker.py — Stage 1 naive version
import hashlib
from pathlib import Path
from dataclasses import dataclass

SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java'}

@dataclass
class Chunk:
    id: str
    file: str
    symbol: str
    chunk: str
    start_line: int
    end_line: int
    language: str

def chunk_file(file_path: str) -> list[Chunk]:
    path = Path(file_path)
    if path.suffix not in SUPPORTED_EXTENSIONS:
        return []
    
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return []
    
    lines = content.split('\n')
    language = path.suffix.lstrip('.')
    chunks = []
    
    # Find split points — lines that look like symbol definitions
    split_lines = [0]
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (stripped.startswith('def ') or 
            stripped.startswith('class ') or
            stripped.startswith('function ') or
            stripped.startswith('const ') or
            stripped.startswith('export function') or
            stripped.startswith('export const') or
            stripped.startswith('async function')):
            split_lines.append(i)
    split_lines.append(len(lines))
    
    # Create chunks from split points
    for i in range(len(split_lines) - 1):
        start = split_lines[i]
        end = split_lines[i + 1]
        chunk_lines = lines[start:end]
        chunk_text = '\n'.join(chunk_lines).strip()
        
        if len(chunk_text) < 20:  # Skip trivially small chunks
            continue
        
        # Try to extract symbol name from first line
        first_line = chunk_lines[0].strip() if chunk_lines else ''
        symbol = _extract_symbol_name(first_line) or f"chunk_{start}"
        
        chunk_id = hashlib.sha256(f"{file_path}:{symbol}:{start}".encode()).hexdigest()[:16]
        
        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol=symbol,
            chunk=chunk_text,
            start_line=start,
            end_line=end,
            language=language
        ))
    
    return chunks

def _extract_symbol_name(line: str) -> str | None:
    for keyword in ['def ', 'class ', 'function ', 'const ', 'async function ']:
        if keyword in line:
            after = line.split(keyword, 1)[1]
            name = after.split('(')[0].split(':')[0].split(' ')[0].strip()
            return name if name else None
    return None
```

### Stage 1, Step 3: Embedder (embedder.py)

Uses Ollama running locally. Ollama must be installed and running (`ollama serve`).

```python
# embedder.py
import requests
import json

OLLAMA_URL = "http://localhost:11434"
MODEL = "nomic-embed-text"  # upgrade to nomic-embed-code if available

def embed_text(text: str) -> list[float]:
    """Get embedding vector for a single text."""
    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": MODEL, "prompt": text}
    )
    response.raise_for_status()
    return response.json()["embedding"]

def embed_batch(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """Embed multiple texts. Ollama doesn't support true batching so we loop."""
    embeddings = []
    for i, text in enumerate(texts):
        if i % 10 == 0:
            print(f"  Embedding {i}/{len(texts)}...")
        embeddings.append(embed_text(text))
    return embeddings

def check_ollama_running() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False
```

### Stage 1, Step 4: LanceDB store (store.py)

```python
# store.py
import lancedb
import numpy as np
from pathlib import Path
from dataclasses import asdict
from chunker import Chunk

DB_PATH = Path.home() / ".codebase-intelligence" / "db"

def get_db(project_id: str):
    db_path = DB_PATH / project_id
    db_path.mkdir(parents=True, exist_ok=True)
    return lancedb.connect(str(db_path))

def store_chunks(project_id: str, chunks: list[Chunk], embeddings: list[list[float]]):
    db = get_db(project_id)
    
    records = []
    for chunk, embedding in zip(chunks, embeddings):
        record = asdict(chunk)
        record['vector'] = embedding
        record['stale'] = False
        record['ast_hash'] = ''
        records.append(record)
    
    if "chunks" in db.table_names():
        table = db.open_table("chunks")
        table.add(records)
    else:
        table = db.create_table("chunks", records)
    
    return len(records)

def search_similar(project_id: str, query_embedding: list[float], limit: int = 10) -> list[dict]:
    db = get_db(project_id)
    if "chunks" not in db.table_names():
        return []
    
    table = db.open_table("chunks")
    results = table.search(query_embedding).limit(limit).to_list()
    return results

def delete_file_chunks(project_id: str, file_path: str):
    db = get_db(project_id)
    if "chunks" not in db.table_names():
        return
    table = db.open_table("chunks")
    table.delete(f"file = '{file_path}'")

def get_all_indexed_files(project_id: str) -> list[str]:
    db = get_db(project_id)
    if "chunks" not in db.table_names():
        return []
    table = db.open_table("chunks")
    return list(set(r['file'] for r in table.to_list()))
```

### Stage 1, Step 5: Main indexing entry point (main.py)

```python
# main.py
import sys
import json
import argparse
from pathlib import Path
from chunker import chunk_file, SUPPORTED_EXTENSIONS
from embedder import embed_text, embed_batch, check_ollama_running
from store import store_chunks, search_similar, delete_file_chunks

def index_directory(directory: str, project_id: str):
    """Walk a directory and index all supported files."""
    if not check_ollama_running():
        print("ERROR: Ollama is not running. Start it with: ollama serve")
        sys.exit(1)
    
    root = Path(directory)
    all_files = []
    
    # Collect all supported files, skip common noise dirs
    skip_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', 
                 'dist', 'build', '.next', '.nuxt', 'coverage'}
    
    for path in root.rglob('*'):
        if any(skip in path.parts for skip in skip_dirs):
            continue
        if path.is_file() and path.suffix in SUPPORTED_EXTENSIONS:
            all_files.append(str(path))
    
    print(f"Found {len(all_files)} files to index")
    
    total_chunks = 0
    for i, file_path in enumerate(all_files):
        print(f"[{i+1}/{len(all_files)}] {file_path}")
        
        chunks = chunk_file(file_path)
        if not chunks:
            continue
        
        texts = [f"File: {c.file}\nSymbol: {c.symbol}\n\n{c.chunk}" for c in chunks]
        embeddings = embed_batch(texts)
        
        stored = store_chunks(project_id, chunks, embeddings)
        total_chunks += stored
        print(f"  → {stored} chunks indexed")
    
    print(f"\nDone. {total_chunks} total chunks indexed for project '{project_id}'")

def search(project_id: str, query: str, limit: int = 10):
    """Search the index and print results as JSON."""
    from embedder import embed_text
    query_embedding = embed_text(query)
    results = search_similar(project_id, query_embedding, limit)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    
    index_parser = subparsers.add_parser('index')
    index_parser.add_argument('directory')
    index_parser.add_argument('--project', required=True)
    
    search_parser = subparsers.add_parser('search')
    search_parser.add_argument('query')
    search_parser.add_argument('--project', required=True)
    search_parser.add_argument('--limit', type=int, default=10)
    
    args = parser.parse_args()
    
    if args.command == 'index':
        index_directory(args.directory, args.project)
    elif args.command == 'search':
        search(args.project, args.query, args.limit)
    else:
        parser.print_help()
```

### Stage 1, Step 6: MCP Server (mcp-server/src/index.ts)

The MCP server is a Node.js process that communicates with Claude Code via stdio. It calls the Python indexer as a subprocess for queries.

```typescript
// mcp-server/src/index.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { execSync } from "child_process";
import * as path from "path";

const server = new Server(
  { name: "codebase-intelligence", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

// Config — these will be passed via environment variables
const PROJECT_ID = process.env.CI_PROJECT_ID || "default";
const INDEXER_PATH = process.env.CI_INDEXER_PATH || path.join(__dirname, "../../indexer/main.py");

function callIndexer(command: string, args: Record<string, string>): any {
  const argStr = Object.entries(args)
    .map(([k, v]) => `--${k} "${v}"`)
    .join(" ");
  
  const result = execSync(
    `python3 ${INDEXER_PATH} ${command} ${argStr}`,
    { maxBuffer: 10 * 1024 * 1024 } // 10MB buffer for large results
  );
  
  return JSON.parse(result.toString());
}

// Define available tools
server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "search_code",
      description: "Search the codebase for code semantically similar to a query. Returns relevant code chunks with file locations. Use this when you need to find code related to a concept, feature, or functionality.",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "Natural language description of what you're looking for" },
          limit: { type: "number", description: "Max results to return (default 10)", default: 10 }
        },
        required: ["query"]
      }
    }
  ]
}));

// Handle tool calls
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  
  if (name === "search_code") {
    const { query, limit = 10 } = args as { query: string; limit?: number };
    
    const results = callIndexer("search", { 
      query, 
      project: PROJECT_ID,
      limit: String(limit)
    });
    
    const formatted = results.map((r: any) => 
      `FILE: ${r.file} (lines ${r.start_line}-${r.end_line})\nSYMBOL: ${r.symbol}\n\`\`\`\n${r.chunk}\n\`\`\``
    ).join("\n\n---\n\n");
    
    return {
      content: [{ type: "text", text: formatted || "No results found." }]
    };
  }
  
  throw new Error(`Unknown tool: ${name}`);
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch(console.error);
```

### Stage 1, Step 7: Register with Claude Code

Add to your Claude Code config (`~/.claude/mcp_config.json`):

```json
{
  "mcpServers": {
    "codebase-intelligence": {
      "command": "node",
      "args": ["/path/to/codebase-intelligence/mcp-server/dist/index.js"],
      "env": {
        "CI_PROJECT_ID": "my-project",
        "CI_INDEXER_PATH": "/path/to/codebase-intelligence/indexer/main.py"
      }
    }
  }
}
```

### Stage 1 validation checklist:
- [ ] `python main.py index ./my-project --project test` runs without errors
- [ ] `python main.py search "user authentication" --project test` returns relevant results
- [ ] MCP server starts without errors
- [ ] Claude Code can call `search_code` and get results
- [ ] Results include file paths and line numbers

---

## STAGE 2: AST-BASED CHUNKING
### Goal: Replace naive chunker with Tree-sitter. Better chunks = better embeddings.
### Time estimate: 1–2 weeks
### Success criteria: Chunks map exactly to functions/classes. No more splitting mid-function.

---

### Stage 2, Step 1: Install Tree-sitter

```bash
pip install tree-sitter==0.21.3
pip install tree-sitter-python tree-sitter-javascript tree-sitter-typescript
```

Note: Tree-sitter Python bindings changed significantly at version 0.21. Use 0.21.x for this implementation. The API is different from 0.20.x — if you find conflicting documentation online, check the version.

### Stage 2, Step 2: AST chunker (ast_chunker.py)

```python
# ast_chunker.py — replaces chunker.py
import hashlib
from pathlib import Path
from dataclasses import dataclass
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript

# Symbol node types per language — what counts as a "chunk"
SYMBOL_TYPES = {
    'python': ['function_definition', 'class_definition', 'decorated_definition'],
    'javascript': ['function_declaration', 'class_declaration', 'arrow_function', 
                   'method_definition', 'variable_declaration'],
    'typescript': ['function_declaration', 'class_declaration', 'method_definition',
                   'interface_declaration', 'type_alias_declaration', 'variable_declaration'],
}

LANGUAGE_MAP = {
    '.py': ('python', tspython.language()),
    '.js': ('javascript', tsjavascript.language()),
    '.ts': ('typescript', tstypescript.language_typescript()),
    '.tsx': ('typescript', tstypescript.language_tsx()),
    '.jsx': ('javascript', tsjavascript.language()),
}

@dataclass
class Chunk:
    id: str
    file: str
    symbol: str
    symbol_type: str
    chunk: str
    start_line: int
    end_line: int
    language: str
    ast_hash: str   # NEW: hash of AST node for change detection

def chunk_file(file_path: str) -> list[Chunk]:
    path = Path(file_path)
    if path.suffix not in LANGUAGE_MAP:
        return []
    
    language_name, language = LANGUAGE_MAP[path.suffix]
    
    try:
        content = path.read_bytes()
        source = content.decode('utf-8', errors='ignore')
    except Exception:
        return []
    
    parser = Parser()
    parser.set_language(Language(language))
    tree = parser.parse(content)
    
    chunks = []
    symbol_types = SYMBOL_TYPES.get(language_name, [])
    
    _extract_nodes(tree.root_node, source, file_path, language_name, symbol_types, chunks)
    
    # If no symbols found (e.g. config file), treat whole file as one chunk
    if not chunks:
        file_hash = hashlib.sha256(content).hexdigest()
        chunk_id = hashlib.sha256(f"{file_path}:module_level".encode()).hexdigest()[:16]
        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol='module_level',
            symbol_type='module',
            chunk=source[:4000],  # Cap at 4000 chars for modules
            start_line=0,
            end_line=source.count('\n'),
            language=language_name,
            ast_hash=file_hash[:16]
        ))
    
    return chunks

def _extract_nodes(node, source: str, file_path: str, language: str, 
                   symbol_types: list[str], chunks: list[Chunk]):
    """Recursively walk AST and extract symbol nodes."""
    if node.type in symbol_types:
        chunk_text = source[node.start_byte:node.end_byte]
        symbol_name = _get_symbol_name(node, source)
        
        # Hash the AST node bytes for change detection
        ast_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:16]
        chunk_id = hashlib.sha256(f"{file_path}:{symbol_name}:{node.start_point[0]}".encode()).hexdigest()[:16]
        
        chunks.append(Chunk(
            id=chunk_id,
            file=file_path,
            symbol=symbol_name,
            symbol_type=node.type,
            chunk=chunk_text,
            start_line=node.start_point[0],
            end_line=node.end_point[0],
            language=language,
            ast_hash=ast_hash
        ))
        # Don't recurse into found symbols — avoid nested function duplicates
        return
    
    for child in node.children:
        _extract_nodes(child, source, file_path, language, symbol_types, chunks)

def _get_symbol_name(node, source: str) -> str:
    """Extract the name identifier from a symbol node."""
    for child in node.children:
        if child.type in ('identifier', 'property_identifier', 'name'):
            return source[child.start_byte:child.end_byte]
    return f"anonymous_{node.start_point[0]}"

def diff_chunks(old_chunks: list[Chunk], new_chunks: list[Chunk]) -> tuple[list[Chunk], list[Chunk], list[str]]:
    """
    Compare old and new chunks for a file.
    Returns: (added_chunks, modified_chunks, deleted_chunk_ids)
    """
    old_by_id = {c.id: c for c in old_chunks}
    new_by_id = {c.id: c for c in new_chunks}
    
    added = [c for cid, c in new_by_id.items() if cid not in old_by_id]
    deleted = [cid for cid in old_by_id if cid not in new_by_id]
    modified = [c for cid, c in new_by_id.items() 
                if cid in old_by_id and old_by_id[cid].ast_hash != c.ast_hash]
    
    return added, modified, deleted
```

### Stage 2, Step 3: Update main.py to use ast_chunker

Replace `from chunker import chunk_file` with `from ast_chunker import chunk_file`. Everything else stays the same. This is intentional — the interface is identical.

### Stage 2 validation checklist:
- [ ] Chunks now correspond exactly to functions and classes
- [ ] Chunks have `ast_hash` populated
- [ ] Nested functions don't create duplicate chunks
- [ ] Files with no recognizable symbols still get indexed as one chunk
- [ ] Search quality is noticeably better than Stage 1

---

## STAGE 3: GRAPH DATABASE
### Goal: Build and query a call graph. LLM can ask "what does this function affect?"
### Time estimate: 2–3 weeks
### Success criteria: `get_call_graph("functionName")` returns callers and callees

---

### Stage 3, Step 1: Extract relationships (graph_extractor.py)

```python
# graph_extractor.py
from tree_sitter import Language, Parser
from dataclasses import dataclass
from ast_chunker import LANGUAGE_MAP

@dataclass
class Relationship:
    from_symbol: str
    from_file: str
    to_symbol: str
    to_file: str  # empty if cross-file (resolved later)
    relationship_type: str  # "calls" | "imports" | "extends" | "defines"

def extract_relationships(file_path: str, all_symbols: dict[str, str]) -> list[Relationship]:
    """
    Extract all relationships in a file.
    all_symbols: dict mapping symbol_name -> file_path (for cross-file resolution)
    """
    from pathlib import Path
    path = Path(file_path)
    if path.suffix not in LANGUAGE_MAP:
        return []
    
    language_name, language = LANGUAGE_MAP[path.suffix]
    content = path.read_bytes()
    source = content.decode('utf-8', errors='ignore')
    
    parser = Parser()
    parser.set_language(Language(language))
    tree = parser.parse(content)
    
    relationships = []
    
    if language_name == 'python':
        _extract_python_relationships(tree.root_node, source, file_path, all_symbols, relationships)
    elif language_name in ('javascript', 'typescript'):
        _extract_js_relationships(tree.root_node, source, file_path, all_symbols, relationships)
    
    return relationships

def _extract_python_relationships(node, source, file_path, all_symbols, relationships):
    """Extract Python-specific relationships: function calls, imports, class inheritance."""
    current_function = None
    
    def walk(node):
        nonlocal current_function
        
        if node.type == 'function_definition':
            prev = current_function
            current_function = source[node.children[1].start_byte:node.children[1].end_byte]
            for child in node.children:
                walk(child)
            current_function = prev
            return
        
        if node.type == 'call' and current_function:
            # Extract function name being called
            func_node = node.children[0]
            called = source[func_node.start_byte:func_node.end_byte].split('(')[0]
            called_base = called.split('.')[-1]  # Handle method.calls
            
            to_file = all_symbols.get(called_base, '')
            relationships.append(Relationship(
                from_symbol=current_function,
                from_file=file_path,
                to_symbol=called_base,
                to_file=to_file,
                relationship_type='calls'
            ))
        
        if node.type == 'import_from_statement':
            module = ''
            for child in node.children:
                if child.type == 'dotted_name':
                    module = source[child.start_byte:child.end_byte]
                    break
            relationships.append(Relationship(
                from_symbol='module_level',
                from_file=file_path,
                to_symbol=module,
                to_file='',
                relationship_type='imports'
            ))
        
        for child in node.children:
            walk(child)
    
    walk(node)

def _extract_js_relationships(node, source, file_path, all_symbols, relationships):
    """Extract JS/TS relationships — similar pattern to Python version."""
    # Implementation follows same pattern as Python version
    # Focus on: call_expression, import_declaration, class_heritage
    pass  # Implement similarly to Python version
```

### Stage 3, Step 2: Kuzu graph store (graph_store.py)

```python
# graph_store.py
import kuzu
from pathlib import Path
from graph_extractor import Relationship

DB_PATH = Path.home() / ".codebase-intelligence" / "graph"

def get_db(project_id: str):
    db_path = DB_PATH / project_id
    db_path.mkdir(parents=True, exist_ok=True)
    db = kuzu.Database(str(db_path))
    conn = kuzu.Connection(db)
    _initialize_schema(conn)
    return conn

def _initialize_schema(conn):
    """Create tables if they don't exist."""
    try:
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Symbol(
                id STRING PRIMARY KEY,
                name STRING,
                file STRING,
                symbol_type STRING
            )
        """)
        conn.execute("CREATE REL TABLE IF NOT EXISTS CALLS(FROM Symbol TO Symbol)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS IMPORTS(FROM Symbol TO Symbol)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS DEFINES(FROM Symbol TO Symbol)")
        conn.execute("CREATE REL TABLE IF NOT EXISTS EXTENDS(FROM Symbol TO Symbol)")
    except Exception:
        pass  # Tables already exist

def store_symbol(conn, symbol_id: str, name: str, file: str, symbol_type: str):
    conn.execute(
        "MERGE (s:Symbol {id: $id}) SET s.name = $name, s.file = $file, s.symbol_type = $symbol_type",
        {"id": symbol_id, "name": name, "file": file, "symbol_type": symbol_type}
    )

def store_relationship(conn, rel: Relationship):
    from_id = f"{rel.from_file}:{rel.from_symbol}"
    to_id = f"{rel.to_file}:{rel.to_symbol}" if rel.to_file else f"external:{rel.to_symbol}"
    
    rel_type = rel.relationship_type.upper()
    conn.execute(f"""
        MATCH (a:Symbol {{id: $from_id}}), (b:Symbol {{id: $to_id}})
        MERGE (a)-[:{rel_type}]->(b)
    """, {"from_id": from_id, "to_id": to_id})

def get_call_graph(conn, symbol_name: str, depth: int = 2) -> dict:
    """Get functions that call this symbol and functions it calls."""
    
    # Who calls this symbol
    callers = conn.execute("""
        MATCH (caller:Symbol)-[:CALLS]->(target:Symbol {name: $name})
        RETURN caller.name, caller.file
        LIMIT 20
    """, {"name": symbol_name}).get_as_df()
    
    # What this symbol calls
    callees = conn.execute("""
        MATCH (source:Symbol {name: $name})-[:CALLS]->(target:Symbol)
        RETURN target.name, target.file
        LIMIT 20
    """, {"name": symbol_name}).get_as_df()
    
    return {
        "symbol": symbol_name,
        "called_by": callers.to_dict('records'),
        "calls": callees.to_dict('records')
    }

def get_dependents(conn, file_path: str) -> list[str]:
    """Get all files that depend on (import) this file."""
    result = conn.execute("""
        MATCH (dependent:Symbol)-[:IMPORTS]->(target:Symbol {file: $file})
        RETURN DISTINCT dependent.file
    """, {"file": file_path}).get_as_df()
    return result['dependent.file'].tolist()

def delete_file_nodes(conn, file_path: str):
    """Remove all nodes from a file (called when file is deleted or re-indexed)."""
    conn.execute("MATCH (s:Symbol {file: $file}) DETACH DELETE s", {"file": file_path})
```

### Stage 3, Step 3: New MCP tools to expose

Add these tools to the MCP server alongside `search_code`:

```typescript
// Add to tools list in mcp-server/src/index.ts

{
  name: "get_call_graph",
  description: "Get the call graph for a specific function or class. Shows what it calls and what calls it. Use this when you need to understand the impact of changing a function, or trace how data flows through the codebase.",
  inputSchema: {
    type: "object",
    properties: {
      symbol_name: { type: "string", description: "The function or class name to look up" }
    },
    required: ["symbol_name"]
  }
},
{
  name: "what_depends_on",
  description: "Find all files and symbols that depend on a given file or symbol. Use this before making changes to understand what might break.",
  inputSchema: {
    type: "object", 
    properties: {
      file_path: { type: "string", description: "Relative path to the file" }
    },
    required: ["file_path"]
  }
},
{
  name: "find_symbol",
  description: "Find where a specific function, class, or variable is defined. Returns exact file path and line number.",
  inputSchema: {
    type: "object",
    properties: {
      symbol_name: { type: "string", description: "Symbol name to find" }
    },
    required: ["symbol_name"]
  }
}
```

### Stage 3 validation checklist:
- [ ] `get_call_graph("functionName")` returns callers and callees
- [ ] `what_depends_on("src/auth.py")` returns all files that import from auth.py
- [ ] Graph survives process restart (persisted to disk)
- [ ] Graph is consistent with actual code (spot-check manually)

---

## STAGE 4: INCREMENTAL UPDATES
### Goal: File changes trigger targeted updates, not full rebuilds.
### Time estimate: 2–3 weeks
### Success criteria: Saving a file updates only affected chunks within 1 second

---

### Stage 4, Step 1: File watcher (watcher.py)

```python
# watcher.py
import time
import json
import hashlib
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from ast_chunker import chunk_file, diff_chunks, LANGUAGE_MAP
from embedder import embed_text
from store import store_chunks, delete_file_chunks, get_chunks_for_file
from graph_store import get_db as get_graph_db, store_symbol, store_relationship, delete_file_nodes, get_dependents
from graph_extractor import extract_relationships

# pip install watchdog

DEBOUNCE_SECONDS = 0.3

class CodeChangeHandler(FileSystemEventHandler):
    def __init__(self, project_id: str, root: str):
        self.project_id = project_id
        self.root = root
        self.pending = {}  # file_path -> timestamp
        
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
        """Debounce: record the change but don't process immediately."""
        suffix = Path(path).suffix
        if suffix in LANGUAGE_MAP:
            self.pending[path] = time.time()
    
    def _handle_delete(self, path: str):
        print(f"[DELETE] {path}")
        delete_file_chunks(self.project_id, path)
        conn = get_graph_db(self.project_id)
        delete_file_nodes(conn, path)
    
    def flush_pending(self):
        """Called on a timer — process all debounced changes."""
        now = time.time()
        to_process = [p for p, t in self.pending.items() 
                      if now - t >= DEBOUNCE_SECONDS]
        
        for path in to_process:
            del self.pending[path]
            self._handle_change(path)
    
    def _handle_change(self, file_path: str):
        print(f"[CHANGE] {file_path}")
        
        # 1. Get existing chunks for this file
        old_chunks = get_chunks_for_file(self.project_id, file_path)
        
        # 2. Re-parse the file
        new_chunks = chunk_file(file_path)
        
        # 3. Diff — only process what actually changed
        added, modified, deleted_ids = diff_chunks(old_chunks, new_chunks)
        
        print(f"  → {len(added)} added, {len(modified)} modified, {len(deleted_ids)} deleted")
        
        # 4. Delete removed/modified chunks from vector store
        ids_to_delete = deleted_ids + [c.id for c in modified]
        for chunk_id in ids_to_delete:
            delete_file_chunks(self.project_id, file_path, chunk_id=chunk_id)
        
        # 5. Re-embed and store new/modified chunks
        chunks_to_store = added + modified
        if chunks_to_store:
            texts = [f"File: {c.file}\nSymbol: {c.symbol}\n\n{c.chunk}" for c in chunks_to_store]
            from embedder import embed_batch
            embeddings = embed_batch(texts)
            store_chunks(self.project_id, chunks_to_store, embeddings)
        
        # 6. Update graph
        conn = get_graph_db(self.project_id)
        delete_file_nodes(conn, file_path)  # Remove old graph nodes
        
        all_symbols = {}  # TODO: load from index for cross-file resolution
        rels = extract_relationships(file_path, all_symbols)
        for rel in rels:
            store_relationship(conn, rel)
        
        # 7. Mark dependents as stale
        dependents = get_dependents(conn, file_path)
        if dependents:
            print(f"  → {len(dependents)} dependent files may be affected: {dependents[:3]}")

def watch(directory: str, project_id: str):
    handler = CodeChangeHandler(project_id, directory)
    observer = Observer()
    observer.schedule(handler, directory, recursive=True)
    observer.start()
    
    print(f"Watching {directory} for changes (project: {project_id})")
    
    try:
        while True:
            time.sleep(0.1)
            handler.flush_pending()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

### Stage 4, Step 2: Run watcher as background process

The watcher should run as a background daemon while the developer is working:

```bash
# Start watcher (run in background)
python watcher.py /path/to/project --project my-project &

# Or as a proper daemon with auto-restart
# Use PM2, supervisord, or a simple shell script
```

Add a convenience CLI command to main.py:

```python
# In main.py argparse setup
watch_parser = subparsers.add_parser('watch')
watch_parser.add_argument('directory')
watch_parser.add_argument('--project', required=True)

# In main execution
elif args.command == 'watch':
    from watcher import watch
    watch(args.directory, args.project)
```

### Stage 4, Step 3: Stale flag propagation

When a file changes, files that depend on it may have stale graph data. Mark them:

```python
# In store.py — add this function
def mark_stale(project_id: str, file_path: str):
    """Mark all chunks from a file as stale."""
    db = get_db(project_id)
    table = db.open_table("chunks")
    # LanceDB update syntax
    table.update(where=f"file = '{file_path}'", values={"stale": True})

def get_stale_files(project_id: str) -> list[str]:
    db = get_db(project_id)
    if "chunks" not in db.table_names():
        return []
    table = db.open_table("chunks")
    stale = [r for r in table.to_list() if r.get('stale', False)]
    return list(set(r['file'] for r in stale))
```

The MCP server can expose a `get_index_status` tool that tells the LLM which files might be stale:

```typescript
{
  name: "get_index_status",
  description: "Check the health of the codebase index. Returns stale files and last update time. Call this if you suspect the index may be out of date.",
  inputSchema: { type: "object", properties: {} }
}
```

### Stage 4 validation checklist:
- [ ] Saving a file triggers an update within 1 second
- [ ] Only changed chunks are re-embedded (check logs)
- [ ] Deleted functions are removed from the index
- [ ] LLM can call `get_index_status` and see fresh data
- [ ] Watcher survives file renames without errors

---

## ERROR HANDLING AND EDGE CASES

Document these as they come up. Known ones to handle:

**Parse failures** — Tree-sitter is resilient but can produce partial trees on syntax errors. Always check `tree.root_node.has_error` and log it, but don't crash. Store what was parseable.

**Binary files** — Skip files that fail UTF-8 decode. Add to skip list.

**Very large files** — Cap chunk size at 8000 characters. Split oversized functions at logical boundaries (inner functions, blank lines).

**Symlinks** — Resolve to real paths before indexing to avoid duplicates.

**Monorepos** — Support multiple `--project` IDs pointing at different subdirectories of the same repo.

**Ollama not running** — MCP tool should return a clear error message rather than crashing, so the LLM can tell the user.

**Empty repos** — Handle gracefully. index command should report "0 files found" not crash.

---

## TESTING STRATEGY

Test each stage with a real open-source project. Good test subjects:
- **Small**: https://github.com/pallets/flask (Python, well-structured)
- **Medium**: https://github.com/expressjs/express (JS, good call graph)
- **Large**: https://github.com/microsoft/vscode (TS, stress test)

For each stage, manually verify:
1. Spot-check 5 search results for relevance
2. Verify call graph for 3 known functions
3. Time the update after changing a file
4. Confirm stale files are flagged after a change

---

## THINGS TO BUILD LATER (NOT NOW)

- Web UI for browsing the index
- Support for Go, Rust, Java (Tree-sitter supports them — just add to LANGUAGE_MAP)
- Semantic diff between git commits
- Export graph as visualization
- Integration tests
- Performance benchmarks
- VS Code extension for easier setup

Don't build any of these until all 4 stages are done and tested.

---

## WHEN YOU GET STUCK

If you're stuck on a specific component, describe:
1. What you expected to happen
2. What actually happened (paste the error)
3. Which step you're on

Common traps:
- **Tree-sitter API confusion**: Version matters. Check `tree_sitter.__version__`. This plan uses 0.21.x.
- **LanceDB schema changes**: If you change the IndexNode schema, delete the DB and re-index. LanceDB doesn't do schema migrations.
- **MCP server not connecting**: Check Claude Code logs. Usually a path or env var issue.
- **Ollama timeouts**: Embedding is slow on CPU. Increase timeout in requests calls. Consider batching differently.
- **Kuzu connection errors**: Only one process can write to Kuzu at a time. Make sure watcher and MCP server don't both try to write simultaneously.
