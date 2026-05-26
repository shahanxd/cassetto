"""
MCP Protocol tests.
Tests that the server responds correctly to JSON-RPC over stdio.
This is what the AI assistant sees — if this fails, nothing works.
"""
import os
import sys
import json
import subprocess
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PY = os.path.join(ROOT, "server.py")


def _send_mcp(*messages):
    """Send JSON-RPC messages to the MCP server via stdio and return responses."""
    input_text = "\n".join(json.dumps(m) for m in messages) + "\n"
    result = subprocess.run(
        [sys.executable, SERVER_PY],
        input=input_text,
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "CASSETTO_PROJECT_ID": "sparrow"},
    )
    responses = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                responses.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return responses


INIT_MSG = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1.0"}
    }
}


class TestMCPProtocol:
    def test_initialize(self):
        responses = _send_mcp(INIT_MSG)
        assert len(responses) >= 1
        r = responses[0]
        assert r["jsonrpc"] == "2.0"
        assert r["id"] == 1
        assert "result" in r
        assert r["result"]["serverInfo"]["name"] == "cassetto"

    def test_tools_are_advertised(self):
        """Verify the server advertises tool capabilities in initialize."""
        responses = _send_mcp(INIT_MSG)
        r = responses[0]
        caps = r["result"]["capabilities"]
        assert "tools" in caps

    def test_tool_call_via_protocol(self):
        """Send a tools/call directly (init + call in one batch)."""
        responses = _send_mcp(
            INIT_MSG,
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {
                "name": "get_index_status",
                "arguments": {}
            }}
        )
        # Should get at least the init response
        assert len(responses) >= 1
        # If both are processed, check the call response
        call_resps = [r for r in responses if r.get("id") == 10]
        if call_resps:
            content = call_resps[0]["result"]["content"]
            assert content[0]["type"] == "text"
            assert len(content[0]["text"]) > 5


class TestToolDiscovery:
    """Test that all 18 tools are registered and have proper schemas."""
    def test_all_tools_registered(self):
        """Import server and verify all tools are in the MCP registry."""
        os.environ["CASSETTO_PROJECT_ID"] = "sparrow"
        sys.path.insert(0, ROOT)
        from server import mcp
        tools = mcp._tool_manager._tools
        assert len(tools) == 18

    def test_expected_tools_present(self):
        os.environ["CASSETTO_PROJECT_ID"] = "sparrow"
        sys.path.insert(0, ROOT)
        from server import mcp
        tool_names = set(mcp._tool_manager._tools.keys())
        expected = {
            "search_code", "get_call_graph_tool", "blast_radius",
            "find_dead_code", "get_repo_map", "find_references",
            "goto_definition", "find_implementations", "explain_symbol",
            "get_hotspots", "get_change_history", "get_ownership",
            "get_change_coupling", "get_architecture_summary",
            "find_entry_points", "get_imports", "find_cycles",
            "get_index_status",
        }
        assert expected == tool_names

    def test_all_tools_have_descriptions(self):
        os.environ["CASSETTO_PROJECT_ID"] = "sparrow"
        sys.path.insert(0, ROOT)
        from server import mcp
        for name, tool in mcp._tool_manager._tools.items():
            desc = tool.description if hasattr(tool, 'description') else ""
            assert len(str(desc)) > 10, f"Tool {name} has no description"
