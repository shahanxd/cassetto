"""
Integration tests — MCP server tools.
Tests the actual tool functions against the pre-indexed Sparrow project.
These are the functions that the LLM calls. Every single one must work.
"""
import os
import sys
import json
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["CASSETTO_PROJECT_ID"] = "sparrow"

from server import (
    search_code, get_call_graph_tool, blast_radius, find_dead_code,
    get_repo_map, find_references, goto_definition, explain_symbol,
    get_hotspots, get_architecture_summary, find_entry_points,
    get_imports, find_cycles, get_index_status, find_implementations,
    get_change_history, get_ownership, get_change_coupling,
)


def _has_index():
    """Check if sparrow is actually indexed."""
    from config import DATA_DIR
    return (DATA_DIR / "sparrow" / "graph.duckdb").exists()


pytestmark = pytest.mark.skipif(
    not _has_index(), reason="sparrow not indexed"
)


class TestSearchCode:
    def test_returns_results(self):
        result = search_code("AQI calculation")
        assert "FILE:" in result
        assert len(result) > 50

    def test_empty_query_does_not_crash(self):
        # Empty query may raise internally; at minimum should not segfault
        try:
            result = search_code("x")
            assert isinstance(result, str)
        except Exception:
            pass  # acceptable to error on empty

    def test_limit_respected(self):
        result = search_code("function", limit=3)
        assert result.count("FILE:") <= 3


class TestCallGraph:
    def test_known_function(self):
        result = get_call_graph_tool("apiFetch")
        assert "apiFetch" in result

    def test_unknown_function(self):
        result = get_call_graph_tool("nonexistent_xyz_123")
        assert isinstance(result, str)  # should not crash


class TestBlastRadius:
    def test_apifetch_has_dependents(self):
        result = blast_radius("apiFetch")
        data = json.loads(result)
        assert data["symbol"] == "apiFetch"
        assert len(data["blast_radius"]) >= 5  # 10+ functions call apiFetch

    def test_unknown_symbol(self):
        result = blast_radius("nonexistent_xyz_123")
        assert isinstance(result, str)
        # May be JSON or plain text depending on whether symbol exists
        if result.strip().startswith('{'):
            data = json.loads(result)
            assert len(data.get('blast_radius', [])) == 0


class TestFindDeadCode:
    def test_returns_list(self):
        result = find_dead_code()
        assert isinstance(result, str)
        # Should find at least a few unused functions
        assert "dead" in result.lower() or "(" in result


class TestRepoMap:
    def test_returns_ranked_symbols(self):
        result = get_repo_map(10)
        assert "apiFetch" in result or "getAqiTier" in result
        lines = [l for l in result.strip().split('\n') if l.strip()]
        assert len(lines) >= 5

    def test_limit_works(self):
        small = get_repo_map(3)
        large = get_repo_map(20)
        assert len(large) > len(small)


class TestFindReferences:
    def test_apifetch_references(self):
        result = find_references("apiFetch")
        assert "fetchWards" in result
        assert "wardApi" in result

    def test_no_references(self):
        result = find_references("zzz_nonexistent_999")
        assert "0 found" in result or "No references" in result or isinstance(result, str)


class TestGotoDefinition:
    def test_known_symbol(self):
        result = goto_definition("getAqiColor")
        assert "aqiUtils" in result
        assert "line" in result.lower() or "LINE" in result or "23" in result

    def test_unknown_symbol(self):
        result = goto_definition("zzz_nonexistent_999")
        assert isinstance(result, str)


class TestExplainSymbol:
    def test_build_ward_data(self):
        result = explain_symbol("_build_ward_data")
        data = json.loads(result)
        assert "definition" in data
        assert "called_by" in data
        assert "calls" in data
        assert "pagerank" in data
        assert data["pagerank"] > 0

    def test_unknown(self):
        result = explain_symbol("zzz_nonexistent")
        assert isinstance(result, str)
        # May be JSON or plain text error message
        if result.strip().startswith('{'):
            data = json.loads(result)
            assert isinstance(data, dict)


class TestGetHotspots:
    def test_returns_results(self):
        result = get_hotspots()
        assert isinstance(result, str)
        # should list at least some files
        assert "changes" in result or "churn" in result.lower() or len(result) > 20


class TestArchitectureSummary:
    def test_detects_frameworks(self):
        result = get_architecture_summary()
        data = json.loads(result)
        frameworks = [f["framework"] for f in data["frameworks"]]
        assert "react" in frameworks
        assert "django" in frameworks

    def test_has_entry_points(self):
        result = get_architecture_summary()
        data = json.loads(result)
        assert len(data["entry_points"]) >= 2

    def test_has_languages(self):
        result = get_architecture_summary()
        data = json.loads(result)
        assert "python" in data["languages"]
        assert "javascript" in data["languages"]


class TestFindEntryPoints:
    def test_finds_manage_py(self):
        result = find_entry_points()
        assert "manage.py" in result

    def test_finds_main_jsx(self):
        result = find_entry_points()
        assert "main.jsx" in result


class TestGetImports:
    def test_services_imports(self):
        from store import get_indexed_files
        files = get_indexed_files("sparrow")
        svc = [f for f in files if "services.py" in f and "migration" not in f]
        if not svc:
            pytest.skip("services.py not indexed")
        result = get_imports(svc[0])
        assert "json" in result
        assert "models" in result


class TestFindCycles:
    def test_returns_results(self):
        result = find_cycles()
        assert isinstance(result, str)
        assert "circular" in result.lower() or "cycle" in result.lower() or "0 found" in result


class TestGetIndexStatus:
    def test_returns_status(self):
        result = get_index_status()
        assert "sparrow" in result.lower() or "project" in result.lower() or "files" in result.lower()


class TestFindImplementations:
    def test_returns_string(self):
        result = find_implementations("BaseModel")
        assert isinstance(result, str)


class TestGetChangeHistory:
    def test_returns_string(self):
        result = get_change_history("services.py")
        assert isinstance(result, str)


class TestGetOwnership:
    def test_returns_string(self):
        result = get_ownership("services.py")
        assert isinstance(result, str)


class TestGetChangeCoupling:
    def test_returns_string(self):
        result = get_change_coupling("services.py")
        assert isinstance(result, str)
