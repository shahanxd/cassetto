import json
from pathlib import Path

from cassetto import indexer


def test_mcp_configured_detects_existing_cassetto_server(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"mcpServers": {"cassetto": {"command": "python"}}}))

    ok, detail = indexer._mcp_configured()

    assert ok is True
    assert "mcp.json" in detail


def test_mcp_configured_ignores_non_object_json(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".cursor" / "mcp.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps(["not", "a", "config"]))

    ok, detail = indexer._mcp_configured()

    assert ok is False
    assert detail == "not found in known MCP config files"


def test_collect_doctor_checks_reports_missing_index_without_creating_graph(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(indexer, "DATA_DIR", tmp_path)
    monkeypatch.setattr(indexer, "_embedding_model_available",
                        lambda: (True, "model ready"))
    monkeypatch.setattr(indexer, "_mcp_configured",
                        lambda: (False, "not configured"))

    from cassetto import embedder
    monkeypatch.setattr(embedder, "check_embedding_ready",
                        lambda: (True, "backend ready"))

    checks = indexer.collect_doctor_checks("demo", str(tmp_path))
    by_name = {check.name: check for check in checks}

    assert by_name["Embedding backend"].ok is True
    assert by_name["Embedding model"].ok is True
    assert by_name["Code index"].ok is False
    assert by_name["DuckDB graph"].ok is False
    assert by_name["MCP config"].ok is False
    assert not (tmp_path / "demo" / "graph.duckdb").exists()


def test_doctor_returns_failure_when_any_check_fails(capsys, monkeypatch):
    monkeypatch.setattr(indexer, "collect_doctor_checks", lambda *_args: [
        indexer.DoctorCheck("Embedding backend", True, "backend ready"),
        indexer.DoctorCheck("MCP config", False, "not configured"),
    ])

    exit_code = indexer.doctor("demo")
    output = capsys.readouterr().out

    assert exit_code == 1
    assert "[OK] Embedding backend: backend ready" in output
    assert "[FAIL] MCP config: not configured" in output
