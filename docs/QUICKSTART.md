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

Ember Code ships with hosted models (MiniMax M2.5) — sign up for a free API key:

```bash
ignite-ember login
```

Or bring your own model key:

```bash
export MINIMAX_API_KEY=your_key    # or OPENAI_API_KEY, etc.
```

## First Run

```bash
ignite-ember
```

On first launch, Ember Code:
1. Creates default agents in `.ember/agents/` (explorer, planner, editor, reviewer, git, conversational)
2. Asks a few questions about your role and workflow
3. Proposes project-specific agents based on your codebase
4. You're ready to work

See [Onboarding](ONBOARDING.md) for the full first-run flow.

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

---

## Key Concepts

### Agents

Agents are `.md` files with YAML frontmatter. Each agent has a role, tools, and a system prompt:

```
.ember/agents/
├── explorer.md       # reads and searches the codebase
├── planner.md        # designs implementation plans
├── editor.md         # creates and modifies files
├── reviewer.md       # reviews code for quality
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

```yaml
# .ember/config.yaml
models:
  default: MiniMax-M2.5

permissions:
  file_write: ask           # ask before writing files
  shell_execute: ask        # ask before running commands
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
| `/sessions` | Browse and resume past sessions |
| `/memory` | List stored memories |
| `/knowledge` | Show knowledge base status |
| `/knowledge add <url\|path>` | Add content to knowledge base |
| `/knowledge search <query>` | Search the knowledge base |
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

## Coming from Claude Code?

Most things just work. See the [Migration Guide](MIGRATION.md) for details, but the short version:

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

- [Architecture](ARCHITECTURE.md) — how dynamic team assembly works
- [Agents](AGENTS.md) — agent format, built-in agents, creating your own
- [Configuration](CONFIGURATION.md) — full settings reference
- [Tools](TOOLS.md) — all available toolkits
- [Skills](SKILLS.md) — reusable prompted workflows
- [Security](SECURITY.md) — permissions, sandboxing, audit logging
- [Development](DEVELOPMENT.md) — contributing to Ember Code
