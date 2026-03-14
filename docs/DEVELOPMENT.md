# Development

Guide for contributing to Ember Code and understanding the codebase.

## Project Structure

```
ember-code/
├── docs/                              # Documentation
│   ├── QUICKSTART.md
│   ├── ARCHITECTURE.md
│   ├── AGENTS.md
│   ├── SKILLS.md
│   ├── ONBOARDING.md
│   ├── TOOLS.md
│   ├── MCP.md
│   ├── CONFIGURATION.md
│   ├── VECTORBRIDGE.md
│   ├── EVALS.md
│   ├── HOOKS.md
│   ├── MIGRATION.md
│   ├── SECURITY.md
│   └── DEVELOPMENT.md
├── agents/                            # Built-in agent definitions (.md)
│   ├── explorer.md
│   ├── planner.md
│   ├── editor.md
│   ├── reviewer.md
│   ├── git.md
│   └── conversational.md
├── skills/                            # Built-in skills (SKILL.md)
│   ├── commit/SKILL.md
│   ├── review-pr/SKILL.md
│   ├── explain/SKILL.md
│   └── simplify/SKILL.md
├── src/
│   └── ember_code/
│       ├── __init__.py                # Package root, version string
│       ├── __main__.py                # Entry point (ignite-ember)
│       ├── cli.py                     # Click CLI (flags, subcommands, pipe mode)
│       ├── session.py                 # Session loop, knowledge/memory integration
│       ├── orchestrator.py            # Orchestrator: task analysis → TeamPlan
│       ├── pool.py                    # AgentPool: load/parse .md agent definitions
│       ├── team_builder.py            # Build Agno Teams/Agents from TeamPlan
│       │                              # AgnoFeatures: knowledge, learning, reasoning,
│       │                              # guardrails, compression, HITL
│       ├── config/
│       │   ├── __init__.py
│       │   ├── settings.py            # Settings (Pydantic), KnowledgeConfig,
│       │   │                          # LearningConfig, ReasoningConfig, GuardrailsConfig
│       │   ├── models.py              # ModelRegistry, BYOM resolution
│       │   ├── permissions.py         # PermissionGuard, allowlists
│       │   └── defaults.py            # Default configuration values
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── registry.py            # Tool name → Agno toolkit mapping
│       │   ├── edit.py                # EmberEditTools (string-replacement editing)
│       │   ├── search.py              # GrepTools, GlobTools
│       │   ├── web.py                 # WebTools (URL fetching)
│       │   └── orchestrate.py         # OrchestrateTools (sub-team spawning)
│       ├── knowledge/
│       │   ├── __init__.py
│       │   ├── manager.py             # KnowledgeManager, ChromaDB + Agno Knowledge
│       │   ├── embedder.py            # EmberEmbedder (custom Agno Embedder, 384-dim)
│       │   ├── embedder_registry.py   # EmbedderRegistry (BYOM for embeddings)
│       │   ├── models.py              # Pydantic: KnowledgeAddResult, KnowledgeFilter,
│       │   │                          # KnowledgeSearchResponse, KnowledgeStatus,
│       │   │                          # KnowledgeSyncResult
│       │   └── sync.py               # Git-shared knowledge sync (YAML ↔ ChromaDB)
│       ├── memory/
│       │   ├── __init__.py
│       │   └── manager.py             # Agno SqliteDb/Memory setup
│       ├── hooks/
│       │   ├── __init__.py
│       │   ├── loader.py              # Hook discovery from settings
│       │   ├── executor.py            # Hook execution (command/HTTP)
│       │   └── events.py              # HookEvent definitions
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── loader.py              # Skill discovery (SKILL.md files)
│       │   ├── parser.py              # YAML frontmatter parsing
│       │   └── executor.py            # Skill invocation (inline/forked)
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── server.py              # MCP server (ignite-ember mcp serve)
│       │   ├── client.py              # MCP client (consume external servers)
│       │   ├── tools.py               # MCP → Agno tool integration
│       │   ├── config.py              # .mcp.json loading
│       │   └── transport.py           # Transport layer (stdio, HTTP)
│       ├── tui/
│       │   ├── __init__.py            # Exports EmberApp
│       │   ├── app.py                 # EmberApp — thin Textual shell
│       │   ├── conversation_view.py   # ConversationView — widget append/clear
│       │   ├── execution_manager.py   # ExecutionManager — planning, streaming, cancel
│       │   ├── status_tracker.py      # StatusTracker — tokens, context, status bar
│       │   ├── hitl_handler.py        # HITLHandler — confirmation/input dialogs
│       │   ├── session_manager.py     # SessionManager — session picker, switching
│       │   ├── command_handler.py     # CommandHandler — slash command dispatch
│       │   ├── input_handler.py       # InputHandler — history, autocomplete
│       │   ├── stream_handler.py      # StreamHandler — Agno events → widgets
│       │   └── widgets.py             # Custom Textual widgets
│       └── utils/
│           ├── __init__.py
│           ├── context.py             # Project context loading (ember.md)
│           ├── display.py             # Rich terminal formatting
│           ├── audit.py               # Audit logging (JSON lines)
│           ├── tips.py                # Contextual tips: analyze config/project state,
│           │                          # suggest features not yet enabled
│           └── update_checker.py      # Check for newer ignite-ember versions
├── tests/
│   ├── conftest.py                    # Shared fixtures
│   ├── test_pool.py                   # Agent pool and .md parsing
│   ├── test_orchestrator.py           # Orchestrator and TeamPlan
│   ├── test_team_builder.py           # Team building and AgnoFeatures
│   ├── test_tools.py                  # Tool registry, edit, search, glob
│   ├── test_knowledge.py              # Knowledge, embedder, learning, reasoning, guardrails
│   ├── test_hooks.py                  # Hook events, loader, executor
│   ├── test_skills.py                 # Skill parser, loader, pool
│   ├── test_settings.py               # Config loading and merging
│   ├── test_permissions.py            # Permission guard
│   ├── test_models.py                 # Model registry resolution
│   ├── test_context.py                # Context utilities
│   ├── test_widgets.py                # TUI widgets
│   └── test_tui_handlers.py           # TUI handlers and commands
├── Makefile                           # Build commands (see below)
├── pyproject.toml                     # Package metadata, deps, tool config
├── ember.md                           # Project instructions for self-use
├── README.md
└── LICENSE
```

## Setup

```bash
# Clone
git clone https://github.com/ignite-ember/ember-code.git
cd ember-code

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with all extras
make install
# or: pip install -e ".[dev,mcp,knowledge,web]"

# Verify
ignite-ember --version
make check
```

## Makefile

All common tasks are available via `make`:

```bash
make help           # Show all targets
make install        # Install package with all extras
make test           # Run tests (pytest)
make test-v         # Run tests with verbose output
make test-cov       # Run tests with coverage report
make lint           # Run ruff linter
make format         # Auto-format code (ruff)
make format-check   # Check formatting without changes
make typecheck      # Run mypy type checking
make check          # Run ALL checks (lint + format + typecheck + test)
make fix            # Auto-fix lint and formatting issues
make clean          # Remove build artifacts and caches
```

The `make check` target is the single command to verify everything is clean before committing.

## Dependencies

**Core:**
- `agno[openai]` — Agent orchestration framework
- `rich` — Terminal formatting and markdown rendering
- `textual` — Terminal UI framework
- `pyyaml` — Configuration file parsing
- `click` — CLI argument parsing
- `pydantic` — Settings and data models
- `httpx` — HTTP client (embeddings, web tools)

**Optional:**
- `chromadb` — Vector knowledge base (`pip install ember-code[knowledge]`)
- `mcp` — Model Context Protocol (`pip install ember-code[mcp]`)
- `duckduckgo-search` — Web search (`pip install ember-code[web]`)

**Dev:**
- `pytest` + `pytest-asyncio` — Testing
- `ruff` — Linting and formatting
- `mypy` — Type checking

## Key Implementation Details

### 1. Agent Pool (pool.py)

The AgentPool discovers, parses, and manages agent definitions from `.md` files:

```python
class AgentPool:
    """Loads agent definitions from .md files and builds Agno Agent objects."""

    def _load_all(self, config: Settings):
        # Load in priority order (highest last, so they overwrite)
        dirs = [
            (Path(__file__).parent.parent / "agents", 0),  # built-in
            (Path.home() / ".ember-code" / "agents", 1),   # user global
            (Path(".ember/agents.local"), 2),               # project local
            (Path(".ember/agents"), 3),                     # project shared
        ]
```

### 2. Orchestrator (orchestrator.py)

The Orchestrator is the only hardcoded agent. It analyzes each task and outputs a `TeamPlan`:

```python
class TeamPlan(BaseModel):
    team_name: str
    team_mode: Literal["single", "route", "coordinate", "broadcast", "tasks"]
    agent_names: list[str]
    team_instructions: list[str]
    reasoning: str
```

### 3. Team Builder (team_builder.py)

`AgnoFeatures` encapsulates all Agno-native capabilities applied to agents and teams:

```python
class AgnoFeatures:
    """Configuration for Agno-native features."""
    # Session persistence (db, session_id, user_id)
    # History management
    # Agentic memory
    # Compression & summaries
    # Knowledge (ChromaDB + embeddings)
    # Learning (LearningMachine)
    # Reasoning tools (think, analyze)
    # Guardrails (PII, injection, moderation)
    # HITL hooks
```

The `apply_to_agent()` and `apply_to_team()` methods wire all features consistently.

### 4. Knowledge System (knowledge/)

The knowledge system uses a custom `EmberEmbedder` that calls the Ember server's `/v1/embeddings` endpoint (proxying to VectorBridge's text2vec-transformers model, 384 dimensions):

```python
class EmberEmbedder(Embedder):
    base_url: str = "https://api.ignite-ember.sh"
    model: str = "text2vec-transformers"
    dimensions: int = 384
```

`KnowledgeManager` creates an Agno `Knowledge` with ChromaDB as the vector store. All data models are Pydantic: `KnowledgeAddResult`, `KnowledgeSearchResponse`, `KnowledgeFilter`, `KnowledgeStatus`.

### 5. TUI Architecture (tui/)

The TUI follows a clean separation of concerns:

| Class | File | Responsibility |
|---|---|---|
| `EmberApp` | `app.py` | Textual shell: compose, mount, keybindings, event routing |
| `ConversationView` | `conversation_view.py` | Widget append/clear operations |
| `ExecutionManager` | `execution_manager.py` | Planning, streaming, cancellation |
| `StatusTracker` | `status_tracker.py` | Token/context tracking, status bar |
| `HITLHandler` | `hitl_handler.py` | Confirmation dialogs, user input |
| `SessionManager` | `session_manager.py` | Session picker, switching, clearing |
| `CommandHandler` | `command_handler.py` | Slash command dispatch |
| `InputHandler` | `input_handler.py` | History, autocomplete |
| `StreamHandler` | `stream_handler.py` | Agno streaming events → widgets |

### 6. Model Resolver (config/models.py)

Agent `.md` files specify models by name. The registry maps names to provider, endpoint, model ID, and credentials:

```python
def get_model(name: str, config: Settings) -> Model:
    # 1. User config registry (BYOM)
    # 2. Built-in registry (Ember hosted)
    # 3. provider:model_id syntax (e.g., "openai_like:gpt-4o")
```

## Testing

```bash
# Run all checks
make check

# Or individually:
make test            # pytest
make lint            # ruff check
make format          # ruff format
make typecheck       # mypy

# Quick iteration
make fix             # auto-fix lint + format
make test            # verify tests still pass
```

### Test Strategy

- **Unit tests** — agent pool, .md parsing, tool registry, config merging, knowledge models, TUI handlers
- **Integration tests** — Orchestrator decisions, team assembly, AgnoFeatures application
- **Mock LLM calls** — mock model responses to test orchestration logic
- **Agent definition tests** — validate all built-in `.md` files parse correctly
- **314 tests** across 14 test files, all passing

## Slash Commands

Built-in commands available in interactive mode:

| Command | Description |
|---|---|
| `/help` | Show available commands and keyboard shortcuts |
| `/quit` or `/exit` | Exit Ember Code |
| `/clear` | Clear conversation and reset session |
| `/config` | Show current settings (model, permissions, features) |
| `/agents` | List loaded agents with their tools |
| `/skills` | List loaded skills |
| `/hooks` | List loaded hooks |
| `/sessions` | Browse and resume past sessions |
| `/rename <name>` | Rename the current session |
| `/memory` | List stored memories |
| `/memory optimize` | Consolidate memories |
| `/knowledge` | Show knowledge base status |
| `/knowledge add <url\|path\|text>` | Add content to knowledge base |
| `/knowledge search <query>` | Search the knowledge base |
| `/sync-knowledge` | Sync knowledge between git file and vector DB |
| `/<skill-name> [args]` | Invoke a skill (e.g., `/commit`, `/review-pr`) |

## Architecture Decisions

### Why Agno over raw API calls?

- **Team orchestration** — dynamic task decomposition and routing
- **Memory management** — built-in persistent memory with DB backends
- **Tool ecosystem** — 100+ pre-built toolkits
- **Model agnostic** — swap models without code changes
- **Reasoning** — built-in chain-of-thought with `reasoning=True`
- **Knowledge** — ChromaDB vector stores with pluggable embedders
- **Learning** — LearningMachine for user profiles and entity memory
- **Guardrails** — PII detection, prompt injection, moderation as pre-hooks

### Why dynamic team assembly instead of a fixed hierarchy?

A fixed Router → Agent hierarchy forces you to pre-decide what agents exist and how they interact. The dynamic approach lets:
- Users add agents without code changes (just drop a `.md` file)
- The Orchestrator adapt team composition to each specific task
- Different tasks use different team modes (coordinate for multi-step, broadcast for review, etc.)
- Project teams customize behavior by overriding built-in agent definitions

### Why agents as .md files?

- **Accessibility** — anyone can write markdown, no Python needed
- **Portability** — commit to repo, share across team
- **Overridability** — project definitions override built-ins by name
- **Transparency** — read the file, understand exactly what the agent does
- **Claude Code compatibility** — same YAML frontmatter format, easy migration

### Why a TUI with separate manager classes?

The TUI is the default interface — `ignite-ember` launches `EmberApp` unless `--no-tui` is passed. The Textual app (`EmberApp`) is a thin shell that delegates to focused classes. This keeps each class testable in isolation and avoids a god-class. Textual requires `action_*` methods and `@on` decorators on the App, but the logic lives in the managers.

## Roadmap

See [GitHub Issues](https://github.com/ignite-ember/ember-code/issues) for the current roadmap.

**Planned features:**
- [ ] Centralized tracing (OpenTelemetry → Ember server)
- [ ] Plugin system (installable agent/tool packages)
- [ ] Web UI (Agno Playground integration)
- [ ] Voice mode (speech-to-text input)
- [ ] Multi-repo support (workspaces)
- [ ] Cron tasks (scheduled agent runs)
