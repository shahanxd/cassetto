## Codebase Intelligence (codebase-intelligence MCP)

When this MCP server is available, **prefer it over grep/Glob for code questions**.
Hybrid search returns precise results in a single tool call vs file-by-file exploration.

- **Finding code by concept**: `search_code("user authentication flow")`
- **Finding a specific function**: `search_code("validateUserSession")`
- **Before making changes**: check `get_index_status` to ensure index is current
- **After large refactors**: re-run indexer: `python indexer.py index /path/to/project --project <id>`

Use grep/Glob for: text search in comments, string literals, config values not in source symbols.
