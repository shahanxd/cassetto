"""
Codebase Intelligence — File Watcher (Stage 4)
Watches a directory for file changes and incrementally updates
the search index, graph, and PageRank scores.

Only re-embeds changed symbols — not the whole file.
PageRank is batched (at most once per 30 seconds).

Usage:
    python indexer.py watch <directory> --project <id>
"""
import sys
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ast_chunker import chunk_file, diff_chunks, EXTENSION_MAP
from store import store_chunks, delete_file_chunks, get_chunks_for_file
from graph_store import (get_conn as get_graph_conn, upsert_symbol,
                         delete_file_symbols, upsert_relationship,
                         resolve_symbol_name, update_pagerank_scores)
from graph_extractor import extract_relationships
from embedder import embed_batch, check_embedding_ready
from config import SKIP_DIRS

# Fix Windows console Unicode encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEBOUNCE_SECONDS = 0.4
PAGERANK_INTERVAL = 30  # seconds


class CodeChangeHandler(FileSystemEventHandler):
    """
    Handles file system events and incrementally updates the index.
    Changes are debounced (0.4s) to avoid processing partial saves.
    PageRank is batched (every 30s) to avoid expensive recomputation.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.pending: dict[str, float] = {}
        self.graph_dirty = False
        self.last_pagerank = time.time()
        self._update_count = 0

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
        """Queue a file for processing if it's a supported source file."""
        p = Path(path)
        if p.suffix in EXTENSION_MAP:
            if not any(skip in p.parts for skip in SKIP_DIRS):
                self.pending[path] = time.time()

    def _handle_delete(self, path: str):
        """Remove a deleted file from all stores."""
        p = Path(path)
        if p.suffix not in EXTENSION_MAP:
            return
        print(f"[DELETE] {path}")
        delete_file_chunks(self.project_id, path)
        conn = get_graph_conn(self.project_id)
        delete_file_symbols(conn, path)
        conn.close()
        self.graph_dirty = True

    def flush(self):
        """
        Process any pending file changes that have passed the debounce window.
        Called from the main loop every 100ms.
        """
        now = time.time()

        # Process debounced file changes
        to_process = [p for p, t in list(self.pending.items())
                      if now - t >= DEBOUNCE_SECONDS]
        for path in to_process:
            del self.pending[path]
            try:
                self._handle_change(path)
            except Exception as e:
                print(f"[ERROR] Failed to update {path}: {e}")

        # Batch PageRank recomputation (at most once per 30s)
        if self.graph_dirty and now - self.last_pagerank > PAGERANK_INTERVAL:
            print("[PAGERANK] Recomputing...")
            conn = get_graph_conn(self.project_id)
            count = update_pagerank_scores(conn)
            conn.close()
            self.last_pagerank = now
            self.graph_dirty = False
            print(f"[PAGERANK] {count} symbols ranked")

    def _handle_change(self, file_path: str):
        """
        Incrementally update a single file:
        1. Parse new AST chunks
        2. Diff against stored chunks
        3. Delete old data from all stores
        4. Re-embed and store new chunks
        5. Rebuild graph edges for this file
        """
        # Skip if file no longer exists (moved/renamed)
        if not Path(file_path).exists():
            self._handle_delete(file_path)
            return

        print(f"[CHANGE] {file_path}")

        # 1. Parse new chunks
        new_chunks = chunk_file(file_path)

        # 2. Get old chunks from index and diff
        old_chunks = get_chunks_for_file(self.project_id, file_path)
        added, modified, deleted_ids = diff_chunks(old_chunks, new_chunks)
        print(f"  +{len(added)} ~{len(modified)} -{len(deleted_ids)}")

        # 3. Remove all old data for this file (simpler than surgical update)
        delete_file_chunks(self.project_id, file_path)
        conn = get_graph_conn(self.project_id)
        delete_file_symbols(conn, file_path)

        if not new_chunks:
            conn.close()
            return

        # 4. Re-embed and store all chunks for this file
        texts = [
            f"File: {c.file}\nSymbol: {c.symbol} ({c.symbol_type})\n\n{c.chunk}"
            for c in new_chunks
        ]
        embeddings = embed_batch(texts)
        store_chunks(self.project_id, new_chunks, embeddings)

        # 5. Rebuild graph nodes
        for chunk in new_chunks:
            upsert_symbol(conn, chunk)

        # 6. Re-extract and resolve relationships
        rels = extract_relationships(file_path, new_chunks)
        resolved = 0
        for rel in rels:
            to_id = resolve_symbol_name(conn, rel.to_symbol_name)
            if to_id:
                upsert_relationship(conn, rel.from_symbol_id, to_id, rel.rel_type)
                resolved += 1

        conn.close()
        self.graph_dirty = True
        self._update_count += 1

        print(f"  ✓ {len(new_chunks)} chunks, {resolved} edges "
              f"(total updates: {self._update_count})")


def watch(directory: str, project_id: str):
    """Start watching a directory for file changes."""
    ok, msg = check_embedding_ready()
    if not ok:
        print(f"ERROR: Embedding not available — {msg}")
        sys.exit(1)
    print(f"Embedding backend: {msg}")

    root = Path(directory).resolve()
    if not root.exists():
        print(f"ERROR: Directory not found: {root}")
        sys.exit(1)

    handler = CodeChangeHandler(project_id)
    observer = Observer()
    observer.schedule(handler, str(root), recursive=True)
    observer.start()
    print(f"Watching {root} for changes... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(0.1)
            handler.flush()
    except KeyboardInterrupt:
        print("\nStopping watcher...")
        observer.stop()
    observer.join()
    print("Watcher stopped.")
