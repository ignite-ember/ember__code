# Tools

Ember Code leverages Agno's toolkit system to give agents capabilities. Each agent gets only the tools it needs — no more.

## Core Toolkits

Ember Code uses the **same tool names as Claude Code**. Each name maps to an Agno toolkit under the hood:

| Tool Name | Agno Toolkit | Description |
|---|---|---|
| `Read` | `FileTools(read_only=True)` | Read file contents |
| `Write` | `FileTools()` | Create/overwrite files |
| `Edit` | `EmberEditTools` (custom) | Targeted string-replacement editing |
| `Bash` | `ShellTools` | Shell command execution |
| `Grep` | `GrepTools` (custom) | Regex content search (ripgrep) |
| `Glob` | `GlobTools` (custom) | File pattern matching |
| `LS` | `ShellTools(commands=["ls"])` | List directory contents |
| `WebSearch` | `DuckDuckGoTools` or `TavilyTools` | Web search |
| `WebFetch` | `WebTools` (custom) | Fetch and extract URL content |
| `Orchestrate` | `OrchestrateTools` (custom) | Spawn sub-teams from agent pool |
| `Schedule` | `ScheduleTools` (custom) | Schedule tasks for later or recurring execution |
| `CodeIndex` | `CodeIndexTools` (custom) | Semantic search over pre-processed code intelligence |
| `Python` | `PythonTools` | Execute Python code |

---

## CodeIndex — Semantic Code Intelligence

CodeIndex is the most important tool in Ember Code's arsenal. While other tools operate on raw text (grep for patterns, read for contents), CodeIndex provides **pre-processed, semantic understanding** of the entire codebase.

See [CodeIndex](CODEINDEX.md) for the full documentation on categories, hierarchical summaries, indexing pipeline, and self-hosting.

### What It Does

CodeIndex pre-analyzes every entity in the codebase (files, classes, functions, modules, packages) and generates rich summaries across **six categories**: Code, Security, Testability, Architecture, Performance, and Maintainability.

Summaries are built **bottom-up** (function → class → file → module → project), giving agents multi-resolution understanding.

### Functions

- `search(query, categories?, entity_types?, limit?)` — semantic search across summaries
- `get_entity(path)` — get full summary for a specific entity (file, class, function)
- `get_children(path)` — get summaries of all children of an entity
- `get_references(path)` — get entities that reference or are referenced by a given entity
- `get_category(path, category)` — get a specific category summary (e.g., security analysis of a file)

### Why This Matters

Traditional code search is syntactic — `grep "authenticate"` finds the string, not the concept. CodeIndex is semantic:

| Query | Grep | CodeIndex |
|---|---|---|
| "how does auth work?" | Finds files with "auth" in the name/content | Returns the auth module summary with flow description, security analysis, and references to all related files |
| "what's vulnerable?" | Can't answer this | Returns security-category summaries flagging issues across the codebase |
| "where should I add rate limiting?" | Can't answer this | Returns architecture summaries of request-handling modules with dependency analysis |
| "what needs more tests?" | Can't answer this | Returns testability-category summaries ranking under-tested areas |

### Configuration

CodeIndex works out of the box with zero configuration. Per-project customization (categories, indexing options, ignore patterns) is planned for a future release.

### Fallback: Local Mode

If CodeIndex cloud is unavailable, Ember Code falls back to local tools (Grep, Glob, Read). The experience degrades gracefully — agents still work, just without semantic understanding.

---

## File Operations

### Read / Write (FileTools)

Read and write files on the local filesystem.

```python
from agno.tools.file import FileTools

# Read-only mode for Explorer/Reviewer
FileTools(read_only=True, base_dir="/path/to/project")

# Full access for Editor
FileTools(base_dir="/path/to/project")
```

**Functions:** `read_file`, `write_file`, `list_files`

### Edit (EmberEditTools)

Targeted string-replacement editing (inspired by Claude Code's Edit tool). Instead of rewriting entire files, it replaces specific text spans — producing minimal, reviewable diffs.

```python
from ember_code.tools.edit import EmberEditTools

# Performs old_string → new_string replacement
edit_tools = EmberEditTools(base_dir="/path/to/project")
```

**Functions:**
- `edit_file(path, old_string, new_string)` — replace a specific string in a file
- `edit_file_replace_all(path, old_string, new_string)` — replace all occurrences
- `create_file(path, content)` — create a new file (fails if exists)

**Why custom?** Agno's built-in `FileTools.write_file` overwrites the entire file. For coding, targeted edits are safer — they produce smaller diffs, reduce merge conflicts, and are easier to review.

---

## Search

### Grep (GrepTools)

Content search using ripgrep (`rg`), providing fast regex search across the codebase.

```python
from ember_code.tools.search import GrepTools

grep_tools = GrepTools(base_dir="/path/to/project")
```

**Functions:**
- `grep(pattern, path?, glob?, type?)` — search file contents with regex
- `grep_files(pattern, path?)` — return only matching file paths
- `grep_count(pattern, path?)` — return match counts per file

### Glob (GlobTools)

File pattern matching for finding files by name/path.

```python
from ember_code.tools.search import GlobTools

glob_tools = GlobTools(base_dir="/path/to/project")
```

**Functions:**
- `glob(pattern, path?)` — find files matching a glob pattern (e.g., `**/*.py`)

---

## Shell Execution

### Bash (ShellTools)

Execute shell commands with configurable restrictions.

```python
from agno.tools.shell import ShellTools

# Unrestricted (Editor Agent)
ShellTools(base_dir="/path/to/project")

# Restricted to specific commands (Explorer Agent)
ShellTools(
    base_dir="/path/to/project",
    commands=["rg", "find", "tree", "wc", "cat", "head", "tail"],
)
```

**Functions:** `run_shell_command(command, timeout?)`

**Safety:** Commands are validated before execution. See [Configuration](CONFIGURATION.md) for sandboxing options.

---

## Web Access

### WebSearch (DuckDuckGoTools)

Web search without API keys.

```python
from agno.tools.duckduckgo import DuckDuckGoTools

web_search = DuckDuckGoTools()
```

**Functions:** `duckduckgo_search(query)`, `duckduckgo_news(query)`

### WebFetch (WebTools)

Fetch and extract content from URLs.

```python
from ember_code.tools.web import WebTools

web_tools = WebTools()
```

**Functions:**
- `fetch_url(url)` — fetch URL content, extract text
- `fetch_json(url)` — fetch and parse JSON

---

## Python Execution

### Python (PythonTools)

Execute Python code in a sandboxed environment.

```python
from agno.tools.python import PythonTools

python_tools = PythonTools(
    base_dir="/path/to/project",
    pip_install=True,  # allow installing packages
)
```

**Functions:** `run_python_code(code)`, `pip_install(package)`, `read_file(path)`, `list_files(path)`

---

## Git & GitHub

Git operations are handled via `ShellTools` with git/gh commands. The Git Agent wraps these with safety checks:

- **Pre-push confirmation** — always asks before pushing
- **Force-push protection** — warns and requires explicit confirmation
- **Destructive operation guards** — `reset --hard`, `clean -f`, `branch -D` require approval

---

## Knowledge Base

### Knowledge (KnowledgeManager)

Built-in vector knowledge base powered by ChromaDB and the Ember embeddings API. Unlike CodeIndex (which provides pre-processed semantic code intelligence), the Knowledge system is a general-purpose document store that users can populate with any content.

```yaml
knowledge:
  enabled: true
  collection_name: "my_project"
  embedder: "ember"            # uses Ember server's /v1/embeddings (384-dim)
```

**Slash commands:**
- `/knowledge` — show knowledge base status (document count, collection info)
- `/knowledge add <url|path|text>` — add content to the knowledge base
- `/knowledge search <query>` — search the knowledge base

**How it works:**
1. `EmberEmbedder` calls the Ember server's `/v1/embeddings` endpoint (proxying to text2vec-transformers, 384 dimensions)
2. Documents are chunked and stored in ChromaDB with vector embeddings
3. Agents can search the knowledge base automatically during execution via Agno's `Knowledge` integration

**Data models (Pydantic):** `KnowledgeAddResult`, `KnowledgeSearchResponse`, `KnowledgeFilter`, `KnowledgeStatus`

**Requires:** `pip install ember-code[knowledge]` (installs `chromadb`)

---

## Task Scheduling

### Schedule (ScheduleTools)

Enables agents to schedule tasks for later or recurring execution. All agents with tools automatically get scheduling capabilities.

**Functions:**
- `schedule_task(description, when)` — schedule a task for later execution
- `list_scheduled_tasks(include_done?)` — check scheduled tasks and their status
- `cancel_scheduled_task(task_id)` — cancel a pending or recurring task

**Time formats:**
- One-shot: `"in 30 minutes"`, `"at 5pm"`, `"tomorrow"`, `"2026-12-25 14:00"`
- Recurring: `"daily"`, `"daily at 9am"`, `"hourly"`, `"every 2 hours"`, `"weekly"`

**Configuration:**
```yaml
scheduler:
  poll_interval: 30       # seconds between checking for due tasks
  task_timeout: 300       # max seconds per task (5 min default)
  max_concurrent: 1       # bounded concurrency (sequential by default)
```

Scheduled tasks run in the background via `SchedulerRunner` with bounded concurrency (`asyncio.Semaphore`) and per-task timeout (`asyncio.wait_for`). Toast notifications appear in the TUI when tasks complete or fail.

---

## Orchestration

### Orchestrate (OrchestrateTools)

Enables agents to spawn sub-teams at runtime. Any agent with `can_orchestrate: true` (the default) gets access to this tool.

```python
from ember_code.tools.orchestrate import OrchestrateTools

orchestrate = OrchestrateTools(pool=agent_pool, config=settings)
```

**Functions:**
- `spawn_team(task, agent_names?, mode?)` — spawn a sub-team to handle a task. The Orchestrator picks agents and mode if not specified.
- `spawn_agent(task, agent_name)` — spawn a single agent for a focused sub-task.

**Depth limits:** Configurable via `orchestration.max_nesting_depth` (default: 5) and `orchestration.max_total_agents` (default: 20). See [Security](SECURITY.md) for details.

---

## Custom Tools

You can add custom tools using Agno's `@tool` decorator:

```python
from agno.tools import tool

@tool(description="Run the project's test suite")
def run_tests(test_path: str = "") -> str:
    """Run tests, optionally filtering by path."""
    import subprocess
    cmd = ["pytest", "-v"]
    if test_path:
        cmd.append(test_path)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_dir)
    return result.stdout + result.stderr
```

Place custom tools in `~/.ember/tools/` or `.ember/tools/` for project-level tools. They're automatically discovered and available to agents.

---

## Tool Access by Built-in Agent

Each built-in agent's tools are declared in its `.md` file. This table shows the defaults:

| Tool | Explorer | Architect | Planner | Editor | Simplifier | Reviewer | Security | QA | Debugger | Git | Conversational |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `Read` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - |
| `Write` | - | - | - | yes | - | - | - | yes | - | - | - |
| `Edit` | - | - | - | yes | yes | - | - | yes | yes | - | - |
| `Grep` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - |
| `Glob` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - |
| `Bash` | - | - | - | yes | yes | - | - | yes | yes | yes | - |
| `LS` | yes | yes | yes | - | - | yes | yes | - | - | - | - |
| `WebSearch` | yes | yes | yes | - | - | yes | yes | - | - | - | - |
| `WebFetch` | yes | - | - | - | - | yes | - | - | - | - | - |
| `Orchestrate` | yes | yes | yes | yes | yes | yes | yes | yes | yes | yes | - |

Since agents are `.md` files, you can change any agent's tools by editing its definition or overriding it in `.ember/agents/`.
