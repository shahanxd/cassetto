## Cassetto (MCP tools)

Prefer these tools over grep/glob for structural code questions.

- **Semantic search**: `search_code("user authentication flow")`
- **Exact name search**: `search_code("validateUserSession")`
- **Before ANY change**: `blast_radius("functionName")` — see what breaks
- **Understanding a function**: `get_call_graph_tool("functionName")`
- **New codebase orientation**: `get_repo_map()` — see the most important symbols
- **Cleanup tasks**: `find_dead_code()` — find unused functions
- **Index health**: `get_index_status()`

Rule: Call `blast_radius` before modifying any function with more than one dependent.
