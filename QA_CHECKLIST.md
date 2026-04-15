# Ember Code — Full QA Checklist

> Priority by feature importance:
> - **P0** = Product unusable if broken (core loop, tools, permissions, sessions)
> - **P1** = Key differentiators broken (agents, orchestration, MCP, hooks, TUI)
> - **P2** = Important features degraded (knowledge, memory, scheduling, auth, media, worktree)
> - **P3** = Polish & completeness (autocomplete, tips, help text, docs, cosmetics)

---

## P0 — Core Loop & Safety

### Startup & basic conversation
- [x] `ignite-ember` — TUI launches, no crash
- [x] `ignite-ember --no-tui` — Rich CLI launches
- [x] `ignite-ember -m "what is 2+2"` — single message, response, exits
- [x] `echo "hello" | ignite-ember -p` — pipe mode works
- [x] `echo "text" | ignite-ember -p -m "prompt"` — combined works
- [x] Send a message in TUI — get a coherent response back
- [x] Send a message in `--no-tui` — get a coherent response back
- [X] Multi-turn conversation — context preserved across turns
- [x] Streaming — responses appear token-by-token (not all at once)

### End-to-end coding workflows
- [ ] "Add tests for [module]" — agent reads code, writes test file, runs tests
- [ ] "Fix the bug in [file]" — agent reads, edits, verifies
- [ ] "Refactor [function]" — agent reads, edits multiple files, runs tests
- [x] Multi-agent task — orchestrator delegates to specialist agents
- [ ] Agent uses multiple tools in sequence (Read → Edit → Bash)

### Error recovery & resilience
- [x] Model API timeout — graceful error message, session continues
- [x] Model API returns error — error shown, can send next message
- [x] Tool throws exception mid-task — agent informed, can retry or pivot
- [ ] MCP server crashes mid-session — error logged, other tools still work
- [x] Network down during WebSearch/WebFetch — error, not crash

### Cancel & interrupt behavior
- [x] `Escape` during agent run (TUI) — cancels operation, session stays alive
- [x] `Ctrl+C` in `--no-tui` — exits gracefully (no corrupt state)
- [ ] Cancel mid-file-write — file not left in corrupt state
- [x] Type message while agent is running — message queued, sent after agent finishes

### Tools (agents can't do anything without these)
- [x] **Read** — reads file contents correctly
- [x] **Write** — creates/overwrites file (permission check fires)
- [x] **Edit** — targeted string replacement works
- [x] **Bash** — executes shell commands (permission check fires)
- [x] **Glob** — pattern matching finds correct files
- [x] **Grep** — regex search returns correct matches with context
- [x] **LS** — lists directory contents
- [x] **WebSearch** — returns search results
- [x] **WebFetch** — fetches and extracts URL content
- [ ] **CodeIndex** — semantic search works (if Ember Cloud connected)
- [x] **NotebookEdit** — edits .ipynb cells correctly
- [x] **Orchestrate** — spawns sub-teams from agent pool
- [x] `--no-web` — disables WebSearch and WebFetch

### Permissions & safety (prevents destructive actions)
- [ ] File write — prompts for approval (default mode)
- [ ] Shell execute — prompts for approval (default mode)
- [ ] Git push — prompts for approval
- [ ] Git destructive (force-push, reset --hard) — prompts for approval
- [ ] "Allow once" — approves single call, next call prompts again
- [ ] "Always allow" — saves exact rule, no future prompts for same
- [ ] "Allow similar" — saves pattern rule
- [ ] "Deny" — blocks the call, agent informed
- [ ] Permission rules persist to `~/.ember/permissions.yaml`
- [ ] `--accept-edits` — auto-approves file edits, still asks for shell
- [ ] `--auto-approve` — skips all prompts
- [ ] `--read-only` — blocks all writes and shell execution
- [ ] `--strict` — denies everything, sandbox enabled

### Protected paths (hard blocks, not permission prompts)
- [x] Write to `*.pem` — blocked
- [x] Write to normal file — permission prompt (not hard block)

### Command safety
- [x] Blocked command (`rm -rf /`, fork bombs) — always blocked
- [x] Confirmation-required command (`git push`, `npm publish`) — requires approval
- [x] `--sandbox` mode — restricts filesystem/network access

### Session persistence (don't lose work)
- [x] New session gets auto-generated ID
- [x] Session persists to SQLite (`~/.ember/sessions.db`)
- [x] `--continue` — resumes last session with full history
- [x] `/clear` — generates new session ID, fresh context
- [x] `/rename <name>` — renames session
- [x] Conversation history survives app restart (via `--continue`)

### Context & compaction (prevents context overflow)
- [x] Auto-compaction at 80% context window — summarizes and trims
- [x] `/compact` — manual compaction works
- [x] `/compact` at minimum (2 runs) — says "Already at minimum"
- [x] Session summaries generated before trimming
- [x] Conversation still works after compaction
- [x] Tool result compression — Agno CompressionManager active (code verified)

### Configuration loading (wrong config = wrong behavior everywhere)
- [x] Built-in defaults apply when no config files exist
- [ ] `~/.ember/config.yaml` — user-global overrides work
- [ ] `.ember/config.yaml` — project overrides work
- [ ] `.ember/config.local.yaml` — local overrides (gitignored)
- [ ] CLI flags — highest priority, override all config files
- [ ] `ember.md` at project root — loaded as system context
- [ ] `~/.ember/rules.md` — user-global rules loaded

---

## P1 — Key Differentiators

### Agent system (the core architecture)
- [x] Built-in agents loaded from package
- [x] `.ember/agents/*.md` — project agents loaded
- [x] `~/.ember/agents/*.md` — user-global agents loaded
- [x] `.claude/agents/*.md` — loaded if `cross_tool_support: true`
- [ ] Agent with model override — uses specified model
- [x] Agent with custom tools list — only gets declared tools
- [x] Agent with `reasoning: true` — reasoning enabled (Agno uses manual CoT; no separate thinking phase visible in TUI)
- [x] Agent with `can_orchestrate: false` — cannot spawn sub-teams
- [x] `/agents` — lists all agents with tools
- [x] `/agents ephemeral` — lists ephemeral agents

### Orchestration (multi-agent coordination)
- [x] Orchestrator selects correct agent for task
- [x] Multi-agent team coordination — right agent for right subtask
- [ ] Sub-team spawning (recursive) — works
- [ ] Max nesting depth enforced — prevents infinite recursion
- [ ] Max total agents enforced — prevents resource exhaustion
- [ ] Sub-team timeout enforced — kills stalled sub-teams

### Ephemeral agents (dynamic agent creation)
- [x] Dynamically created during session when no agent fits
- [x] `/agents ephemeral` shows them
- [x] `/agents promote <name>` — saves to disk permanently
- [x] `/agents discard <name>` — removes
- [ ] Max ephemeral per session enforced
- [x] Auto-cleanup on session exit (if configured)

### MCP integration (extensibility)
- [x] `.mcp.json` at project root — servers loaded
- [x] `.ember/.mcp.json` — overrides project config
- [x] `~/.ember/.mcp.json` — user-global servers
- [x] Later file overrides earlier (scope precedence)
- [x] MCP servers connect on first message (`ensure_mcp`)
- [x] Connection failure — error printed, session continues (not fatal)
- [x] MCP server with no tools — disconnected with warning
- [x] Per-agent filtering (`mcp_servers` frontmatter) — agent only gets declared servers
- [x] Agent without `mcp_servers` — gets all connected tools
- [x] MCP tool calls display correctly in conversation (MCPCallWidget)
- [x] Status bar — green dot connected, red dot disconnected
- [x] `"type": "stdio"` — works (uses direct stdio_client with errlog redirect)
- [x] `"type": "sse"` — works
- [x] `"type": "invalid"` — rejected, error logged, no crash
- [x] No `type` field — defaults to stdio
- [x] Invalid JSON in `.mcp.json` — ignored, no crash

### MCP panel (`/mcp`)
- [ ] `/mcp` with no servers — shows "No MCP servers configured", Esc closes
- [x] `/mcp` with servers — shows list with status, transport, tool count
- [x] Panel does NOT trigger connections on open — shows current state only
- [x] Space on disconnected — connects, refreshes, status bar updates
- [x] Space on connected — disconnects, refreshes
- [ ] Space on policy-blocked — no action
- [x] After toggle, agents rebuild (verify MCP tool works)
- [ ] Toggle server that fails — error shown, no crash
- [x] Disconnect then reconnect — clean, no stale error
- [x] Enter expands tool list, Enter again collapses
- [x] Up/Down navigate, bounds respected
- [x] Escape closes, focus returns to input
- [x] Rapid toggle — no crash

### MCP approval & policy
- [x] First-time project server — auto-approved (project .mcp.json trusted by default)
- [x] User-global server — auto-approved
- [x] Denied server — not connected, logged (code verified)
- [x] Admin-denied server — blocked, lock icon in panel (code verified)

### Hooks (workflow automation)
- [x] **PreToolUse** — fires before tool, can block execution
- [x] **PostToolUse** — fires after tool success
- [x] **PostToolUseFailure** — fires after tool error (unit tested)
- [x] **UserPromptSubmit** — fires on message send, can block
- [x] **SessionStart** — fires on session begin
- [x] **SessionEnd** — fires on session end
- [x] **Stop** — fires when agent finishes, can block (up to 3 retries, unit tested)
- [x] **SubagentStart** — fires when sub-team spawns
- [x] **SubagentStop** — fires when sub-team finishes
- [x] Command hook — shell script, JSON on stdin
- [x] HTTP hook — POSTs to URL
- [x] Matcher — regex filtering works (unit tested)
- [x] Timeout — hook killed if exceeds limit (unit tested)
- [x] Background hook — fire-and-forget, doesn't block (unit tested)
- [x] `/hooks` — lists loaded hooks
- [x] `/hooks reload` — reloads from settings
- [x] Hooks from all settings files loaded (unit tested)

### TUI interface (the default experience)
- [x] Welcome banner — user name, model, directory
- [x] Status bar — tokens, context %, model, session ID
- [x] `Enter` sends, `\` + `Enter` newline
- [x] Up/Down input history
- [x] `Escape` cancels running operation
- [x] `Ctrl+D` quits
- [x] `Ctrl+L` clears screen
- [ ] `Ctrl+O` expand/collapse all messages
- [x] `Ctrl+V` toggle verbose
- [ ] `Ctrl+Q` toggle queue panel
- [ ] `Ctrl+T` toggle task panel
- [x] Markdown rendering with code highlighting
- [x] Tool calls as collapsible widgets
- [ ] Long messages collapse/expand
- [x] Agent tree visualization
- [x] Session picker (`/sessions`) — navigate, select, switch, Escape cancels
- [x] Model picker (`/model`) — navigate, select, current highlighted, Escape cancels

### Guardrails (safety layer)
- [x] PII detection — warns on PII (block)
- [x] Prompt injection — warns on injection patterns
- [x] All disabled — no warnings, no overhead

---

## P2 — Important Features

### Knowledge base
- [x] Enable in config — ChromaDB initialized
- [x] `/knowledge` — shows status
- [x] `/knowledge add <url>` — adds URL
- [x] `/knowledge add <path>` — adds file/directory
- [x] `/knowledge add <text>` — adds inline text
- [x] `/knowledge search <query>` — ranked results
- [x] `/knowledge search` no results — "No results found"
- [x] `/sync-knowledge` — bidirectional sync (or "not enabled")

### Memory & learning
- [ ] Agentic memory enabled — memories stored across conversations
- [ ] `/memory` — lists memories (or "none stored")
- [ ] `/memory optimize` — consolidates
- [ ] `--no-memory` — disables for this session
- [ ] Memories added to agent context
- [ ] Learning enabled — learns user preferences
- [ ] Entity memory — remembers facts

### Authentication & cloud
- [ ] `/login` — TUI: device flow widget; `--no-tui`: "TUI only" message
- [ ] `/login` flow — browser opens, polling, token saved
- [ ] `/login` — Escape cancels
- [ ] `/logout` — clears credentials (or "Not logged in")
- [ ] `/whoami` — shows email/expiry (or "Not logged in" / "Expired")
- [ ] Token stored at `~/.ember/credentials.json` with 0600 perms
- [ ] Cloud model auto-injected when authenticated
- [ ] Status bar shows cloud indicator

### Scheduling
- [ ] `/schedule` — lists tasks (or "none")
- [ ] `/schedule all` — includes completed/cancelled
- [ ] `/schedule add review code at 5pm` — one-shot
- [ ] `/schedule add run tests in 30 minutes` — relative
- [ ] `/schedule add run tests every 2 hours` — recurring
- [ ] `/schedule add check deps daily` — daily
- [ ] `/schedule show <id>` — details (or error)
- [ ] `/schedule cancel <id>` — cancels (or "already completed")
- [ ] Scheduled task executes at scheduled time
- [ ] Recurring tasks reschedule after completion
- [ ] Task timeout enforced
- [ ] Max concurrent enforced
- [ ] Task panel (Ctrl+T) — shows live status

### Media auto-detection
- [ ] TUI: local image path — "Attached: 1 image(s)"
- [ ] TUI: URL with media extension — attaches
- [ ] TUI: multiple media — combined summary
- [ ] TUI: non-existent file — left in text
- [ ] TUI: no media — normal send
- [ ] TUI: URL without known extension — NOT attached
- [ ] `--no-tui`: same behavior
- [ ] `-m "analyze ~/img.png"` — media detected
- [ ] Pipe mode — media detected
- [ ] Image (`.png`, `.jpg`, `.gif`, `.webp`) — auto-attached
- [ ] Audio (`.mp3`, `.wav`, `.ogg`, `.flac`) — auto-attached
- [ ] Video (`.mp4`, `.mov`, `.avi`, `.webm`) — auto-attached
- [ ] PDF (`.pdf`) — auto-attached
- [ ] Code/text files (`.py`, `.js`, `.json`, `.md`, etc.) — NOT auto-attached, agent reads via tools

### @file mention autocomplete
- [ ] Type `@` — file picker dropdown appears above input
- [ ] Type `@src/` — filters to files under src/
- [ ] Fuzzy matching works (e.g., `@s/u/m` matches `src/utils/media.py`)
- [ ] Up/Down arrows navigate the picker
- [ ] Tab selects file and inserts path after `@`
- [ ] Enter selects file (does NOT submit message)
- [ ] Escape dismisses picker without inserting
- [ ] Selected path inserted with trailing space
- [ ] `@nonexistent` — shows "No matching files"
- [ ] `@` alone (empty query) — shows first 20 project files
- [ ] Picker disappears when cursor leaves @-mention
- [ ] `email@domain` — does NOT trigger picker
- [ ] Works after `/clear` and session switches
- [ ] Large project (1000+ files) — no lag on first `@`
- [ ] Git-ignored files excluded from results

### Worktree
- [ ] `--worktree` — creates isolated git worktree
- [ ] Branch auto-named with session ID
- [ ] Changes don't affect main checkout
- [ ] Exit with no changes — auto-cleaned
- [ ] Exit with changes — preserved, merge instructions shown

### Skills
- [ ] `/skills` — lists loaded skills
- [ ] `/<skill-name>` — executes skill
- [ ] `/<skill-name> args` — passes arguments
- [ ] Auto-trigger — Orchestrator triggers matching skill (if enabled)

### Evals
- [ ] `/evals` — runs suites (or "no suites found")
- [ ] `/evals <agent>` — filters by agent
- [ ] Works in both TUI and `--no-tui`

### `--file` flag removal
- [ ] `--help` — no `-f` or `--file`
- [ ] `-f test.png` — errors as unknown flag
- [ ] `--file test.png` — errors as unknown flag

### Queue panel (Ctrl+Q)
- [ ] Shows pending messages
- [ ] Edit queued message
- [ ] Delete queued message
- [ ] Toggle on/off

### Slash command edge cases
- [ ] `/rename` (no args) — shows usage error
- [ ] `/schedule add` with unparseable time — shows format help
- [ ] `/agents promote` (no name) — shows error
- [ ] `/knowledge add` (no argument) — shows status instead of error

### CLI flags (remaining)
- [ ] `--model <name>` — overrides model
- [ ] `--verbose` — routing/reasoning shown
- [ ] `--quiet` — details suppressed
- [ ] `--no-color` — colors off
- [ ] `--no-memory` — memory disabled
- [ ] `--worktree` — worktree created
- [ ] `--add-dir <path>` — directory added
- [ ] `--add-dir` with two directories — both included in context
- [ ] `--debug` — debug log created at `~/.ember/debug.log`
- [ ] `--version` — version shown

---

## P3 — Polish & Completeness

### `/bug` command
- [ ] Opens GitHub issues in browser, confirms
- [ ] Headless/SSH — no crash

### Autocomplete
- [ ] `/mc` suggests `/mcp`
- [ ] `/com` suggests `/compact`
- [ ] `/bu` suggests `/bug`
- [ ] `/ev` suggests `/evals`
- [ ] `/syn` suggests `/sync-knowledge`
- [ ] `/sch` suggests `/schedule`
- [ ] Exact match — no dropdown
- [ ] Skills appear in autocomplete

### Help text
- [x] `/help` lists all commands in TUI
- [x] `/help` lists skills
- [x] `/help` shows shortcuts

### Tips & cosmetics
- [ ] Tip rotation includes `/mcp`
- [ ] Tips change every 30 seconds
- [ ] Tips contextual to config
- [ ] Update bar — newer version notification
- [ ] Tip bar visible

### First-run onboarding
- [ ] Fresh project — creates `.ember/`, copies agents/skills/hooks, `ember.md`
- [x] Delete project `.ember/` folder, re-run — re-initializes project (agents, skills, hooks copied)
- [ ] Home `~/.ember/.initialized` and project `.ember/.initialized` tracked independently
- [ ] Second run (both markers exist) — no re-initialization
- [ ] Built-in agents in `/agents`
- [ ] Built-in skills in `/skills`

### Audit & logging
- [ ] Audit log at `~/.ember/audit.log`
- [ ] Entries: session ID, agent, tool, status
- [ ] `--debug` creates debug log
- [ ] Blocked operations logged

### Cross-tool support
- [ ] `CLAUDE.md` loaded if `cross_tool_support: true`
- [ ] `.claude/agents/*.md` loaded if enabled

### Documentation accuracy
- [ ] `QUICKSTART.md` — media input section correct
- [ ] `docs/MCP.md` — `/mcp` panel section correct
- [ ] `docs/COMPARISON.md` — media + MCP rows correct
- [ ] `docs/MIGRATION.md` — `--file` + new commands correct
- [ ] Portal `GETTING_STARTED.md` — media + commands table
- [ ] Portal `MCP.md` — `/mcp` section
- [ ] Portal `MIGRATION.md` — `--file` + new commands
