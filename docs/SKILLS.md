# Skills

Skills are reusable prompted workflows invoked via slash commands. While [agents](AGENTS.md) define **who** does the work (tools, model, system prompt), skills define **what** to do (step-by-step instructions, templates, guidelines).

```
Agents = persistent identities with tools        "I am an editor agent"
Skills = reusable task recipes invoked on demand  "/deploy staging"
```

Skills use the **same format as Claude Code** — `SKILL.md` files with YAML frontmatter. Claude Code skills work in Ember Code out of the box.

---

## Skill File Format

Each skill lives in a named directory containing a `SKILL.md` file:

```
.ember/skills/
├── deploy/
│   └── SKILL.md
├── review-pr/
│   ├── SKILL.md
│   └── templates/
│       └── review-checklist.md
└── migrate-component/
    ├── SKILL.md
    └── examples/
        └── react-to-vue.md
```

### Example

```markdown
---
name: deploy
description: This skill should be used when the user asks to "deploy", "push to staging", "release to production", or mentions deployment pipelines. Handles the full deployment workflow with safety checks.
version: 0.1.0
argument-hint: [environment]
allowed-tools: Read, Bash, Grep, Glob
---

Deploy the application to $ARGUMENTS environment.

## Steps
1. Run the test suite — abort if any tests fail
2. Check for uncommitted changes — abort if dirty
3. Build the application
4. Deploy to the target environment
5. Run smoke tests against the deployed version
6. Report deployment status

## Safety
- Always confirm before deploying to production
- Never deploy if tests are failing
- Show the diff between current and deployed versions before proceeding
```

---

## Frontmatter Fields

**Claude Code compatible fields:**

| Field | Type | Description |
|---|---|---|
| `name` | string | Skill identifier (defaults to directory name if omitted) |
| `description` | string | When to use this skill — the Orchestrator reads this to decide when to trigger |
| `version` | string | Semantic version (informational) |
| `argument-hint` | string | Hint shown in autocomplete (e.g., `[environment]`, `[file-path]`) |
| `allowed-tools` | string | Comma-separated tool names (restricts which tools are available) |
| `model` | string | Model override (`inherit`, `MiniMax-M2.5`, etc.) |
| `context` | string | `fork` = run in isolated sub-agent, default = run inline |
| `agent` | string | When `context: fork`, which agent type to use |
| `disable-model-invocation` | bool | If `true`, only the user can invoke (not auto-triggered) |
| `user-invocable` | bool | If `false`, only the Orchestrator can invoke (not user slash command) |

### The `description` Field

The description is how the Orchestrator decides when to auto-trigger a skill. Write it in third person with specific trigger phrases:

**Weak** (won't trigger reliably):
```yaml
description: Provides guidance for deployments.
```

**Strong** (triggers reliably):
```yaml
description: This skill should be used when the user asks to "deploy", "push to staging", "release to production", "ship it", or mentions deployment pipelines and environments.
```

---

## String Substitutions

| Variable | Description |
|---|---|
| `$ARGUMENTS` | All arguments passed to the skill |
| `$ARGUMENTS[0]`, `$1` | Specific argument by index |
| `${EMBER_SESSION_ID}` | Current session ID |
| `${EMBER_SKILL_DIR}` | Directory containing the SKILL.md |

Example:
```markdown
Review pull request $1.
Fetch the diff: `gh pr diff $1`
Read the description: `gh pr view $1`
```

Invoked as `/review-pr 123` → `$1` becomes `123`, `$ARGUMENTS` becomes `123`.

---

## Skill Directories

By default, skills are loaded from **Ember Code directories only**:

| Location | Scope | Shared? |
|---|---|---|
| `.ember/skills/` | Project | Yes (commit to repo) |
| `.ember/skills.local/` | Project | No (gitignored) |
| `~/.ember/skills/` | User (all projects) | No |
| `<install>/skills/` | Built-in | Shipped with Ember Code |

Name conflicts: project-level wins over user-level, which wins over built-in.

### Cross-Tool Support (opt-in)

Enable `cross_tool_support` to also scan Claude Code directories:

```yaml
# .ember/config.yaml
skills:
  cross_tool_support: true
```

When enabled, these additional directories are scanned:

| Location | Scope |
|---|---|
| `.claude/skills/` | Claude Code (project) |
| `~/.claude/skills/` | Claude Code (user) |

Within the same scope, Ember Code directories take precedence over Claude Code.

---

## How Skills Are Invoked

### Manual — Slash Command

```
/deploy staging
/review-pr 123
/migrate-component SearchBar React Vue
```

Type `/` followed by the skill name. Arguments are passed as `$ARGUMENTS`.

### Automatic — Orchestrator Triggers

The Orchestrator reads all skill descriptions (metadata) into context. When a user message matches a skill's description, the Orchestrator loads the full skill and incorporates it into the team's instructions.

```
User: "deploy to staging"
  → Orchestrator sees deploy skill description matches
  → Loads full SKILL.md
  → Assembles team with skill instructions
```

This means skills can fire without the user explicitly typing `/deploy` — the Orchestrator recognizes intent.

**Auto-trigger requires `auto_trigger: true`** (the default) in config:

```yaml
# .ember/config.yaml
skills:
  auto_trigger: true    # default — Orchestrator can auto-trigger skills
```

Set `auto_trigger: false` globally, or `disable-model-invocation: true` per-skill, to require explicit `/command` invocation.

**Example: how auto-trigger works end-to-end**

Given this skill:
```yaml
description: This skill should be used when the user asks to "deploy", "push to staging", "release to production", or "ship it".
```

These user messages would all trigger it automatically:
- "deploy to staging"
- "ship it to production"
- "push the latest build to staging"
- "can you release v2.1?"

The Orchestrator loads all skill descriptions (~100 words each) into its context window. When a user message matches, it loads the full SKILL.md body and assembles a team to execute it.

### Invocation Control

| Setting | User `/command` | Orchestrator auto-trigger |
|---|---|---|
| Default | Yes | Yes |
| `disable-model-invocation: true` | Yes | No |
| `user-invocable: false` | No | Yes |

Use `disable-model-invocation: true` for skills that should only run when explicitly requested (e.g., destructive operations). Use `user-invocable: false` for internal skills that the Orchestrator should use as building blocks but users shouldn't invoke directly.

---

## Execution Modes

### Inline (Default)

Skill instructions are injected into the current conversation context. The Orchestrator assembles a team that follows the skill's steps.

```
User: "/review-pr 456"
  → Orchestrator loads review-pr SKILL.md
  → Assembles team: [explorer, reviewer] in coordinate mode
  → Explorer reads the diff and files
  → Reviewer analyzes for issues
  → Team follows the skill's output format
```

### Forked (`context: fork`)

Skill runs in an isolated sub-agent with its own context. The skill's body becomes the task prompt. Useful for long-running or side-effect-heavy workflows that shouldn't pollute the main conversation.

```yaml
---
name: deep-research
description: Research a topic thoroughly across the codebase
context: fork
agent: explorer
---

Research $ARGUMENTS thoroughly:
1. Find all relevant files using Glob and Grep
2. Use VectorBridge for semantic context
3. Read and analyze the code
4. Summarize findings with specific file:line references
```

When `context: fork` is set, the `agent` field specifies which agent type runs the skill. Available types:
- Any agent from the pool (by name): `explorer`, `editor`, `planner`, etc.
- The Orchestrator can also assemble a team for forked skills when the task is complex

---

## Supporting Files

Skills can include additional files beyond `SKILL.md`:

```
my-skill/
├── SKILL.md                    # Main instructions (loaded on invoke)
├── references/
│   └── detailed-guide.md       # In-depth documentation
├── examples/
│   └── working-example.md      # Usage examples
├── templates/
│   └── output-template.md      # Template for agent to fill
└── scripts/
    └── validate.sh             # Helper scripts (not loaded, executed via Bash)
```

Reference these from SKILL.md so agents know they exist:

```markdown
For the full API reference, read `${EMBER_SKILL_DIR}/references/detailed-guide.md`.
Use `${EMBER_SKILL_DIR}/templates/output-template.md` as the output format.
```

Agents read supporting files on demand via the Read tool. This keeps the initial context small.

---

## Progressive Disclosure

Skills use a three-level context loading strategy to stay within token budgets:

1. **Metadata** (always in context) — `name` + `description` (~100 words). The Orchestrator reads this to decide relevance.
2. **SKILL.md body** (loaded on invoke) — core instructions and guidelines. Keep under 2,000 words.
3. **Supporting files** (loaded as needed) — detailed docs, examples, templates. Agents read these via Read tool when they need more detail.

This means a project with 50 skills adds only ~5,000 tokens of metadata to context. Full skill bodies are loaded only when triggered.

---

## Built-in Skills

Ember Code ships with built-in skills in `<install>/skills/`:

| Skill | Description |
|---|---|
| `/commit` | Create a well-formatted git commit with conventional message |
| `/review-pr [number]` | Review a pull request for quality, security, and correctness |
| `/explain [path]` | Deep-dive explanation of a file or module using VectorBridge |
| `/simplify` | Review changed code for reuse, quality, and efficiency |
| `/onboard` | Run the full onboarding flow |
| `/propose-agents` | Propose project-specific agents based on current project |
| `/evals run` | Run agent evaluations |

Override any built-in skill by creating a skill with the same name in `.ember/skills/`.

---

## Examples

### PR Review with VectorBridge

```markdown
---
name: review-pr
description: This skill should be used when the user asks to "review a PR", "review pull request", "check this PR", or mentions PR numbers. Performs comprehensive code review with security and performance analysis.
argument-hint: [pr-number]
allowed-tools: Read, Grep, Glob, Bash, VectorBridge
---

Review pull request $1.

## Steps
1. Fetch the PR diff: `gh pr diff $1`
2. Read the PR description: `gh pr view $1`
3. For each changed file:
   a. Read the full file for context
   b. Search VectorBridge for the security and architecture category summaries
   c. Identify potential issues
4. Check for:
   - Bugs and logic errors
   - Security vulnerabilities (use VectorBridge security category)
   - Performance concerns
   - Missing tests
   - Style/convention violations
5. Summarize findings with severity levels

## Output Format
For each finding:
- **Severity**: Critical / High / Medium / Low / Nit
- **File**: path:line
- **Issue**: What's wrong
- **Suggestion**: How to fix it
```

### Database Migration

```markdown
---
name: migrate-db
description: This skill should be used when the user asks to "create a migration", "add a column", "modify the schema", "database migration", or mentions Alembic/Knex/Prisma migrations.
argument-hint: [description]
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, VectorBridge
---

Create a database migration for: $ARGUMENTS

## Steps
1. Search VectorBridge (architecture category) to understand the current schema patterns
2. Find existing migrations to follow naming conventions
3. Detect the migration framework (Alembic, Knex, Prisma, raw SQL)
4. Generate the migration file following the project's conventions
5. Run `migrate check` or equivalent to validate
6. Show the migration and ask for confirmation before finalizing

## Safety
- Never run destructive migrations (DROP, TRUNCATE) without explicit confirmation
- Always create a reversible migration when possible
- Check for dependent foreign keys before schema changes
```

### Component Scaffolding

```markdown
---
name: scaffold
description: This skill should be used when the user asks to "scaffold", "create a new component", "generate boilerplate", "bootstrap a module", or wants to create a new file from a project template.
argument-hint: [type] [name]
allowed-tools: Read, Write, Grep, Glob, VectorBridge
---

Scaffold a new $1 named $2.

## Steps
1. Search VectorBridge for existing $1 patterns in the project
2. Find the most similar existing $1 to use as a template
3. Create the new $1 following the project's conventions:
   - File location (match existing patterns)
   - Naming conventions
   - Import patterns
   - Test file placement
4. Create a corresponding test file
5. Add any necessary imports/registrations in parent modules

## Conventions
Follow the project's existing patterns exactly. Do NOT invent new conventions.
Read at least 2 existing examples before generating.
```

### Forked: Background Test Runner

```markdown
---
name: test-watch
description: Run tests in the background and report results
context: fork
agent: editor
disable-model-invocation: true
---

Run the project's test suite and report results:

1. Detect the test framework (pytest, jest, cargo test, etc.)
2. Run the full suite: capture output
3. If failures: summarize each failing test with file:line and error message
4. If all pass: report success with count and duration
```

---

## Skills vs Agents vs Hooks

| Concept | What It Is | Example |
|---|---|---|
| **Agent** | A persistent identity with tools and a system prompt | "I am a code reviewer" |
| **Skill** | A reusable task recipe invoked on demand | "/review-pr 123" |
| **Hook** | A shell command that fires on tool events | "Run prettier after every Edit" |

- **Agents** do the work. They have tools, models, and specialized knowledge.
- **Skills** describe the work. They provide step-by-step instructions that agents follow.
- **Hooks** automate around the work. They fire before/after tool calls for validation and side effects.

Skills are executed **by** agents. When you invoke `/review-pr 123`, the Orchestrator reads the skill, picks the right agents (explorer + reviewer), assembles a team, and the agents follow the skill's instructions.

---

## Claude Code Compatibility

Ember Code skills use the **same format** as Claude Code:
- Same `SKILL.md` file in named directory
- Same frontmatter fields (`name`, `description`, `context`, `agent`, `allowed-tools`, etc.)
- Same string substitutions (`$ARGUMENTS`, `$1`, `${CLAUDE_SKILL_DIR}` mapped to `${EMBER_SKILL_DIR}`)
- Same directory scoping (`.claude/skills/` is scanned alongside `.ember/skills/`)

Claude Code skills work in Ember Code out of the box. The key difference: in Ember Code, skills can leverage VectorBridge for semantic understanding and the Orchestrator distributes skill instructions across a coordinated team — not just a single agent loop.

---

## Creating Custom Skills

### Minimal

```
.ember/skills/my-skill/SKILL.md
```

```markdown
---
name: my-skill
description: Does the thing when user asks to "do the thing"
---

Do the thing.
```

That's it. It's immediately available as `/my-skill`.

### With Arguments

```markdown
---
name: explain
description: Deep-dive explanation of a file or module
argument-hint: [file-or-directory]
allowed-tools: Read, Grep, Glob, VectorBridge
---

Explain $ARGUMENTS in depth.

1. Get the VectorBridge summary for $1 (all categories)
2. Read the actual source code
3. Trace key execution paths
4. Explain the design decisions and trade-offs
5. Note any issues from security/performance/testability categories
```

### With Supporting Files

```markdown
---
name: api-endpoint
description: Create a new API endpoint following project conventions
argument-hint: [method] [path]
---

Create a new $1 endpoint at $2.

Follow the conventions documented in `${EMBER_SKILL_DIR}/references/api-conventions.md`.
Use `${EMBER_SKILL_DIR}/templates/endpoint.py` as a starting template.
```

---

## Configuration

```yaml
# .ember/config.yaml

skills:
  cross_tool_support: false        # true = also scan .claude/skills/ directories
  auto_trigger: true               # Allow Orchestrator to auto-trigger skills
  max_metadata_tokens: 5000        # Token budget for skill metadata in context
```
