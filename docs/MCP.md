# MCP Integration

Ember Code uses the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) for two purposes:

1. **As an MCP client** — consuming external MCP servers (IDE tools, databases, APIs)
2. **As an MCP server** — exposing its tools to IDEs and other MCP clients

This is what enables IDE integration — VS Code, JetBrains, Cursor, and others connect to Ember Code through MCP.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        IDE (VS Code / JetBrains / Cursor)    │
│                              │                               │
│                         MCP Client                           │
│                              │ stdio                         │
└──────────────────┬───────────┘                               │
                   │                                           │
                   ▼                                           │
┌──────────────────────────────────────────────────────────────┐
│                    Ember Code (MCP Server)                   │
│                                                              │
│  Exposed Tools:                                              │
│  ┌──────┬───────┬──────┬──────┬───────┬────────┬──────────┐  │
│  │ Bash │ Read  │Write │ Edit │ Grep  │ Glob   │ SubAgent │  │
│  └──────┴───────┴──────┴──────┴───────┴────────┴──────────┘  │
│                                                              │
│                    Ember Code (MCP Client)                   │
│                              │                               │
│              ┌───────────────┼───────────────┐               │
│              ▼               ▼               ▼               │
│     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐       │
│     │ JetBrains    │ │  Playwright  │ │  Custom      │       │
│     │ MCP Server   │ │  MCP Server  │ │  MCP Server  │       │
│     │ (IDE tools)  │ │ (browser)    │ │              │       │
│     └──────────────┘ └──────────────┘ └──────────────┘       │
└──────────────────────────────────────────────────────────────┘
```

## 1. Ember Code as MCP Server (IDE Integration)

### How It Works

When you run `ignite-ember mcp serve`, Ember Code starts a headless MCP server over **stdio** using JSON-RPC 2.0. IDEs connect to this server and can use Ember Code's tools programmatically.

```bash
# Start as MCP server
ignite-ember mcp serve
```

Each IDE connection spawns a fresh Ember Code session. No state is shared between connections.

### Exposed Tools

The MCP server exposes these tools to IDE clients:

| Tool | Description | Maps to Agent |
|---|---|---|
| `Bash` | Execute shell commands | Editor Agent |
| `Read` | Read file contents | Explorer Agent |
| `Write` | Create/overwrite files | Editor Agent |
| `Edit` | Targeted string replacement | Editor Agent |
| `Grep` | Search file contents (regex) | Explorer Agent |
| `Glob` | Find files by pattern | Explorer Agent |
| `ListDir` | List directory contents | Explorer Agent |
| `dispatch_agent` | Spawn a sub-agent for complex tasks | Router (Coordinate mode) |

### IDE Configuration

#### VS Code

Add to your VS Code MCP settings (`.vscode/mcp.json` or user settings):

```json
{
  "mcpServers": {
    "ignite-ember": {
      "type": "stdio",
      "command": "ignite-ember",
      "args": ["mcp", "serve"]
    }
  }
}
```

#### JetBrains (IntelliJ, PyCharm, WebStorm, etc.)

Settings > Tools > MCP Server > Add:

```json
{
  "mcpServers": {
    "ignite-ember": {
      "type": "stdio",
      "command": "ignite-ember",
      "args": ["mcp", "serve"]
    }
  }
}
```

JetBrains 2025.2+ has a built-in MCP server that Ember Code can also consume (see below).

#### Cursor / Windsurf

```json
{
  "mcpServers": {
    "ignite-ember": {
      "type": "stdio",
      "command": "ignite-ember",
      "args": ["mcp", "serve"]
    }
  }
}
```

Config locations:
- **Cursor**: `~/.cursor/mcp.json`
- **Windsurf**: `~/.codeium/windsurf/mcp_config.json`

### Implementation

Ember Code uses the `mcp` Python SDK to implement the server:

```python
# src/ember_code/mcp/server.py
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

server = Server("ignite-ember")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="Read",
            description="Read a file's contents",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="Edit",
            description="Edit a file by replacing a specific string",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_string": {"type": "string"},
                    "new_string": {"type": "string"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
        ),
        # ... other tools
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Route tool calls through the permission system,
    # then execute via the appropriate agent's toolkit
    result = await execute_tool(name, arguments)
    return [TextContent(type="text", text=result)]

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream)
```

### dispatch_agent

The `dispatch_agent` tool is special — it lets IDE clients delegate complex tasks to Ember Code's full agent team:

```json
{
  "name": "dispatch_agent",
  "arguments": {
    "prompt": "Refactor the auth module to use JWT tokens",
    "agent_type": "coder"
  }
}
```

This triggers the Router to delegate to the appropriate agent/team, and returns the final result.

---

## 2. Ember Code as MCP Client (Consuming External Servers)

### How It Works

Ember Code connects to external MCP servers to gain additional capabilities. This uses Agno's built-in `MCPTools` class.

```bash
# Add an MCP server
ignite-ember mcp add --transport stdio playwright -- npx @playwright/mcp@latest
ignite-ember mcp add --transport http my-api https://api.example.com/mcp

# List configured servers
ignite-ember mcp list

# Remove a server
ignite-ember mcp remove playwright
```

### Supported Transports

| Transport | Use Case | Example |
|---|---|---|
| **stdio** | Local processes (fully supported) | `npx @playwright/mcp@latest` |
| **streamable-http** | Remote APIs (planned) | `https://api.example.com/mcp` |
| **sse** | Remote APIs (planned) | `https://old-api.example.com/sse` |

> **Note:** Currently only the **stdio** transport is fully implemented. HTTP and SSE transports are defined in the transport layer but not yet wired up end-to-end. Use stdio for all MCP integrations today.

### Configuration File (.mcp.json)

Project-level MCP configuration lives in `.mcp.json` at the project root. This file can be committed to version control so the whole team shares the same tool integrations.

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {}
    },
    "jetbrains": {
      "command": "npx",
      "args": ["@anthropic-ai/mcp-jetbrains@latest"],
      "env": {}
    },
    "database": {
      "type": "http",
      "url": "${DB_MCP_URL:-http://localhost:3001/mcp}",
      "headers": {
        "Authorization": "Bearer ${DB_TOKEN}"
      }
    }
  }
}
```

**Environment variable expansion:** `${VAR}` and `${VAR:-default}` are supported in `command`, `args`, `env`, `url`, and `headers`.

### Scopes

| Scope | Location | Shared? |
|---|---|---|
| **Project** | `.mcp.json` (project root) | Yes, via git |
| **Local** | `.ember/mcp.local.json` | No (gitignored) |
| **User** | `~/.ember/mcp.json` | No, all projects |

### Integration with Agno

External MCP tools are loaded at session start and made available to agents:

```python
# src/ember_code/mcp/client.py
from agno.tools.mcp import MCPTools

async def load_mcp_servers(config: dict) -> list[MCPTools]:
    """Load all configured MCP servers as Agno tool providers."""
    mcp_tools = []

    for name, server_config in config.get("mcpServers", {}).items():
        transport = server_config.get("type", "stdio")

        if transport == "stdio":
            tools = MCPTools(
                command=server_config["command"],
                args=server_config.get("args", []),
                env=server_config.get("env", {}),
            )
        elif transport in ("http", "streamable-http"):
            tools = MCPTools(
                transport="streamable-http",
                url=server_config["url"],
                headers=server_config.get("headers", {}),
            )
        elif transport == "sse":
            tools = MCPTools(
                transport="sse",
                url=server_config["url"],
            )

        await tools.connect()
        mcp_tools.append(tools)

    return mcp_tools
```

MCP tools are injected into the relevant agents at session start. The Router agent sees all MCP tools and can route requests to them.

### Tool Filtering

Control which MCP tools are available to which agents:

```yaml
# .ember/config.yaml
mcp:
  tool_routing:
    # Only the Editor agent gets Playwright tools
    playwright:
      agents: ["editor"]
    # JetBrains IDE tools go to Explorer
    jetbrains:
      agents: ["explorer"]
    # Database tools go to Editor and Explorer
    database:
      agents: ["editor", "explorer"]
```

### Interactive Management

Inside an Ember Code session, use `/mcp` to manage servers:

```
/mcp                    # Show status of all MCP servers
/mcp add <name>         # Add a new server (interactive wizard)
/mcp remove <name>      # Remove a server
/mcp restart <name>     # Restart a disconnected server
/mcp toggle <name>      # Enable/disable a server
```

---

## 3. IDE-Specific Features

### JetBrains MCP Server

JetBrains IDEs (2025.2+) expose a built-in MCP server with code intelligence tools:

| Tool | Description |
|---|---|
| `get_open_file` | Get the currently focused file in the IDE |
| `search_in_project` | Search across the project using IDE index |
| `get_diagnostics` | Get errors/warnings from the IDE |
| `navigate_to` | Open a file at a specific line |
| `refactor` | Invoke IDE refactoring actions |
| `run_configuration` | Execute a run/debug configuration |

Ember Code can consume these to get rich IDE context:

```json
{
  "mcpServers": {
    "jetbrains": {
      "type": "stdio",
      "command": "npx",
      "args": ["@anthropic-ai/mcp-jetbrains@latest"]
    }
  }
}
```

### VS Code Extension (Future)

A dedicated VS Code extension will provide:
- Sidebar panel with Ember Code chat
- Inline code actions (explain, refactor, fix)
- Diagnostics integration (auto-fix errors)
- Terminal integration

The extension will communicate with Ember Code via MCP, using the same `ignite-ember mcp serve` backend.

---

## 4. Security

### MCP Server Security

When running as an MCP server:
- **stdio only** — no network exposure; only the parent process can connect
- **Permission system applies** — all tool calls go through the same permission checks
- **Audit logging** — all MCP tool calls are logged
- **No passthrough** — MCP servers that Ember Code consumes are NOT exposed to IDE clients

### MCP Client Security

When consuming external servers:
- **Project-scoped servers** require approval on first use
- **Environment variables** keep secrets out of config files
- **Tool filtering** limits which agents can use which MCP tools
- **Connection isolation** — each MCP server runs in its own process

### Managed Configuration (Enterprise)

For enterprise deployments, administrators can enforce MCP policies:

```json
// /Library/Application Support/EmberCode/managed-mcp.json (macOS)
// /etc/ignite-ember/managed-mcp.json (Linux)
{
  "mcpServers": {
    "corporate-tools": {
      "type": "http",
      "url": "https://internal.corp.com/mcp"
    }
  },
  "policy": {
    "allowedMcpServers": ["corporate-tools", "playwright"],
    "deniedMcpServers": ["*-unsafe-*"]
  }
}
```

---

## 5. Project Structure

```
src/ember_code/
├── mcp/
│   ├── __init__.py
│   ├── server.py          # MCP server implementation (ignite-ember mcp serve)
│   ├── client.py          # MCP client (consuming external servers)
│   ├── tools.py           # Tool definitions exposed via MCP
│   ├── config.py          # .mcp.json loading and env var expansion
│   └── transport.py       # Transport layer (stdio, http, sse)
```
