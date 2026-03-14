# Configuration

Ember Code is configured through a layered system of config files, environment variables, and CLI flags.

## Configuration Hierarchy

(Highest priority first)

1. **CLI flags** — `--model`, `--no-web`, `--sandbox`, etc.
2. **Project config** — `.ember/config.yaml` (committed to repo)
3. **Project local config** — `.ember/config.local.yaml` (gitignored)
4. **User config** — `~/.ember/config.yaml` (global)
5. **Defaults** — built-in sensible defaults

## Models & Authentication

Ember Code needs an LLM to run. Models are resolved through a **config-driven registry** — agent `.md` files reference models by name (e.g., `model: MiniMax-M2.5`), and the registry maps that name to a provider, endpoint URL, model ID, and API key.

### Model Registry

The registry has two layers:

1. **Built-in models** — ship with Ember Code, route through the Ember hosted endpoint
2. **Custom models (BYOM)** — user-defined entries that override or extend the built-ins

```yaml
# Built-in registry (hardcoded in defaults.py, shown here for reference)
models:
  registry:
    MiniMax-M2.5:
      provider: openai_like
      model_id: MiniMax-Text-01
      url: https://api.ignite-ember.sh/v1    # Ember hosted endpoint
      api_key_env: EMBER_API_KEY

    MiniMax-M2.5-highspeed:
      provider: openai_like
      model_id: MiniMax-Text-01-highspeed
      url: https://api.ignite-ember.sh/v1
      api_key_env: EMBER_API_KEY
```

Agent `.md` files just reference the registry name:

```yaml
model: MiniMax-M2.5           # → looks up "MiniMax-M2.5" in the registry
```

### Resolution Order

When an agent references `model: <name>`:

```
1. Is <name> in models.registry (user config)?     → use it
2. Is <name> in built-in registry?                  → use it (Ember hosted endpoint)
3. Does <name> contain ":" (e.g., "openai:gpt-4o")? → parse as provider:model_id
4. None of the above?                               → error: unknown model
```

### Option 1: Ember Code Account (default, zero-config)

Sign up at **https://ignite-ember.sh** and get an API key. All built-in models route through the Ember hosted endpoint. Free tier available.

```bash
ignite-ember login          # interactive login
# or
export EMBER_API_KEY=ek_...
```

No model configuration needed — the built-in registry handles everything.

### Option 2: Bring Your Own Model (BYOM)

Add entries to `models.registry` in your config. These override built-in entries with the same name, or add entirely new models.

```yaml
# .ember/config.yaml
models:
  registry:
    # Override the built-in MiniMax-M2.5 to use your own key directly
    MiniMax-M2.5:
      provider: openai_like
      model_id: MiniMax-Text-01
      url: https://api.minimaxi.chat/v1
      api_key_env: MINIMAX_API_KEY

    # Add new models
    gpt-4o:
      provider: openai_like
      model_id: gpt-4o
      url: https://api.openai.com/v1
      api_key_env: OPENAI_API_KEY

    claude-sonnet:
      provider: openai_like
      model_id: claude-sonnet-4-6
      url: https://api.anthropic.com/v1
      api_key_env: ANTHROPIC_API_KEY
```

Now agents can reference `model: gpt-4o` or `model: claude-sonnet` in their `.md` files.

Works with MiniMax, OpenAI, Anthropic, Groq, Together AI, OpenRouter, Ollama, or any OpenAI-compatible API.

### Registry Entry Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `provider` | string | yes | Agno model class to use. `openai_like` for any OpenAI-compatible API |
| `model_id` | string | yes | Model identifier sent to the API (e.g., `MiniMax-Text-01`, `gpt-4o`) |
| `url` | string | yes | API base URL |
| `api_key_env` | string | no | Environment variable name containing the API key |
| `api_key_cmd` | string | no | Shell command that outputs the API key (alternative to `api_key_env`) |
| `temperature` | float | no | Default temperature for this model |
| `max_tokens` | int | no | Default max output tokens |

### Comparison with Claude Code

Claude Code uses a simple alias map (`"sonnet"` → `"claude-sonnet-4-6"`) because it only supports Anthropic models. Ember Code needs a full registry because it's multi-provider — each model name must resolve to a provider class, endpoint URL, model ID, and credentials.

| Aspect | Claude Code | Ember Code |
|---|---|---|
| Model resolution | Alias map (string → string) | Config-driven registry (name → provider + URL + key) |
| First-party API | `ANTHROPIC_API_KEY` | `EMBER_API_KEY` (Ember hosted MiniMax M2.5) |
| Hosted endpoint | `api.anthropic.com` | `api.ignite-ember.sh` |
| AWS Bedrock | `CLAUDE_CODE_USE_BEDROCK` | BYOM registry entry with Bedrock URL |
| Google Vertex | `CLAUDE_CODE_USE_VERTEX` | BYOM registry entry with Vertex URL |
| Custom base URL | `ANTHROPIC_BASE_URL` | `url` field per registry entry |
| Adding new models | Not supported (Anthropic only) | Add a registry entry in config |
| Key helper script | `apiKeyHelper` | `api_key_env` or `api_key_cmd` per model |

The key difference: Claude Code only supports Anthropic models through different providers. Ember Code supports **any model from any provider** — MiniMax, OpenAI, Anthropic, Groq, local Ollama, etc. The config-driven registry means adding a new provider is a config change, not a code change.

---

## Config File Format

```yaml
# .ember/config.yaml

# Model configuration
#
# Model resolution order:
#   1. User-provided custom models (BYOM - Bring Your Own Model)
#   2. Ember Code hosted models (requires Ember Code account)
#
# If no custom model is configured, Ember Code uses its own hosted
# MiniMax M2.5 endpoint. You need an Ember Code account for this.
# Sign up at https://ignite-ember.sh (free tier available).

models:
  default: "MiniMax-M2.5"             # Default model for most agents
  fast: "MiniMax-M2.5-highspeed"      # Fast model (~100 TPS, 2x cost)

  # Model registry: maps model names (used in agent .md files) to providers.
  # Built-in entries (MiniMax-M2.5, MiniMax-M2.5-highspeed) route through
  # the Ember hosted endpoint and are always available.
  # Add entries here to override built-ins or register new models.
  registry:
    # Example: bypass Ember hosted endpoint, use MiniMax directly
    # MiniMax-M2.5:
    #   provider: openai_like
    #   model_id: MiniMax-Text-01
    #   url: https://api.minimaxi.chat/v1
    #   api_key_env: MINIMAX_API_KEY

    # Example: add OpenAI
    # gpt-4o:
    #   provider: openai_like
    #   model_id: gpt-4o
    #   url: https://api.openai.com/v1
    #   api_key_env: OPENAI_API_KEY

    # Example: add Anthropic
    # claude-sonnet:
    #   provider: openai_like
    #   model_id: claude-sonnet-4-6
    #   url: https://api.anthropic.com/v1
    #   api_key_env: ANTHROPIC_API_KEY

    # Example: local Ollama model
    # local-llama:
    #   provider: openai_like
    #   model_id: llama3.3:70b
    #   url: http://localhost:11434/v1

    # Example: OpenRouter (access to many models)
    # openrouter-minimax:
    #   provider: openai_like
    #   model_id: minimax/minimax-m2.5
    #   url: https://openrouter.ai/api/v1
    #   api_key_env: OPENROUTER_API_KEY

# Permission levels
permissions:
  # "ask" = confirm before use, "allow" = auto-allow, "deny" = block
  file_write: "ask"
  file_read: "allow"
  shell_execute: "ask"
  shell_restricted: "allow"       # read-only commands (rg, find, tree)
  web_search: "deny"
  web_fetch: "deny"
  git_push: "ask"
  git_destructive: "ask"          # force-push, reset --hard, etc.

# Safety
safety:
  sandbox_shell: false             # Run shell commands in sandbox
  protected_paths:                 # Paths that cannot be written to
    - ".env"
    - ".env.*"
    - "*.pem"
    - "*.key"
    - "credentials.*"
    - "secrets.*"
  blocked_commands:                # Shell commands that are always blocked
    - "rm -rf /"
    - ":(){ :|:& };:"
  max_file_size_kb: 500            # Max file size for reads (KB)
  require_confirmation:            # Actions that always require confirmation
    - "git push"
    - "git push --force"
    - "npm publish"
    - "pip install"

# Memory & storage
storage:
  # Backend: "sqlite" (default, local), "postgres", "mongodb", "redis", "dynamodb", etc.
  # Agno supports 15+ storage backends. SQLite is the default for zero-config local use.
  # Use a remote backend (postgres, mongodb, etc.) to sync sessions across devices.
  backend: "sqlite"
  session_db: "~/.ember/sessions.db"   # SQLite path (when backend=sqlite)
  memory_db: "~/.ember/memory.db"      # SQLite path (when backend=sqlite)
  # Remote backend example (uncomment to sync across devices):
  # backend: "postgres"
  # db_url: "postgresql://user:pass@host:5432/ember_code"
  audit_log: "~/.ember/audit.log"      # Tool execution log
  max_history_runs: 10                       # Conversation turns to keep

# Project context
context:
  project_file: "ember.md"         # Project instructions file (like CLAUDE.md)
  auto_load:                       # Files to auto-load into context
    - "ember.md"
    - ".ember/config.yaml"
  ignore_patterns:                 # Patterns to exclude from search
    - "node_modules/"
    - ".git/"
    - "__pycache__/"
    - "*.pyc"
    - ".venv/"
    - "dist/"
    - "build/"

# Orchestration
orchestration:
  max_nesting_depth: 5             # Max recursive sub-team depth
  max_total_agents: 20             # Max agents per request
  sub_team_timeout: 120            # Seconds before sub-team times out

# Agents & Skills
# By default, only Ember Code directories are scanned.
# Enable cross_tool_support to also scan Claude Code and Codex directories.
agents:
  cross_tool_support: false        # true = also scan .claude/agents/, .codex/, etc.
  # Default dirs (always scanned):
  #   .ember/agents/              (project, committed)
  #   .ember/agents.local/        (project, gitignored)
  #   ~/.ember/agents/            (user global)
  # With cross_tool_support: true, also scans:
  #   .claude/agents/             (Claude Code project)
  #   ~/.claude/agents/           (Claude Code user global)
  #   AGENTS.md / .codex/         (Codex project)
  #   ~/.codex/                   (Codex user global)

skills:
  cross_tool_support: false        # true = also scan .claude/skills/
  auto_trigger: true               # Allow Orchestrator to auto-trigger skills
  # Default dirs (always scanned):
  #   .ember/skills/              (project, committed)
  #   .ember/skills.local/        (project, gitignored)
  #   ~/.ember/skills/            (user global)
  # With cross_tool_support: true, also scans:
  #   .claude/skills/             (Claude Code project)
  #   ~/.claude/skills/           (Claude Code user global)

# Embeddings — BYOM registry (same pattern as models.registry)
# Resolution: user registry → built-in → provider:model_id
embeddings:
  default: "ember"                 # Default embedder name
  registry:
    # Example: use Voyage AI
    # voyage:
    #   provider: openai_compatible
    #   model_id: voyage-3
    #   url: https://api.voyageai.com/v1
    #   api_key_env: VOYAGE_API_KEY
    #   dimensions: 1024

    # Example: use OpenAI native embedder
    # openai-embed:
    #   provider: openai
    #   model_id: text-embedding-3-small
    #   api_key_env: OPENAI_API_KEY
    #   dimensions: 1536

    # Example: local Ollama embeddings
    # local-embed:
    #   provider: openai_compatible
    #   model_id: nomic-embed-text
    #   url: http://localhost:11434/v1
    #   dimensions: 768

# Knowledge base (requires: pip install ember-code[knowledge])
knowledge:
  enabled: false                   # Enable ChromaDB knowledge base
  collection_name: "ember_knowledge"  # ChromaDB collection name
  chroma_db_path: "~/.ember/chromadb" # Path to ChromaDB storage
  max_results: 10                  # Max search results returned
  embedder: "ember"                # Embedder registry name (or provider:model_id)
  share: true                      # Sync knowledge to a git-friendly YAML file
  share_file: ".ember/knowledge.yaml"  # Knowledge file path (relative to project)
  auto_sync: true                  # Auto-sync on session start/end

# Learning (Agno LearningMachine)
learning:
  enabled: false                   # Enable learning across sessions
  user_profile: true               # Build user preference profiles
  user_memory: true                # Persist user-specific memories
  session_context: true            # Carry session context forward
  entity_memory: false             # Track entities across conversations

# Reasoning tools
reasoning:
  enabled: false                   # Add think/analyze tools to agents
  add_instructions: true           # Include reasoning instructions in prompt
  add_few_shot: false              # Include few-shot examples

# Guardrails
guardrails:
  pii_detection: false             # Detect PII in prompts (pre-hook)
  prompt_injection: false          # Detect injection attempts (pre-hook)
  moderation: false                # OpenAI moderation API (pre-hook)

# Display
display:
  markdown: true                   # Render markdown in terminal
  show_tool_calls: true            # Show which tools agents are using
  show_routing: false              # Show Router agent decisions
  show_reasoning: false            # Show reasoning chain steps
  color_theme: "auto"              # auto, dark, light
```

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `EMBER_API_KEY` | Ember Code account API key (for hosted models) | required if no custom model |
| `MINIMAX_API_KEY` | MiniMax API key (BYOM) | - |
| `OPENAI_API_KEY` | OpenAI API key (BYOM) | - |
| `ANTHROPIC_API_KEY` | Anthropic API key (BYOM) | - |
| `OPENROUTER_API_KEY` | OpenRouter API key (BYOM) | - |
| `EMBER_MODEL` | Override default model | `MiniMax-M2.5` |
| `EMBER_CONFIG` | Path to config file | auto-discovered |
| `EMBER_SANDBOX` | Enable shell sandboxing | `false` |
| `EMBER_LOG_LEVEL` | Logging verbosity | `warning` |
| `EMBER_NO_MEMORY` | Disable persistent memory | `false` |
| `VECTORBRIDGE_API_KEY` | VectorBridge cloud API key | - |
| `EMBER_SKIP_ONBOARDING` | Skip first-run onboarding | `false` |
| `CHROMADB_PATH` | Override ChromaDB storage path | `~/.ember/chromadb` |

## CLI Flags

```bash
# Model selection
ignite-ember --model MiniMax-M2.5
ignite-ember --model MiniMax-M2.5-highspeed  # faster variant
ignite-ember --model gpt-4o                  # use OpenAI

# Safety modes
ignite-ember --sandbox               # sandbox all shell commands
ignite-ember --no-web                # disable web access
ignite-ember --read-only             # no file modifications

# Display
ignite-ember --verbose               # show routing + reasoning
ignite-ember --quiet                 # minimal output
ignite-ember --no-color              # disable colors

# TUI mode (default — use --no-tui to fall back to plain Rich CLI)
ignite-ember --no-tui                # disable TUI, use plain Rich CLI output

# Session
ignite-ember --resume                # resume last session
ignite-ember --resume <session-id>   # resume specific session
ignite-ember --no-memory             # disable persistent memory

# Direct execution
ignite-ember -m "add tests for auth module"   # non-interactive single task
cat src/auth.py | ignite-ember -p              # pipe stdin as context
```

## Project Instructions (ember.md)

Similar to Claude Code's `CLAUDE.md`, place an `ember.md` file in your project root with project-specific instructions:

```markdown
# Project: My API

## Stack
- Python 3.12, FastAPI, SQLAlchemy, PostgreSQL
- Tests: pytest with fixtures in conftest.py

## Conventions
- Use snake_case for all Python identifiers
- All endpoints must have OpenAPI docstrings
- Database models go in src/models/
- API routes go in src/routes/

## Important
- Never modify migration files after they've been applied
- The .env file contains production credentials — never read or log it
- Run `make test` to execute the full test suite
```

This file is loaded into context at session start and shared with all agents.

## Permission Modes

Quick permission presets for common scenarios:

```bash
# Default — asks for writes and shell commands
ignite-ember

# Permissive — auto-allows edits, asks for shell
ignite-ember --accept-edits

# Strict — asks for everything including reads
ignite-ember --strict

# CI/CD — auto-allows everything (use with caution)
ignite-ember --auto-approve
```

## Custom Agents

Drop Python files in `.ember/agents/` to add project-specific agents:

```markdown
# .ember/agents/deploy.md
---
name: deploy
description: Handles deployment to staging and production environments
tools: Bash, Read, Glob
model: MiniMax-M2.5
color: cyan

tags: [deploy, infrastructure, devops]
---

You handle deployment operations.

## Rules
- Always confirm before deploying to production
- Run smoke tests after deployment
- Show the deployment plan before executing
```

Custom agents are auto-discovered and added to the agent pool. The `model: MiniMax-M2.5` field is resolved through the model registry — no hardcoded provider classes needed.

## Custom Tools

Drop Python files in `.ember/tools/` to add project-specific tools:

```python
# .ember/tools/docker_helpers.py
from agno.tools import tool

@tool(description="Build and run the Docker dev environment")
def docker_dev_up() -> str:
    """Start the development Docker containers."""
    import subprocess
    result = subprocess.run(
        ["docker-compose", "-f", "docker-compose.dev.yml", "up", "-d"],
        capture_output=True, text=True
    )
    return result.stdout + result.stderr
```

Custom tools are available to all agents that have `ShellTools` or `PythonTools`.
