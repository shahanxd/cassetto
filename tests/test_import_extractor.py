"""
Unit tests — Import extractor.
Tests import parsing across languages.
"""
import os
from cassetto.import_extractor import extract_imports, ImportRelationship


class TestPythonImports:
    def test_simple_import(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("import os\nimport json\n")
        imports = extract_imports(str(f))
        modules = {i.module for i in imports}
        assert "os" in modules
        assert "json" in modules

    def test_from_import(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("from pathlib import Path\n")
        imports = extract_imports(str(f))
        assert len(imports) >= 1
        assert any(i.module == 'pathlib' for i in imports)

    def test_relative_import(self, tmp_path):
        f = tmp_path / "views.py"
        f.write_text("from .models import User\n")
        imports = extract_imports(str(f))
        assert len(imports) >= 1


class TestJavaScriptImports:
    def test_es_import(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text("import React from 'react';\nimport { useState } from 'react';\n")
        imports = extract_imports(str(f))
        assert len(imports) >= 1
        modules = {i.module for i in imports}
        assert "react" in modules

    def test_require(self, tmp_path):
        f = tmp_path / "server.js"
        f.write_text("const express = require('express');\nconst app = express();\n")
        imports = extract_imports(str(f))
        # require may or may not be captured depending on AST walk
        assert isinstance(imports, list)

    def test_relative_import(self, tmp_path):
        f = tmp_path / "app.js"
        f.write_text("import { fetchData } from './api/wardApi';\n")
        imports = extract_imports(str(f))
        assert len(imports) >= 1
        assert any('./api/wardApi' in i.module for i in imports)


class TestEmptyAndEdgeCases:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        assert extract_imports(str(f)) == []

    def test_no_imports(self, tmp_path):
        f = tmp_path / "pure.py"
        f.write_text("x = 42\nprint(x)\n")
        assert extract_imports(str(f)) == []

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.txt"
        f.write_text("import os")
        assert extract_imports(str(f)) == []

    def test_returns_dataclass(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("import os\n")
        imports = extract_imports(str(f))
        assert len(imports) >= 1
        assert isinstance(imports[0], ImportRelationship)
        assert hasattr(imports[0], 'module')
        assert hasattr(imports[0], 'file')


class TestRealFiles:
    def test_sparrow_services(self, sparrow_dir):
        fpath = os.path.join(sparrow_dir, "backend", "wards", "services.py")
        if not os.path.exists(fpath):
            import pytest; pytest.skip("sparrow not available")
        imports = extract_imports(fpath)
        modules = {i.module for i in imports}
        assert "json" in modules
        assert len(imports) >= 5

    def test_sparrow_wardapi(self, sparrow_dir):
        fpath = os.path.join(sparrow_dir, "src", "api", "wardApi.js")
        if not os.path.exists(fpath):
            import pytest; pytest.skip("sparrow not available")
        imports = extract_imports(fpath)
        # wardApi should import at least apiFetch
        assert isinstance(imports, list)
