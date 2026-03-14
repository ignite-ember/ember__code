# Quickstart

Get up and running with Ember Code in under 5 minutes.

## Install

**Homebrew (recommended):**

```bash
brew install ignite-ember
```

**pip:**

```bash
pip install ignite-ember
```

**From source:**

```bash
git clone https://github.com/ignite-ember/ember-code.git
cd ember-code
pip install -e ".[dev]"
```

## Authenticate

**Option A: Ember Code account (zero-config)**

Sign up for a free API key — all built-in models (MiniMax M2.5) work out of the box:

```bash
ignite-ember /login
```

**Option B: Bring your own model**

Use OpenAI, Anthropic, or any OpenAI-compatible API. Two steps:

1. Set your API key:

```bash
export OPENAI_API_KEY=sk-...
```

2. Add the model to `.ember/config.yaml`:

```yaml
models:
  default: gpt-4o              # use this model by default

  registry:
    gpt-4o:
      provider: openai_like
      model_id: gpt-4o
      url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY
```

That's it — agents will now use GPT-4o. See [Configuration](docs/CONFIGURATION.md) for more providers (Anthropic, Groq, Ollama, OpenRouter, etc.).

## First Run

```bash
ignite-ember
```

On first launch, Ember Code:
1. Creates 11 default agents in `.ember/agents/` — see the [agent list](#agents) below
2. Asks a few questions about your role and workflow
3. Proposes project-specific agents based on your codebase
4. You're ready to work

See [Onboarding](docs/ONBOARDING.md) for the full first-run flow.

---

## Basic Usage

### Interactive Mode

```bash
ignite-ember
```

Type naturally. The Orchestrator automatically picks the right agents and team mode for each task.

```
◆ Add a /health endpoint to the API with a test

  → Orchestrator assembles: [planner, editor] in coordinate mode
  → Planner reads existing routes, designs approach
  → Editor implements endpoint + test
  → Editor runs pytest to verify
```

### Single Message

```bash
ignite-ember -m "What does the auth middleware do?"
```

Runs one task and exits. Good for scripts and quick questions.

### Pipe Mode

```bash
cat error.log | ignite-ember -p -m "What caused this crash?"
```

Reads stdin, processes it with your message, writes to stdout. No interactive UI.

### TUI Mode

```bash
ignite-ember
```

The TUI launches by default — full terminal UI with streaming responses, session management, token tracking, agent tree visualization, and keyboard shortcuts. Use `--no-tui` to fall back to the plain Rich CLI output.

### Keyboard Shortcuts

| Action | macOS | Linux/Windows |
|---|---|---|
| Send message | `Enter` | `Enter` |
| New line | `⇧Enter` | `Shift+Enter` |
| Quit | `⌃D` | `Ctrl+D` |
| Clear screen | `⌃L` | `Ctrl+L` |
| Expand/collapse all | `⌃O` | `Ctrl+O` |
| Toggle verbose mode | `⌃V` | `Ctrl+V` |
| Toggle queue panel | `⌃Q` | `Ctrl+Q` |
| Input history | `↑/↓` | `Up/Down` |
| Cancel current operation | `Esc` | `Escape` |

---

## Key Concepts

### Agents

Agents are `.md` files with YAML frontmatter. Each agent has a role, tools, and a system prompt:

```
.ember/agents/
├── explorer.md       # reads and searches the codebase
├── architect.md      # designs component architecture
├── planner.md        # designs implementation plans
├── editor.md         # creates and modifies files
├── simplifier.md     # post-edit code polish
├── reviewer.md       # reviews code for quality
├── security.md       # vulnerability analysis
├── qa.md             # test generation and review
├── debugger.md       # bug diagnosis and root cause analysis
├── git.md            # handles version control
└── conversational.md # answers questions
```

Open them, read them, change them. Drop new `.md` files in to add your own agents.

### Orchestrator

You don't pick agents — the Orchestrator does. It analyzes each task and builds a purpose-fit team:

| Team Mode | When | Example |
|---|---|---|
| **Single** | One agent clearly fits | "What does this function do?" |
| **Route** | Pick one from several | "Fix the typo in README" |
| **Coordinate** | Multi-step, different skills | "Add endpoint with tests" |
| **Broadcast** | Parallel perspectives | "Review for security + performance" |
| **Tasks** | Large autonomous goals | "Migrate the test suite to pytest" |

### Tools

Agents get only the tools declared in their `.md` file. Built-in tools:

| Tool | What It Does |
|---|---|
| `Read` | Read file contents |
| `Write` | Create/overwrite files |
| `Edit` | Targeted string-replacement editing |
| `Bash` | Shell command execution |
| `Grep` | Regex content search (ripgrep) |
| `Glob` | File pattern matching |
| `WebSearch` | Web search |
| `WebFetch` | Fetch URL content |
| `Python` | Execute Python code |
| `Orchestrate` | Spawn sub-teams |

---

## Configuration

Ember Code loads config from multiple layers (highest priority first):

1. CLI flags
2. `.ember/config.local.yaml` (project, gitignored)
3. `.ember/config.yaml` (project, committed)
4. `~/.ember/config.yaml` (user global)
5. Built-in defaults

### Minimal Config

If you're using an Ember Code account, no config is needed — defaults work out of the box.

For BYOM, the minimum is a model registry entry (see [Authenticate](#authenticate) above). You can also tune permissions:

```yaml
# .ember/config.yaml
permissions:
  file_write: ask           # ask before writing files (default)
  shell_execute: ask        # ask before running commands (default)
  web_search: allow         # enable web search
```

### Project Instructions

Create an `ember.md` in your project root (like `CLAUDE.md` for Claude Code):

```markdown
# Project: My App

- Python 3.12 + FastAPI backend
- React 18 frontend in client/
- Tests use pytest, run with `make test`
- Always run tests after editing code
- Never modify files in migrations/ directly
```

Agents receive these instructions as context on every request.

---

## Permission Modes

Control how much the agent can do without asking:

| Command | Behavior |
|---|---|
| `ignite-ember` | Asks for file writes and shell commands |
| `ignite-ember --accept-edits` | Auto-approves file edits, asks for shell |
| `ignite-ember --read-only` | No file modifications allowed |
| `ignite-ember --strict` | Asks for everything, sandbox enabled |
| `ignite-ember --auto-approve` | Auto-approves everything (use with caution) |

When prompted for approval, you can:
- **[y] Allow once** — approve this specific call
- **[a] Always allow** — permanently allow this exact command
- **[s] Allow similar** — permanently allow the pattern (e.g., `pytest *`)
- **[n] Deny** — block this call

---

## Slash Commands

In interactive mode, use `/` commands:

| Command | What It Does |
|---|---|
| `/help` | Show available commands |
| `/clear` | Clear conversation and reset session |
| `/config` | Show current settings |
| `/agents` | List loaded agents with their tools |
| `/sessions` | Browse and resume past sessions (TUI only) |
| `/rename` | Rename current session (TUI only) |
| `/memory` | List stored memories (TUI only) |
| `/knowledge` | Show knowledge base status (TUI only) |
| `/knowledge add <url\|path>` | Add content to knowledge base |
| `/knowledge search <query>` | Search the knowledge base |
| `/sync-knowledge` | Manually sync knowledge between git and vector DB |
| `/commit` | Generate a commit (skill) |
| `/review-pr` | Review a pull request (skill) |

---

## Resume Sessions

Ember Code persists sessions to SQLite. Pick up where you left off:

```bash
ignite-ember --resume             # resume last session
ignite-ember --resume abc123      # resume specific session
```

Or use `/sessions` in interactive mode to browse past sessions.

---

## Optional Features

### Knowledge Base

Store and search documents via ChromaDB:

```yaml
# .ember/config.yaml
knowledge:
  enabled: true
  collection_name: "my_project"
  share: true                    # sync to .ember/knowledge.yaml for git sharing
```

When `share: true`, knowledge is automatically synced to a YAML file that your team can commit to git. On startup, only new entries are embedded — no redundant work. Use `/sync-knowledge` to manually trigger a sync.

The shared knowledge file (`.ember/knowledge.yaml`) uses this format:

```yaml
version: 1
synced_at: "2026-03-14T10:30:00+00:00"
entries:
  - id: "a1b2c3d4e5f67890"    # SHA256 content hash (16 chars)
    content: "API rate limits are 100 req/min per user"
    source: "docs/api-limits.md"
    added_at: "2026-03-14T09:00:00+00:00"
  - id: "f0e1d2c3b4a59876"
    content: "Deploy to staging before production, always"
    source: "manual"
    added_at: "2026-03-14T09:15:00+00:00"
```

Requires: `pip install ember-code[knowledge]`

### MCP (IDE Integration)

Use Ember Code as a tool server in VS Code, Cursor, or JetBrains:

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

### Web Tools

Enable web search and URL fetching:

```bash
pip install ember-code[web]
```

```yaml
permissions:
  web_search: allow
  web_fetch: allow
```

### Guardrails

Built-in AI safety pre-hooks:

```yaml
guardrails:
  pii_detection: true          # flag PII in prompts
  prompt_injection: true       # detect injection attempts
  moderation: true             # content moderation
```

---

## Custom Agents

Create a `.md` file in `.ember/agents/`:

```markdown
---
name: my-agent
description: Does a specific thing for my project
tools: Read, Write, Edit, Bash, Grep, Glob
model: MiniMax-M2.5
tags: [backend, api]
reasoning: true
---

You are a specialist for this project.

## What You Know
- The API lives in src/api/
- Tests are in tests/
- Always run `make test` after changes
```

The Orchestrator will start including it in teams immediately.

---

## CLI Reference

All flags at a glance:

| Flag | Description |
|---|---|
| `--model <name>` | Override the default model |
| `--verbose` | Show routing decisions and reasoning |
| `--quiet` | Minimal output |
| `-m, --message <text>` | Single message mode (non-interactive) |
| `-p, --pipe` | Pipe mode: read stdin, write stdout |
| `--resume [id]` | Resume last session (or specific session by ID) |
| `--no-memory` | Disable persistent memory for this session |
| `--sandbox` | Sandbox all shell commands |
| `--read-only` | No file modifications allowed |
| `--accept-edits` | Auto-approve file edits, ask for shell |
| `--auto-approve` | Auto-approve everything (use with caution) |
| `--strict` | Strict mode: ask for everything, sandbox enabled |
| `--no-tui` | Use plain Rich CLI instead of Textual TUI |
| `--no-web` | Disable web search/fetch tools |
| `--no-color` | Disable color output |

---

## Tips

On startup, Ember Code shows contextual tips based on your configuration. For example:

- *Create an `ember.md` in your project root to give agents project-specific context.*
- *Drop a `.md` file in `.ember/agents/` to create a project-specific agent — no code needed.*
- *Use `--verbose` to see which agents and team mode the Orchestrator picks.*

Tips adapt to your setup — if you haven't enabled the knowledge base or guardrails, you'll see suggestions for those. If you have Claude Code agents in `.claude/agents/`, you'll see a tip about `cross_tool_support`.

---

## Coming from Claude Code?

Most things just work. See the [Migration Guide](docs/MIGRATION.md) for details, but the short version:

```bash
# Enable cross-tool support to pick up existing Claude Code agents
# .ember/config.yaml
agents:
  cross_tool_support: true
skills:
  cross_tool_support: true
```

Ember Code also reads `CLAUDE.md`, `.claude/agents/*.md`, and `.mcp.json` as-is.

---

## Next Steps

- [Architecture](docs/ARCHITECTURE.md) — how dynamic team assembly works
- [Agents](docs/AGENTS.md) — agent format, built-in agents, creating your own
- [Configuration](docs/CONFIGURATION.md) — full settings reference
- [Tools](docs/TOOLS.md) — all available toolkits
- [Skills](docs/SKILLS.md) — reusable prompted workflows
- [Security](docs/SECURITY.md) — permissions, sandboxing, audit logging
- [Development](docs/DEVELOPMENT.md) — contributing to Ember Code
