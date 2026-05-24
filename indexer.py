"""
Codebase Intelligence — Indexer
CLI entry point for indexing a codebase and searching the index.

Usage:
    python indexer.py index <directory> --project <id>
    python indexer.py search <query> --project <id> [--limit N]
"""
import sys
import json
import time
import hashlib
import argparse
from pathlib import Path

# Fix Windows console Unicode encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from config import SKIP_DIRS, SUPPORTED_EXTENSIONS


def index_directory(directory: str, project_id: str):
    """Walk a directory and index all supported files."""
    from ast_chunker import chunk_file
    from embedder import embed_batch, check_embedding_ready
    from store import store_chunks, delete_file_chunks, update_file_metadata
    from graph_store import (get_conn as get_graph_conn, upsert_symbol,
                             upsert_relationship, delete_file_symbols,
                             resolve_symbol_name, update_pagerank_scores)
    from graph_extractor import extract_relationships

    ok, msg = check_embedding_ready()
    if not ok:
        print(f"ERROR: Embedding not available — {msg}")
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
    errors = 0
    start_time = time.time()

    graph_conn = get_graph_conn(project_id)

    # Collect all pending relationships (need all symbols stored before resolving)
    pending_rels = []

    for i, file_path in enumerate(all_files):
        print(f"[{i + 1}/{len(all_files)}] {file_path}")
        try:
            chunks = chunk_file(file_path)
            if not chunks:
                continue

            # Stage 1+2: embed and store chunks
            texts = [
                f"File: {c.file}\nSymbol: {c.symbol} ({c.symbol_type})\n\n{c.chunk}"
                for c in chunks
            ]
            embeddings = embed_batch(texts)
            delete_file_chunks(project_id, file_path)
            store_chunks(project_id, chunks, embeddings)
            total_chunks += len(chunks)

            # Stage 3: build graph
            delete_file_symbols(graph_conn, file_path)
            for chunk in chunks:
                upsert_symbol(graph_conn, chunk)

            rels = extract_relationships(file_path, chunks)
            pending_rels.extend(rels)

            file_content = Path(file_path).read_bytes()
            file_hash = hashlib.sha256(file_content).hexdigest()[:16]
            update_file_metadata(
                project_id, file_path,
                last_modified=Path(file_path).stat().st_mtime,
                file_hash=file_hash,
                symbol_count=len(chunks),
            )

            print(f"  -> {len(chunks)} chunks, {len(rels)} relationships")
        except Exception as e:
            errors += 1
            print(f"  -> ERROR: {e}")

    # Resolve relationship names → IDs and insert edges
    print(f"\nResolving {len(pending_rels)} relationships...")
    resolved = 0
    for rel in pending_rels:
        to_id = resolve_symbol_name(graph_conn, rel.to_symbol_name)
        if to_id:
            upsert_relationship(graph_conn, rel.from_symbol_id, to_id, rel.rel_type)
            resolved += 1
    total_rels = resolved
    print(f"  -> {resolved}/{len(pending_rels)} resolved")

    # Compute PageRank
    print("Computing PageRank...")
    pr_count = update_pagerank_scores(graph_conn)
    print(f"  -> {pr_count} symbols ranked")

    graph_conn.close()

    elapsed = time.time() - start_time
    print(f"\nDone. {total_chunks} chunks, {total_rels} edges, "
          f"{errors} errors, {elapsed:.1f}s")


def search(project_id: str, query: str, limit: int = 10):
    """Search the index and print results."""
    from embedder import embed_text, check_embedding_ready
    from store import hybrid_search

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Codebase Intelligence Indexer")
    subparsers = parser.add_subparsers(dest='command')

    idx = subparsers.add_parser('index')
    idx.add_argument('directory')
    idx.add_argument('--project', required=True)

    srch = subparsers.add_parser('search')
    srch.add_argument('query')
    srch.add_argument('--project', required=True)
    srch.add_argument('--limit', type=int, default=10)

    wtch = subparsers.add_parser('watch')
    wtch.add_argument('directory')
    wtch.add_argument('--project', required=True)

    args = parser.parse_args()
    if args.command == 'index':
        index_directory(args.directory, args.project)
    elif args.command == 'search':
        search(args.project, args.query, args.limit)
    elif args.command == 'watch':
        from watcher import watch
        watch(args.directory, args.project)
    else:
        parser.print_help()

