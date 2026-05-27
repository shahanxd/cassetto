from cassetto import indexer
from cassetto.ast_chunker import Chunk


class FakeGraphConn:
    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return (1,)

    def close(self):
        pass


def test_index_directory_verbose_reports_progress_and_phase_timings(
    tmp_path,
    capsys,
    monkeypatch,
):
    source = tmp_path / "app.py"
    source.write_text("def hello():\n    return 'world'\n")

    chunk = Chunk(
        id="chunk-1",
        file=str(source),
        symbol="hello",
        symbol_type="function_definition",
        chunk=source.read_text(),
        start_line=1,
        end_line=2,
        language="python",
        ast_hash="hash",
    )

    from cassetto import ast_chunker, embedder, graph_extractor
    from cassetto import graph_store, import_extractor, store
    from cassetto import git_intel

    monkeypatch.setattr(embedder, "check_embedding_ready",
                        lambda: (True, "backend ready"))
    monkeypatch.setattr(ast_chunker, "chunk_file", lambda _path: [chunk])
    monkeypatch.setattr(embedder, "embed_batch",
                        lambda texts: [[0.0] for _ in texts])
    monkeypatch.setattr(store, "get_file_metadata",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "delete_file_chunks",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "store_chunks",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(store, "update_file_metadata",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "get_conn",
                        lambda _project_id: FakeGraphConn())
    monkeypatch.setattr(graph_store, "delete_file_symbols",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "upsert_symbol",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "delete_file_imports",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "upsert_import",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "resolve_symbol_name",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "update_pagerank_scores",
                        lambda _conn: 0)
    monkeypatch.setattr(graph_store, "store_git_churn",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_store, "store_git_coupling",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(graph_extractor, "extract_relationships",
                        lambda *_args, **_kwargs: [])
    monkeypatch.setattr(import_extractor, "extract_imports", lambda _path: [])
    monkeypatch.setattr(import_extractor, "resolve_import_to_file",
                        lambda *_args, **_kwargs: None)
    monkeypatch.setattr(git_intel, "is_git_repo", lambda _root: False)

    indexer.index_directory(str(tmp_path), "demo", verbose=True)
    output = capsys.readouterr().out

    assert "Parsing app.py -> 1 chunks" in output
    assert "Embedding 1 chunks..." in output
    assert "Extracted 0 relationships" in output
    assert "Extracted 0 imports" in output
    assert "Phase timings:" in output

