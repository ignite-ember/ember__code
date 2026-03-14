---
name: simplify
description: This skill should be used when the user asks to "simplify", "clean up", "reduce complexity", or wants to review changed code for reuse, quality, and efficiency.
allowed-tools: Read, Edit, Grep, Glob, Bash
---

Review recently changed code for opportunities to simplify while preserving exact functionality.

## Ground Rules

1. **Preserve functionality.** Never change what the code does. Every simplification must be behavior-preserving. If you are not certain a change is safe, do not make it.

2. **Follow project standards.** Read `ember.md` (or equivalent project config) before making changes. Apply the project's conventions for naming, structure, and patterns. Do not impose outside conventions.

3. **Enhance clarity.** Reduce complexity and eliminate redundancy, but maintain readability. Fewer lines is not the goal — clearer intent is.

4. **Maintain balance.** Do not over-simplify. An abstraction that exists for a reason should stay. A three-line function that reads clearly should not be collapsed into a dense one-liner.

5. **Stay in scope.** Only simplify code that was recently changed. Do not refactor unrelated code unless the user explicitly asks.

## Steps

1. **Find what changed.** Run `git diff` to see unstaged changes, and `git diff --cached` for staged changes. If neither shows anything, run `git diff HEAD~1` to see the last commit's changes. If there are still no changes, ask the user what code they want simplified.

2. **Read project standards.** Check for `ember.md`, linter configs, `.editorconfig`, or style guides. These define what "correct" looks like for this project.

3. **Read each changed file in full.** Context matters — a function that looks redundant in isolation may serve a purpose in the broader module.

4. **Identify simplification opportunities.** Look for:
   - **Duplicated code** that can be extracted into a shared function.
   - **Overly complex logic** — deeply nested conditionals, long chains of if/else that could be a lookup table or early returns.
   - **Unnecessary abstractions** — wrapper functions that add no value, classes where a plain function would suffice.
   - **Dead code** — unreachable branches, unused variables, commented-out blocks.
   - **Verbose patterns** — manual iteration where a built-in method exists, redundant null checks, repeated boilerplate.

5. **Apply changes.** Make minimal, focused edits. One simplification per logical change so the user can review and understand each one.

6. **Run tests.** After making changes, run the project's test suite to verify nothing broke. If no test command is obvious, check `package.json`, `Makefile`, `pyproject.toml`, or equivalent. Report the test results.

## Anti-Patterns — Do NOT Do These

- **Do not make code "clever."** A readable five-line block is better than a dense one-liner using obscure language features.
- **Do not combine unrelated concerns.** If two functions do different things, do not merge them just because they share some lines.
- **Do not prioritize fewer lines over readability.** Line count is not a quality metric.
- **Do not remove defensive checks** unless you can prove they are unreachable.
- **Do not change public interfaces** (function signatures, API contracts, exported types) without warning the user about downstream impact.

## Edge Cases

- **No tests exist:** Warn the user that there is no automated way to verify the simplifications are safe. Recommend writing tests before or after simplifying, and proceed only with extra caution.
- **No recent changes:** Ask the user what code they would like simplified. Do not pick targets on your own.
- **Test suite fails before changes:** Inform the user that tests are already failing. Do not simplify code when you cannot establish a passing baseline.
- **Large changeset:** Prioritize the most complex or duplicated files first. Offer to continue with remaining files after the user reviews the initial batch.
