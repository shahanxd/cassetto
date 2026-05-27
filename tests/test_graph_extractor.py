"""
Unit tests — Graph extractor.
Tests call graph, inheritance, and JSX render extraction.
"""
import os
from cassetto.graph_extractor import extract_relationships, Relationship


class TestExtractRelationships:
    def test_python_function_calls(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text(
            "def outer():\n"
            "    inner()\n"
            "    other(42)\n"
        )
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(str(f))
        rels = extract_relationships(str(f), chunks)
        called = {r.to_symbol_name for r in rels if r.rel_type == 'calls'}
        assert "inner" in called
        assert "other" in called

    def test_javascript_calls(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text(
            "function main() {\n"
            "  fetchData();\n"
            "  console.log('hi');\n"
            "}\n"
        )
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(str(f))
        rels = extract_relationships(str(f), chunks)
        called = {r.to_symbol_name for r in rels if r.rel_type == 'calls'}
        assert "fetchData" in called

    def test_jsx_renders(self, tmp_path):
        f = tmp_path / "App.jsx"
        f.write_text(
            "function App() {\n"
            "  return (\n"
            "    <div>\n"
            "      <Header />\n"
            "      <MapView data={x} />\n"
            "    </div>\n"
            "  );\n"
            "}\n"
        )
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(str(f))
        rels = extract_relationships(str(f), chunks)
        renders = {r.to_symbol_name for r in rels if r.rel_type == 'renders'}
        assert "Header" in renders
        assert "MapView" in renders

    def test_class_inheritance(self, tmp_path):
        f = tmp_path / "models.py"
        f.write_text(
            "class Animal:\n"
            "    pass\n\n"
            "class Dog(Animal):\n"
            "    pass\n"
        )
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(str(f))
        rels = extract_relationships(str(f), chunks)
        extends = {(r.to_symbol_name, r.rel_type) for r in rels}
        assert ("Animal", "extends") in extends

    def test_empty_file_no_crash(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(str(f))
        rels = extract_relationships(str(f), chunks)
        assert rels == []

    def test_real_sparrow_wardapi(self, sparrow_dir):
        """wardApi.js should have many calls to apiFetch."""
        fpath = os.path.join(sparrow_dir, "src", "api", "wardApi.js")
        if not os.path.exists(fpath):
            import pytest; pytest.skip("sparrow not available")
        from cassetto.ast_chunker import chunk_file
        chunks = chunk_file(fpath)
        rels = extract_relationships(fpath, chunks)
        calls = [r for r in rels if r.rel_type == 'calls' and r.to_symbol_name == 'apiFetch']
        assert len(calls) >= 5  # wardApi has ~10 functions that call apiFetch


class TestRelationshipDataclass:
    def test_fields(self):
        r = Relationship(from_symbol_id="abc", to_symbol_name="foo", rel_type="calls")
        assert r.from_symbol_id == "abc"
        assert r.to_symbol_name == "foo"
        assert r.rel_type == "calls"
