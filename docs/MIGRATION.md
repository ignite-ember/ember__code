# Coming from Claude Code

Already using Claude Code? Ember Code is designed to feel familiar while giving you more. Agent definitions, MCP configs, and hooks use the **same formats** — most things just work when you switch.

## What Just Works (Zero Migration)

| What | Where | Status |
|---|---|---|
| Agent `.md` files | `.claude/agents/` | Loaded when `cross_tool_support: true` |
| Skills | `.claude/skills/` | Loaded when `cross_tool_support: true` |
| MCP config | `.mcp.json` | Same format, same location, works as-is |
| Hooks | `.claude/settings.json` | Same event names, same JSON format, same exit codes |
| Project instructions | `CLAUDE.md` | Ember Code reads `CLAUDE.md` in addition to `ember.md` |

Enable cross-tool support to scan Claude Code directories:

```yaml
# .ember/config.yaml
agents:
  cross_tool_support: true
skills:
  cross_tool_support: true
```

Or copy your agents/skills into `.ember/agents/` and `.ember/skills/` — no conversion needed since the file format is the same.

---

## Quick Start (for Claude Code users)

```bash
brew install ignite-ember
# or: pip install ignite-ember
ignite-ember login                   # sign up at ignite-ember.sh
ignite-ember                         # start — enable cross_tool_support to pick up existing agents
```

To use your existing Claude Code agents and skills immediately, add to `.ember/config.yaml`:
```yaml
agents:
  cross_tool_support: true
skills:
  cross_tool_support: true
```

---

## What's Different

### 1. Dynamic Teams Instead of Manual Sub-Agents

**Claude Code:** You spawn sub-agents manually. The parent agent decides when to delegate. Sub-agents can't spawn their own sub-agents (depth limit: 1).

**Ember Code:** An Orchestrator meta-agent automatically assembles teams for each task. It picks agents, chooses the team mode (route, coordinate, broadcast, tasks), and runs them. Every agent can spawn sub-teams — no depth limit.

```
Claude Code:                       Ember Code:
  You → Agent → Sub-agent            You → Orchestrator → Team
                                            (auto-assembled)
                                         ├─ Agent A
                                         ├─ Agent B → Sub-team
                                         └─ Agent C    ├─ Agent D
                                                       └─ Agent E
```

You don't need to tell Ember Code which agents to use. Just describe the task.

### 2. Team Modes

Claude Code has one execution model: single agent loop with optional sub-agent spawning.

Ember Code has four team modes, picked automatically per-task:

| Mode | What It Does | Example |
|---|---|---|
| **Route** | Pick one agent, pass through | "What does this function do?" → Explorer |
| **Coordinate** | Sequential multi-agent | "Add endpoint with tests" → Planner → Editor → Reviewer |
| **Broadcast** | Parallel independent agents | "Review for security + performance" → both run simultaneously |
| **Tasks** | Autonomous multi-step | "Migrate test suite" → iterates through files |

### 3. Agents as Extensible Data

Both use `.md` files with YAML frontmatter. Ember Code adds **optional** extension fields:

```yaml
---
name: my-agent
description: Does things
tools: Read, Write, Edit, Bash
model: MiniMax-M2.5        # (Claude Code uses: claude-sonnet-4-6)

# Ember extensions (ignored by Claude Code)
tags: [backend, api]
reasoning: true
can_orchestrate: true       # can this agent spawn sub-teams?
---
```

Claude Code agents work in Ember Code. Ember Code agents work in Claude Code (extensions are ignored).

### 4. VectorBridge (Semantic Code Intelligence)

Claude Code agents grep for patterns. Ember Code agents can also search by **meaning** via VectorBridge:

```
"How does authentication work?"
  Claude Code: grep for "auth", read matching files
  Ember Code:  VectorBridge returns pre-processed summary with
               security analysis, dependency graph, and references
```

See [VectorBridge](VECTORBRIDGE.md) for details.

### 5. Default Model

Claude Code defaults to Anthropic models (Claude). Ember Code defaults to **MiniMax M2.5** through the Ember Code hosted endpoint, but supports any model:

```yaml
# Use any OpenAI-compatible model
models:
  custom:
    - name: "claude-sonnet"
      url: "https://api.anthropic.com/v1"
      api_key_env: "ANTHROPIC_API_KEY"
      model_id: "claude-sonnet-4-6"
```

---

## Configuration Mapping

### Settings Files

| Claude Code | Ember Code | Notes |
|---|---|---|
| `~/.claude/settings.json` | `~/.ember/settings.json` | Global settings |
| `.claude/settings.json` | `.ember/settings.json` | Project settings |
| `.claude/settings.local.json` | `.ember/settings.local.json` | Local overrides (gitignored) |
| `CLAUDE.md` | `ember.md` | Project instructions (both are read) |
| `~/.claude/CLAUDE.md` | `~/.ember/ember.md` | Global instructions |
| `.claude/agents/*.md` | `.ember/agents/*.md` | Agent definitions (both dirs scanned) |
| `.mcp.json` | `.mcp.json` | MCP config (same file, same format) |

### CLI Flags

| Claude Code | Ember Code | Notes |
|---|---|---|
| `claude` | `ignite-ember` | Main command |
| `--model claude-sonnet-4-6` | `--model MiniMax-M2.5` | Different default, both support overrides |
| `--continue` / `-c` | `--resume` | Resume last session |
| `--resume <id>` | `--resume <id>` | Resume specific session |
| `--print` / `-p` | `-m "prompt"` | Non-interactive single task |
| `--dangerously-skip-permissions` | `--auto-approve` | Skip all permission prompts |
| `--permission-mode plan` | `--read-only` | Read-only mode |
| `--permission-mode acceptEdits` | `--accept-edits` | Auto-approve file edits |
| `--worktree` | Not yet available | Planned feature |
| `--effort low\|high` | Not applicable | Ember Code uses Agno reasoning instead |
| `--tools <list>` | Per-agent in `.md` file | Tool access is per-agent, not global |
| N/A | `--no-tui` | Fall back to plain Rich CLI (TUI is the default) |
| `--add-dir <path>` | Not yet available | Planned feature |

### Slash Commands

| Claude Code | Ember Code | Notes |
|---|---|---|
| `/help` | `/help` | Same |
| `/clear` | `/clear` | Same |
| `/compact` | `/compact` | Same |
| `/config` | `/config` | Same |
| `/model <name>` | `/model <name>` | Same |
| `/plan` | `/plan` | Same — enters planning mode |
| `/agent` | `/agents` | List/manage agents |
| `/resume` | `/resume` | Resume session |
| `/cost` | `/cost` | Token/cost stats |
| `/mcp` | `/mcp` | Manage MCP servers |
| `/hooks` | `/hooks` | View loaded hooks |
| — | `/onboard` | First-run onboarding (Ember Code only) |
| — | `/propose-agents` | Generate project-specific agents |
| — | `/evals run` | Run agent evaluations |
| — | `/knowledge` | Knowledge base status |
| — | `/knowledge add` | Add content to knowledge base |
| — | `/knowledge search` | Search the knowledge base |
| — | `/sync-knowledge` | Sync knowledge between git file and vector DB |
| — | `/memory` | List stored memories |
| — | `/memory optimize` | Consolidate memories |
| — | `/sessions` | Browse and resume past sessions |
| — | `/rename <name>` | Rename current session |
| — | `/skills` | List loaded skills |
| — | `/vectorbridge status` | VectorBridge indexing status |

### Permissions

| Claude Code | Ember Code | Notes |
|---|---|---|
| `"allow": ["Bash(npm run *)"]` | `permissions.shell_restricted: "allow"` | Ember uses category-based + patterns |
| `"deny": ["Read(.env)"]` | `safety.protected_paths: [".env"]` | Ember uses a dedicated protected paths list |
| `"ask": ["Bash(git push *)"]` | `safety.require_confirmation: ["git push"]` | Same concept, different syntax |

### Memory & Storage

| Claude Code | Ember Code | Notes |
|---|---|---|
| `~/.claude/projects/<id>/memory/` | Agno Memory (DB-backed) | Ember uses Agno's memory system |
| File-based `MEMORY.md` | `~/.ember/memory.db` (SQLite) | Structured storage, not files |
| Local sessions only | SQLite default, remote backends available | Configure `storage.backend: "postgres"` to sync |

---

## Migration Checklist

### Minimal (just switch)

- [ ] `brew install ignite-ember` (or `pip install ignite-ember`)
- [ ] `ignite-ember login` (sign up at ignite-ember.sh)
- [ ] Run `ignite-ember` — it automatically picks up:
  - `.claude/agents/*.md` (your agents)
  - `.mcp.json` (your MCP servers)
  - `CLAUDE.md` (your project instructions)

### Recommended (get the full benefit)

- [ ] Copy `CLAUDE.md` → `ember.md` (or keep both — Ember reads both)
- [ ] Add Ember extensions to agents that benefit from them:
  - `tags` for better Orchestrator routing
  - `reasoning: true` for agents that need chain-of-thought
  - `can_orchestrate: false` for agents that shouldn't spawn sub-teams
- [ ] Copy hooks from `.claude/settings.json` → `.ember/settings.json`
- [ ] Run `/onboard` to set up VectorBridge indexing
- [ ] Run `/propose-agents` to get project-specific agent suggestions
- [ ] Run `/evals run` to verify agents work correctly

### Optional (power features)

- [ ] Set up a remote storage backend for cross-device sync
- [ ] Configure BYOM if you want to use specific models
- [ ] Create project-specific evals for your custom agents
- [ ] Add VectorBridge-aware search to your agents' system prompts

---

## What Ember Code Adds

Features you get that Claude Code doesn't have:

| Feature | What It Does |
|---|---|
| **Dynamic team assembly** | Orchestrator auto-picks agents and team mode per task |
| **Unlimited nesting** | Agents spawn sub-teams recursively (no depth limit) |
| **VectorBridge** | Semantic code intelligence with multi-category analysis |
| **Ephemeral agents** | Auto-generated agents for tasks no existing agent fits |
| **Agent evals** | Built-in regression testing for agent definitions |
| **First-run onboarding** | Proposes project-specific agents based on your codebase |
| **Cross-device sync** | Session + memory sync via remote storage backends |
| **Model agnostic** | Any model from any provider (not just Anthropic) |
| **Knowledge base** | ChromaDB vector store with custom embeddings for document/code search |
| **Learning** | Agno LearningMachine builds user profiles, entity memory across sessions |
| **Guardrails** | PII detection, prompt injection detection, content moderation as pre-hooks |
| **HITL** | Agents pause for confirmation or user input before sensitive operations |
| **Run cancellation** | Cancel running agents mid-execution (Escape in TUI) |
| **TUI mode** | Full Textual-based terminal UI with streaming, session management, token tracking (default; `--no-tui` for plain Rich CLI) |
| **Team modes** | Route, Coordinate, Broadcast, Tasks — right tool for each job |

---

## What Ember Code Doesn't Have (Yet)

Features in Claude Code that Ember Code hasn't implemented:

| Feature | Status | Notes |
|---|---|---|
| Git worktrees (`--worktree`) | Planned | Isolated parallel sessions |
| Effort levels (`--effort`) | N/A | Ember uses Agno reasoning instead |
| Remote Control (web UI) | Planned | Access from browser |
| Voice mode | Not planned | |
| Plugin marketplace | Not planned | Use agents + tools instead |
| VS Code extension | Planned | MCP integration works today |
| `--add-dir` (multi-repo) | Planned | Multi-workspace support |

---

## Side-by-Side: Same Task, Different Approach

**Task:** "Add rate limiting to the /api/users endpoint with Redis and tests"

**Claude Code:**
```
You → Claude (single agent)
  1. Claude reads existing code (Read, Grep)
  2. Claude writes implementation (Edit, Write)
  3. Claude writes tests (Edit, Write)
  4. Claude runs tests (Bash)
  5. All in one agent loop, one context window
```

**Ember Code:**
```
You → Orchestrator
  → Assembles team: [planner, editor, reviewer] in coordinate mode

  1. Planner reads code, designs approach (Read, Grep, VectorBridge)
  2. Editor implements rate limiting (Read, Edit, Write, Bash)
     └─ Editor spawns Explorer sub-team to understand Redis patterns
  3. Editor writes tests (Read, Edit, Write)
  4. Reviewer validates implementation (Read, Grep, VectorBridge)
     └─ Checks security category for rate limiting best practices
  5. Editor runs tests (Bash)
```

Same result. Ember Code's approach gives better results on complex tasks because:
- Each agent has a focused role and system prompt
- VectorBridge provides architectural context that raw code search misses
- The Reviewer catches issues the Editor might overlook
- Sub-teams provide help exactly when needed
