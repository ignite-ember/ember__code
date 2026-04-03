# MCP Integration

Ember Code uses the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) as a **client** to connect to external MCP servers. This lets you extend Ember Code with additional capabilities — browser automation, database access, custom APIs, and more — without writing plugins.

## How It Works

Ember Code connects to external MCP servers at session start and makes their tools available to agents. This uses Agno's built-in `MCPTools` class.

To add an MCP server, create or edit `.mcp.json` in your project root (see below).

> **Note:** Currently only the **stdio** transport is fully supported. HTTP and SSE transports are planned.

## Configuration (.mcp.json)

Project-level MCP configuration lives in `.mcp.json` at the project root. This file can be committed to version control so the whole team shares the same tool integrations.

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"],
      "env": {}
    }
  }
}
```

### Config Scopes

Configurations are loaded in order -- later files override earlier ones.

| Scope | Location | Shared? |
|---|---|---|
| **User** | `~/.ember/.mcp.json` | No, all projects |
| **Project** | `.mcp.json` (project root) | Yes, via git |
| **Local** | `.ember/.mcp.json` | No (gitignored) |

## Per-Agent MCP Filtering

Control which MCP servers are available to which agents using the `mcp_servers` field in the agent's `.md` file. This keeps all agent configuration in one place.

```markdown
# .ember/agents/database.md
---
name: database
description: Database operations and migrations
tools: Read, Write, Grep, Glob
mcp_servers: [postgres]
---
```

```markdown
# .ember/agents/editor.md
---
name: editor
description: Creates and modifies code files
tools: Read, Write, Edit, Bash, Glob, Grep
mcp_servers: [playwright, filesystem]
---
```

If `mcp_servers` is omitted, the agent receives **all** connected MCP tools (backward-compatible default). Specifying `mcp_servers` restricts the agent to only those servers.

See [Agents](AGENTS.md) for the full frontmatter reference.

## Security

- **Tool filtering** -- the `mcp_servers` frontmatter field limits which agents can use which MCP tools
- **Connection isolation** -- each MCP server runs in its own process

## Best Practices

- **Commit `.mcp.json`** to version control so the team shares the same integrations
- **Use `.ember/.mcp.json`** for machine-specific servers (it is gitignored)
- **Restrict MCP servers per agent** using the `mcp_servers` frontmatter field -- don't give every agent access to every server
- **Prefer stdio** for local tools -- it requires no network configuration and is fully supported today

