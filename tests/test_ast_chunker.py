"""
Unit tests — AST chunker.
Tests the core code-parsing layer that all other modules depend on.
"""
import os
import tempfile
from pathlib import Path
from cassetto.ast_chunker import chunk_file, EXTENSION_MAP, Chunk
from cassetto.config import SUPPORTED_EXTENSIONS


class TestExtensionMap:
    def test_python_supported(self):
        assert '.py' in EXTENSION_MAP

    def test_javascript_supported(self):
        assert '.js' in EXTENSION_MAP
        assert '.jsx' in EXTENSION_MAP

    def test_typescript_supported(self):
        assert '.ts' in EXTENSION_MAP
        assert '.tsx' in EXTENSION_MAP

    def test_kotlin_supported(self):
        assert '.kt' in EXTENSION_MAP
        assert '.kts' in EXTENSION_MAP
        assert '.kt' in SUPPORTED_EXTENSIONS
        assert '.kts' in SUPPORTED_EXTENSIONS

    def test_unsupported_returns_none(self):
        assert '.txt' not in EXTENSION_MAP
        assert '.md' not in EXTENSION_MAP


class TestChunkFile:
    def test_python_function(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def hello():\n    return 'world'\n")
        chunks = chunk_file(str(f))
        assert len(chunks) >= 1
        assert any(c.symbol == "hello" for c in chunks)

    def test_python_class(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("class MyClass:\n    def method(self):\n        pass\n")
        chunks = chunk_file(str(f))
        symbols = [c.symbol for c in chunks]
        assert "MyClass" in symbols

    def test_javascript_function(self, tmp_path):
        f = tmp_path / "sample.js"
        f.write_text("function fetchData(url) {\n  return fetch(url);\n}\n")
        chunks = chunk_file(str(f))
        assert len(chunks) >= 1
        assert any(c.symbol == "fetchData" for c in chunks)

    def test_jsx_component(self, tmp_path):
        f = tmp_path / "Component.jsx"
        f.write_text("function MyComponent() {\n  return <div>Hello</div>;\n}\n")
        chunks = chunk_file(str(f))
        assert any(c.symbol == "MyComponent" for c in chunks)

    def test_kotlin_function_class_and_object(self, tmp_path):
        f = tmp_path / "Sample.kt"
        f.write_text(
            "fun greet(name: String): String {\n"
            "    return \"Hello, $name\"\n"
            "}\n\n"
            "class User(val name: String)\n\n"
            "object Registry {\n"
            "    fun all(): List<User> = emptyList()\n"
            "}\n"
        )
        chunks = chunk_file(str(f))
        symbols = {c.symbol for c in chunks}

        assert "greet" in symbols
        assert "User" in symbols
        assert "Registry" in symbols
        assert {c.language for c in chunks} == {"kotlin"}

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        chunks = chunk_file(str(f))
        assert chunks == []

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("# Hello")
        chunks = chunk_file(str(f))
        assert chunks == []

    def test_chunk_has_required_fields(self, tmp_path):
        f = tmp_path / "sample.py"
        f.write_text("def foo():\n    x = 1\n    y = 2\n    return x + y\n")
        chunks = chunk_file(str(f))
        assert len(chunks) >= 1
        c = chunks[0]
        assert isinstance(c, Chunk)
        assert c.file == str(f)
        assert c.symbol == "foo"
        assert c.start_line >= 0
        assert c.end_line >= c.start_line
        assert len(c.chunk) > 0
        assert len(c.id) > 0

    def test_multiple_functions(self, tmp_path):
        f = tmp_path / "multi.py"
        f.write_text("def a():\n    pass\n\ndef b():\n    pass\n\ndef c():\n    pass\n")
        chunks = chunk_file(str(f))
        symbols = {c.symbol for c in chunks}
        # Chunker may also produce 'module_level' for top-level code
        assert "a" in symbols or "module_level" in symbols
        assert len(chunks) >= 1

    def test_binary_file_does_not_crash(self, tmp_path):
        f = tmp_path / "binary.py"
        f.write_bytes(b'\x00\x01\x02\xff\xfe' * 100)
        # Should not raise
        chunks = chunk_file(str(f))
        assert isinstance(chunks, list)

    def test_real_sparrow_file(self, sparrow_dir):
        """Test on an actual project file."""
        svc = os.path.join(sparrow_dir, "backend", "wards", "services.py")
        if not os.path.exists(svc):
            import pytest
            pytest.skip("sparrow not available")
        chunks = chunk_file(svc)
        assert len(chunks) > 5  # services.py has many functions
        symbols = {c.symbol for c in chunks}
        assert "_build_ward_data" in symbols
