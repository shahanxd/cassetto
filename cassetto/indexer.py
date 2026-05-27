"""
Cassetto — CLI entry point.

    cassetto index <dir> --project <id>     # full index
    cassetto search <query> --project <id>  # quick search
    cassetto watch <dir> --project <id>     # live updates
"""
import sys
import time
import hashlib
import argparse
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from .config import SKIP_DIRS, SUPPORTED_EXTENSIONS, GIT_ENABLED


def index_directory(directory: str, project_id: str, force: bool = False):
    """Full index of a directory: parse, embed, store, build graph."""
    from .ast_chunker import chunk_file
    from .embedder import embed_batch, check_embedding_ready
    from .store import (store_chunks, delete_file_chunks, update_file_metadata,
                       get_file_metadata)
    from .graph_store import (get_conn as get_graph_conn, upsert_symbol,
                             upsert_relationship, delete_file_symbols,
                             delete_file_imports, upsert_import,
                             resolve_symbol_name, update_pagerank_scores,
                             store_git_churn, store_git_coupling)
    from .graph_extractor import extract_relationships
    from .import_extractor import extract_imports, resolve_import_to_file

    ok, msg = check_embedding_ready()
    if not ok:
        print(f"ERROR: {msg}")
        sys.exit(1)
    print(f"Embedding backend: {msg}")

    root = Path(directory).resolve()
    if not root.exists():
        print(f"ERROR: Directory not found: {root}")
        sys.exit(1)

    all_files = []
    for path in root.rglob('*'):
        if any(skip in path.parts for skip in SKIP_DIRS):
            continue
        if path.is_file() and path.suffix in SUPPORTED_EXTENSIONS:
            all_files.append(str(path))

    print(f"Found {len(all_files)} files to index in {root}")
    total_chunks = 0
    total_rels = 0
    total_imports = 0
    errors = 0
    skipped = 0
    start_time = time.time()

    graph_conn = get_graph_conn(project_id)

    # we collect relationships first, then resolve them all at the end.
    pending_rels = []
    pending_imports = []

    for i, file_path in enumerate(all_files):
        # ── incremental indexing: skip unchanged files ──
        if not force:
            try:
                current_hash = hashlib.sha256(
                    Path(file_path).read_bytes()
                ).hexdigest()[:16]
                stored = get_file_metadata(project_id, file_path)
                if stored and stored['file_hash'] == current_hash:
                    skipped += 1
                    continue
            except Exception:
                pass

        print(f"[{i + 1}/{len(all_files)}] {file_path}")
        try:
            chunks = chunk_file(file_path)
            if not chunks:
                continue

            # embed and store in LanceDB + SQLite
            texts = [
                f"File: {c.file}\nSymbol: {c.symbol} ({c.symbol_type})\n\n{c.chunk}"
                for c in chunks
            ]
            embeddings = embed_batch(texts)
            delete_file_chunks(project_id, file_path)
            store_chunks(project_id, chunks, embeddings)
            total_chunks += len(chunks)

            # build graph nodes
            delete_file_symbols(graph_conn, file_path)
            for chunk in chunks:
                upsert_symbol(graph_conn, chunk)

            # extract call + inheritance + JSX relationships (resolved later)
            rels = extract_relationships(file_path, chunks)
            pending_rels.extend(rels)

            # extract imports
            delete_file_imports(graph_conn, file_path)
            imports = extract_imports(file_path)
            for imp in imports:
                upsert_import(graph_conn, imp)
            pending_imports.extend(imports)
            total_imports += len(imports)

            # track file metadata for staleness detection
            file_content = Path(file_path).read_bytes()
            file_hash = hashlib.sha256(file_content).hexdigest()[:16]
            update_file_metadata(
                project_id, file_path,
                last_modified=Path(file_path).stat().st_mtime,
                file_hash=file_hash,
                symbol_count=len(chunks),
            )

            print(f"  -> {len(chunks)} chunks, {len(rels)} rels, {len(imports)} imports")
        except Exception as e:
            errors += 1
            print(f"  -> ERROR: {e}")

    if skipped:
        print(f"\nSkipped {skipped} unchanged files (use --force to re-index all)")

    # resolve call/extends/renders relationships
    print(f"\nResolving {len(pending_rels)} relationships...")
    resolved = 0
    for rel in pending_rels:
        to_id = resolve_symbol_name(graph_conn, rel.to_symbol_name)
        if to_id:
            upsert_relationship(graph_conn, rel.from_symbol_id, to_id, rel.rel_type)
            resolved += 1
    total_rels = resolved
    print(f"  -> {resolved}/{len(pending_rels)} resolved "
          f"(rest are stdlib/builtins not in our index)")

    # resolve imports to actual file paths
    print(f"Resolving {len(pending_imports)} imports...")
    imp_resolved = 0
    for imp in pending_imports:
        if imp.is_relative or not imp.module.startswith(('.', '/')):
            target = resolve_import_to_file(imp.module, imp.file, all_files)
            if target:
                from .graph_store import update_import_resolved
                imp_id = hashlib.sha256(
                    f"{imp.file}:{imp.module}:{imp.line}".encode()
                ).hexdigest()[:16]
                update_import_resolved(graph_conn, imp_id, target)
                imp_resolved += 1
    print(f"  -> {imp_resolved} resolved to local files")

    print("Computing PageRank...")
    pr_count = update_pagerank_scores(graph_conn)
    print(f"  -> {pr_count} symbols ranked")

    # ── Git intelligence ──
    if GIT_ENABLED:
        from .git_intel import is_git_repo, get_file_churn, get_change_coupling
        if is_git_repo(str(root)):
            print("Analyzing git history...")
            churn = get_file_churn(str(root))
            store_git_churn(graph_conn, churn)
            print(f"  -> {len(churn)} files with churn data")

            coupling = get_change_coupling(str(root))
            store_git_coupling(graph_conn, coupling)
            print(f"  -> {len(coupling)} file pairs with change coupling")
        else:
            print("(not a git repo, skipping git analysis)")

    graph_conn.close()

    elapsed = time.time() - start_time
    print(f"\nDone. {total_chunks} chunks, {total_rels} edges, "
          f"{total_imports} imports, {errors} errors, {elapsed:.1f}s")


def search(project_id: str, query: str, limit: int = 10):
    """Quick CLI search for testing."""
    from .embedder import embed_text, check_embedding_ready
    from .store import hybrid_search

    ok, msg = check_embedding_ready()
    if not ok:
        print(f"ERROR: {msg}")
        sys.exit(1)

    query_embedding = embed_text(query)
    results = hybrid_search(project_id, query, query_embedding, limit=limit)

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results):
        print(f"--- Result {i + 1} ---")
        print(f"FILE: {r.get('file', '?')} (lines {r.get('start_line', '?')}-{r.get('end_line', '?')})")
        print(f"SYMBOL: {r.get('symbol', '?')}")
        print(r.get('chunk', '')[:500])
        print()


def setup_mcp(project_id: str, server_path: str):
    """Auto-configure MCP for the user's AI assistant."""
    import json as _json
    server_path = str(Path(server_path).resolve())

    mcp_entry = {
        "command": "python",
        "args": [server_path],
        "env": {"CASSETTO_PROJECT_ID": project_id}
    }

    # Detect which AI assistants are installed and configure each
    configured = []

    # 1. Antigravity (Google)
    ag_dir = Path.home() / ".gemini" / "antigravity"
    if ag_dir.exists():
        ag_cfg = ag_dir / "mcp_config.json"
        try:
            existing = _json.loads(ag_cfg.read_text()) if ag_cfg.exists() else {}
        except Exception:
            existing = {}
        if "mcpServers" not in existing:
            existing = {"mcpServers": existing}
        existing["mcpServers"]["cassetto"] = mcp_entry
        ag_cfg.write_text(_json.dumps(existing, indent=2))
        configured.append(f"Antigravity ({ag_cfg})")
    else:
        # create it anyway since user might install later
        ag_dir.mkdir(parents=True, exist_ok=True)
        ag_cfg = ag_dir / "mcp_config.json"
        ag_cfg.write_text(_json.dumps({"mcpServers": {"cassetto": mcp_entry}}, indent=2))
        configured.append(f"Antigravity ({ag_cfg})")

    # 2. Claude Desktop / Claude Code
    claude_dir = Path.home() / ".claude"
    claude_cfg = claude_dir / "settings.json"
    if claude_dir.exists():
        try:
            existing = _json.loads(claude_cfg.read_text()) if claude_cfg.exists() else {}
        except Exception:
            existing = {}
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["cassetto"] = mcp_entry
        claude_cfg.write_text(_json.dumps(existing, indent=2))
        configured.append(f"Claude ({claude_cfg})")

    # 3. Cursor
    cursor_dir = Path.home() / ".cursor"
    if cursor_dir.exists():
        cursor_cfg = cursor_dir / "mcp.json"
        try:
            existing = _json.loads(cursor_cfg.read_text()) if cursor_cfg.exists() else {}
        except Exception:
            existing = {}
        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["cassetto"] = mcp_entry
        cursor_cfg.write_text(_json.dumps(existing, indent=2))
        configured.append(f"Cursor ({cursor_cfg})")

    if configured:
        print("MCP configured for:")
        for c in configured:
            print(f"  - {c}")
        print(f"\nProject: {project_id}")
        print("Restart your AI assistant to activate Cassetto.")
    else:
        print("No AI assistant config directories found.")
        print("Manual setup: add the following to your MCP config:\n")
        print(_json.dumps({"cassetto": mcp_entry}, indent=2))


def _default_project_id(directory: str = ".") -> str:
    """Derive project ID from folder name."""
    return Path(directory).resolve().name.lower().replace(" ", "-")


def main():
    parser = argparse.ArgumentParser(
        prog="cassetto",
        description="Cassetto -- code intelligence for LLMs via MCP",
    )
    subparsers = parser.add_subparsers(dest='command')

    # index
    idx = subparsers.add_parser('index', help='Index a project directory')
    idx.add_argument('directory', nargs='?', default='.',
                     help='Directory to index (default: current directory)')
    idx.add_argument('--project', '-p', default=None,
                     help='Project ID (default: folder name)')
    idx.add_argument('--force', action='store_true',
                     help='Force re-index all files (skip incremental check)')

    # search
    srch = subparsers.add_parser('search', help='Search the indexed codebase')
    srch.add_argument('query')
    srch.add_argument('--project', '-p', default=None)
    srch.add_argument('--limit', type=int, default=10)

    # watch
    wtch = subparsers.add_parser('watch', help='Watch for changes and re-index')
    wtch.add_argument('directory', nargs='?', default='.')
    wtch.add_argument('--project', '-p', default=None)

    # setup
    stp = subparsers.add_parser('setup',
        help='Auto-configure MCP for your AI assistant (Antigravity, Claude, Cursor)')
    stp.add_argument('--project', '-p', default=None,
                     help='Project ID (default: current folder name)')

    # serve
    srv = subparsers.add_parser('serve', help='Start the MCP server')
    srv.add_argument('--project', '-p', default=None,
                     help='Project ID (default: current folder name)')

    args = parser.parse_args()

    if args.command == 'index':
        pid = args.project or _default_project_id(args.directory)
        print(f"Indexing into project: {pid}")
        index_directory(args.directory, pid,
                        force=getattr(args, 'force', False))
        print(f"\nDone. Run 'cassetto setup' to connect to your AI assistant.")

    elif args.command == 'search':
        pid = args.project or _default_project_id()
        search(pid, args.query, args.limit)

    elif args.command == 'watch':
        pid = args.project or _default_project_id(args.directory)
        from .watcher import watch
        watch(args.directory, pid)

    elif args.command == 'setup':
        pid = args.project or _default_project_id()
        server_path = str(Path(__file__).parent / "server.py")
        setup_mcp(pid, server_path)

    elif args.command == 'serve':
        pid = args.project or _default_project_id()
        import os
        os.environ["CASSETTO_PROJECT_ID"] = pid
        # re-import server to pick up the project ID
        import importlib
        import server as _srv
        importlib.reload(_srv)
        print(f"Starting Cassetto MCP server (project: {pid})...")
        _srv.mcp.run()

    else:
        parser.print_help()
        print("\nQuick start:")
        print("  cassetto index .          # index current directory")
        print("  cassetto setup            # auto-configure MCP")
        print("  cassetto serve            # start MCP server manually")


if __name__ == "__main__":
    main()

