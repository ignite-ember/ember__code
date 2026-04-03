---
name: update-docs
description: This skill should be used when the user asks to "update docs", "sync documentation", "refresh docs", "generate changelog", "update TODO", or wants documentation to reflect recent code changes.
argument-hint: [scope: all|readme|todo|changelog|progress|agents|architecture|config]
---

Update project documentation to reflect the current state of the codebase.

## Context

Gather the following before doing anything else:

- Recent changes: !`git log --oneline -20`
- Current branch: !`git branch --show-current`
- Modified files since last doc update: !`git diff --name-only HEAD~5`
- Existing documentation files: !`find docs/ -name "*.md" -type f 2>/dev/null; ls *.md 2>/dev/null`

## Scope

If `$ARGUMENTS` is provided, treat it as the scope — update only the specified area:
- `all` — Full documentation audit and update (default if no argument)
- `readme` — Update README.md only
- `todo` — Regenerate TODO.md from codebase scan
- `changelog` — Update CHANGELOG.md from git history
- `progress` — Regenerate PROGRESS.md dashboard and all docs/progress/*.md feature reports
- `agents` — Update docs/AGENTS.md from agent definitions
- `architecture` — Update docs/ARCHITECTURE.md from current code structure
- `config` — Update docs/CONFIGURATION.md from config source files

If no argument is provided, default to `all`.

## Steps

### 1. Determine what changed

Run `git log --oneline -20` and `git diff --name-only HEAD~10` to understand recent changes. Categorize changes by area:
- **Agent changes**: files in `agents/`
- **Skill changes**: files in `skills/`
- **Config changes**: files in `src/ember_code/config/`
- **Tool changes**: files in `src/ember_code/tools/`
- **TUI changes**: files in `src/ember_code/tui/`
- **Core changes**: other files in `src/ember_code/`
- **Infrastructure**: `pyproject.toml`, `Makefile`, CI files

### 2. Update TODO.md

Scan the codebase for actionable items:

```bash
# Find all TODO/FIXME/HACK/XXX comments
grep -rn "TODO\|FIXME\|HACK\|XXX" src/ --include="*.py" | head -100
```

Use Grep (not Bash) to find these patterns. Organize into categories:

- **High Priority**: FIXME items and critical TODOs
- **Features**: Feature-related TODOs
- **Technical Debt**: HACK items, refactoring TODOs
- **Documentation**: Doc-related TODOs
- **Testing**: Test-related TODOs

Include the source file and line number for each item. Format as a markdown checklist.

### 3. Update CHANGELOG.md

Generate from git history using [Keep a Changelog](https://keepachangelog.com/) format:

1. Run `git log --oneline` to get the full commit history (or since last tagged version).
2. Group commits into categories: Added, Changed, Fixed, Removed.
3. Rewrite commit messages to be user-facing — describe the impact, not the implementation.
4. If versions/tags exist, group by version. Otherwise, group by date.

### 4. Update PROGRESS.md and docs/progress/

Generate feature progress reports by scanning each module:

**For each feature module** (`auth`, `config`, `hooks`, `knowledge`, `mcp`, `memory`, `prompts`, `session`, `skills`, `tools`, `tui`, plus `orchestrator.py`/`pool.py`/`team_builder.py`, `agents/*.md`, `skills/*/SKILL.md`):

1. **Count files and lines**: Use Glob to list all `.py` files in the module. Read key files to understand what's implemented.
2. **Find stubs**: Use Grep to search for `pass`, `raise NotImplementedError`, `...` (ellipsis) as function bodies — these indicate unfinished work.
3. **Find TODOs**: Use Grep for `TODO`, `FIXME`, `HACK`, `XXX` within the module.
4. **Check tests**: Use Glob to find matching test files in `tests/`.
5. **Get git activity**: Run `git log --oneline -5 -- src/ember_code/<module>/` to see recent commits.
6. **Assess status**:
   - `Planning` — Module directory exists but mostly stubs or empty
   - `In Progress` — Real implementation exists but has TODOs, stubs, or missing tests
   - `Done` — Fully implemented, tested, no critical TODOs
7. **Estimate completion**: Based on implemented vs stub functions, test coverage, and TODO count. Round to nearest 5%.

**Generate `docs/progress/<feature>.md`** for each feature with:
- Overview (from reading the code)
- Design decisions (from code patterns and comments)
- Implementation status (done/in-progress/planned checklists)
- File inventory table (file, purpose, lines, has-tests)
- Known issues (FIXMEs with file:line)
- Recent changes (git log for the module)
- Next steps (from TODOs and incomplete work)

**Generate `PROGRESS.md`** (root) with:
- Summary table of all features with status, completion %, and links to detail pages
- Recently Active section (features with commits in last 7 days)
- Blocked / Needs Attention section (features with FIXMEs or failing tests)
- Up Next section (features in Planning status)

### 5. Update README.md

Read the current README.md and compare against the actual codebase:

1. Verify the feature list matches implemented features.
2. Verify installation instructions still work.
3. Verify any code examples are correct.
4. Update the feature comparison table if features changed.
5. Ensure links to docs/ files are correct and complete.

### 6. Update docs/ files

For each documentation file in `docs/`, check if recent changes affect it:

1. **Read the doc file** to understand its current content.
2. **Read the relevant source code** to understand the current implementation.
3. **Compare and update** — fix any discrepancies, add new features, remove references to deleted features.

Priority order (update these first):
1. `docs/AGENTS.md` — if any agent definitions changed
2. `docs/SKILLS.md` — if any skill definitions changed
3. `docs/CONFIGURATION.md` — if config files changed
4. `docs/TOOLS.md` — if tool implementations changed
5. `docs/ARCHITECTURE.md` — if project structure changed
6. `docs/DEVELOPMENT.md` — if build/test process changed
7. All other docs as needed

### 7. Cross-reference audit

After all updates, verify consistency:

- Feature names are the same across all documents
- No broken cross-references between docs
- No documentation references code that no longer exists
- New agents/skills/tools appear in all relevant docs
- Table of contents or index pages are current
- PROGRESS.md links to all docs/progress/ files correctly

### 8. Report

Summarize what was updated:
- List each file modified with a one-line description of what changed
- Flag any areas where documentation is missing or uncertain
- Note any discrepancies found between docs and code that need human review

## Edge Cases

- **No recent changes**: If the working tree is clean and there are no recent commits, perform a full audit comparing all docs against current code. There may be drift from older changes.
- **New module with no docs**: Create documentation following the patterns of existing docs. Add it to any index or listing pages.
- **Removed feature still in docs**: Remove the documentation and update all cross-references. Note the removal in CHANGELOG.md.
- **Scope argument provided**: Only update the specified area. Skip all other steps. Still run the cross-reference audit for the affected files.
- **Very large changeset**: Prioritize user-facing docs (README, QUICKSTART) first, then reference docs. Offer to continue with remaining files.
