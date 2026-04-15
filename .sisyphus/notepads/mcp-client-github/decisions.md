# Decisions — MCP Client + GitHub MCP Server

## 2026-04-15
- Transport: stdio (default, based on GitHub MCP server)
- GitHub MCP Server: local Docker stdio subprocess
- Multi-server: static (JSON config) + dynamic (Python API)
- Config priority: CLI > ENV > defaults (no separate config file)
- Naming: `mcp.<server>.<tool>` prefix, no override of local tools
- Auto-reconnect: OFF by default
- Dynamic registration: Python API only
- Test strategy: post-implementation, unit + integration
- Resources/prompts: exposed via MCP Manager API, not ToolRegistry