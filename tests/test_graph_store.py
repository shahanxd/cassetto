"""
Unit tests — Graph store (DuckDB).
Tests the persistence layer: symbol storage, relationships, queries.
"""
import os
import shutil
import pytest
from cassetto.graph_store import (
    get_conn, upsert_symbol, upsert_relationship, delete_file_symbols,
    update_pagerank_scores, get_dead_code, get_call_graph,
    resolve_symbol_name, upsert_import, get_blast_radius,
)
from cassetto.ast_chunker import Chunk
from cassetto.import_extractor import ImportRelationship
from cassetto.config import DATA_DIR


def _make_chunk(chunk_id, name, file, start=0, end=5, text=""):
    return Chunk(id=chunk_id, file=file, symbol=name,
                 symbol_type="function_definition", chunk=text,
                 start_line=start, end_line=end, language="python",
                 ast_hash="test")


@pytest.fixture
def db():
    pid = f"_test_{os.getpid()}"
    conn = get_conn(pid)
    yield conn, pid
    conn.close()
    db_dir = DATA_DIR / pid
    if db_dir.exists():
        shutil.rmtree(db_dir, ignore_errors=True)


class TestSymbolCRUD:
    def test_upsert_symbol(self, db):
        conn, pid = db
        c = _make_chunk("id1", "foo", "/test/file.py")
        upsert_symbol(conn, c)
        rows = conn.execute("SELECT * FROM symbols WHERE id='id1'").fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "foo"

    def test_upsert_updates_existing(self, db):
        conn, pid = db
        c1 = _make_chunk("id1", "foo", "/test/file.py", text="v1")
        c2 = _make_chunk("id1", "foo", "/test/file.py", text="v2")
        upsert_symbol(conn, c1)
        upsert_symbol(conn, c2)
        rows = conn.execute("SELECT * FROM symbols WHERE id='id1'").fetchall()
        assert len(rows) == 1

    def test_delete_file_symbols(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "fn_a", "/file1.py"))
        upsert_symbol(conn, _make_chunk("b", "fn_b", "/file2.py"))
        delete_file_symbols(conn, "/file1.py")
        rows = conn.execute("SELECT id FROM symbols").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "b"


class TestRelationships:
    def test_upsert_relationship(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "caller", "/f.py"))
        upsert_symbol(conn, _make_chunk("b", "callee", "/f.py"))
        upsert_relationship(conn, "a", "b", "calls")
        rows = conn.execute("SELECT * FROM relationships").fetchall()
        assert len(rows) == 1
        # Verify 'calls' is in the row somewhere
        assert "calls" in str(rows[0])

    def test_get_call_graph(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "caller", "/f.py"))
        upsert_symbol(conn, _make_chunk("b", "callee", "/f.py"))
        upsert_relationship(conn, "a", "b", "calls")
        result = get_call_graph(conn, "caller")
        assert len(result) > 0  # should have some data


class TestBlastRadius:
    def test_blast_radius(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "base_fn", "/f.py"))
        upsert_symbol(conn, _make_chunk("b", "caller1", "/f.py"))
        upsert_symbol(conn, _make_chunk("c", "caller2", "/f.py"))
        upsert_relationship(conn, "b", "a", "calls")
        upsert_relationship(conn, "c", "a", "calls")
        result = get_blast_radius(conn, "base_fn")
        assert len(result) >= 2


class TestDeadCode:
    def test_finds_uncalled_functions(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "used_fn", "/f.py"))
        upsert_symbol(conn, _make_chunk("b", "dead_fn", "/f.py"))
        upsert_symbol(conn, _make_chunk("c", "caller", "/f.py"))
        upsert_relationship(conn, "c", "a", "calls")
        dead = get_dead_code(conn)
        dead_names = {d['name'] for d in dead}
        assert "dead_fn" in dead_names
        assert "used_fn" not in dead_names


class TestPageRank:
    def test_pagerank_runs(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("a", "hub", "/f.py"))
        upsert_symbol(conn, _make_chunk("b", "spoke1", "/f.py"))
        upsert_symbol(conn, _make_chunk("c", "spoke2", "/f.py"))
        upsert_relationship(conn, "b", "a", "calls")
        upsert_relationship(conn, "c", "a", "calls")
        update_pagerank_scores(conn)
        ranks = conn.execute(
            "SELECT name, pagerank_score FROM symbols ORDER BY pagerank_score DESC"
        ).fetchall()
        assert ranks[0][0] == "hub"
        assert ranks[0][1] > ranks[1][1]


class TestResolveSymbol:
    def test_resolve_by_name(self, db):
        conn, pid = db
        upsert_symbol(conn, _make_chunk("id1", "myFunc", "/f.py"))
        result = resolve_symbol_name(conn, "myFunc")
        assert result is not None
        assert result == "id1"

    def test_resolve_missing_returns_none(self, db):
        conn, pid = db
        result = resolve_symbol_name(conn, "nonexistent")
        assert result is None


class TestImports:
    def test_upsert_import(self, db):
        conn, pid = db
        imp = ImportRelationship(file="/app.py", module="os",
                                 names=None, is_relative=False, line=1)
        upsert_import(conn, imp)
        rows = conn.execute("SELECT * FROM imports").fetchall()
        assert len(rows) == 1
        # Verify 'os' appears in the row data
        assert "os" in str(rows[0])
