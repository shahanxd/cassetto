"""
File watcher — watches for saves/creates/deletes and incrementally updates
the index + graph without re-processing the entire codebase.

Changes are debounced (0.4s) so we don't process half-written files.
PageRank is only recomputed every 30 seconds since it's expensive and
doesn't need to be real-time.
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

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEBOUNCE_SECONDS = 0.4
PAGERANK_INTERVAL = 30


class CodeChangeHandler(FileSystemEventHandler):

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
        """Queue it if it's a file type we care about."""
        p = Path(path)
        if p.suffix in EXTENSION_MAP:
            if not any(skip in p.parts for skip in SKIP_DIRS):
                self.pending[path] = time.time()

    def _handle_delete(self, path: str):
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
        """Called every 100ms from the main loop."""
        now = time.time()

        # process files that have been sitting in the queue long enough
        to_process = [p for p, t in list(self.pending.items())
                      if now - t >= DEBOUNCE_SECONDS]
        for path in to_process:
            del self.pending[path]
            try:
                self._handle_change(path)
            except Exception as e:
                print(f"[ERROR] {path}: {e}")

        # don't recompute pagerank on every save — batch it
        if self.graph_dirty and now - self.last_pagerank > PAGERANK_INTERVAL:
            print("[PAGERANK] recomputing...")
            conn = get_graph_conn(self.project_id)
            count = update_pagerank_scores(conn)
            conn.close()
            self.last_pagerank = now
            self.graph_dirty = False
            print(f"[PAGERANK] {count} symbols ranked")

    def _handle_change(self, file_path: str):
        """Re-index a single file: parse, diff, embed, store, graph."""
        if not Path(file_path).exists():
            self._handle_delete(file_path)
            return

        print(f"[CHANGE] {file_path}")

        new_chunks = chunk_file(file_path)

        # diff to see what actually changed (for logging)
        old_chunks = get_chunks_for_file(self.project_id, file_path)
        added, modified, deleted_ids = diff_chunks(old_chunks, new_chunks)
        print(f"  +{len(added)} ~{len(modified)} -{len(deleted_ids)}")

        # wipe old data and re-insert everything for this file.
        # surgical partial updates aren't worth the complexity for single files.
        delete_file_chunks(self.project_id, file_path)
        conn = get_graph_conn(self.project_id)
        delete_file_symbols(conn, file_path)

        if not new_chunks:
            conn.close()
            return

        texts = [
            f"File: {c.file}\nSymbol: {c.symbol} ({c.symbol_type})\n\n{c.chunk}"
            for c in new_chunks
        ]
        embeddings = embed_batch(texts)
        store_chunks(self.project_id, new_chunks, embeddings)

        for chunk in new_chunks:
            upsert_symbol(conn, chunk)

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

        print(f"  ok: {len(new_chunks)} chunks, {resolved} edges "
              f"(update #{self._update_count})")


def watch(directory: str, project_id: str):
    ok, msg = check_embedding_ready()
    if not ok:
        print(f"ERROR: {msg}")
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
        print("\nStopping...")
        observer.stop()
    observer.join()
    print("Done.")
