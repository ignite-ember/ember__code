---
name: review-pr
description: This skill should be used when the user asks to "review a PR", "review pull request", "check this PR", or mentions PR numbers. Performs comprehensive code review.
argument-hint: [pr-number]
allowed-tools: Read, Bash, Grep, Glob
---

Review a pull request with thorough, confidence-filtered analysis.

## Pre-flight Checks

1. **Determine the PR.** If `$ARGUMENTS` contains a PR number, use it. Otherwise, detect the current branch with `git branch --show-current` and find its open PR with `gh pr view --json number,state,isDraft -q '.number'`. If no PR is found, tell the user.

2. **Check PR state.** Run `gh pr view $PR --json state,isDraft`. If the PR is closed or merged, inform the user and stop. If it is a draft, note this but proceed with the review.

3. **Check for prior reviews.** Run `gh pr reviews $PR --json author,state` (or `gh api repos/{owner}/{repo}/pulls/$PR/reviews`). If you have already submitted a review on this PR, note this and ask the user if they want a fresh review.

## Gather Context

4. **Read the PR description.** Run `gh pr view $PR --json title,body,labels,baseRefName,headRefName`. Understand the stated intent — the review should judge the code against what the PR claims to do.

5. **Get the full diff.** Run `gh pr diff $PR`. Identify every changed file and the scope of changes.

6. **Read project guidelines.** Check for `ember.md`, `.editorconfig`, linter configs, or contributing guides. These inform what counts as a convention violation.

## Review Each File

7. For each changed file in the diff:
   a. **Read the full file** (not just the diff hunk) to understand surrounding context.
   b. **Evaluate against the checklist:**
      - **Bugs and logic errors** — off-by-one, null/undefined access, race conditions, incorrect branching.
      - **Security** — injection, auth bypass, secret exposure, unsafe deserialization, path traversal.
      - **Performance** — unnecessary allocations in loops, N+1 queries, missing indexes, unbounded growth.
      - **Missing tests** — new behavior without corresponding test coverage.
      - **Convention violations** — naming, file structure, patterns that conflict with the project's established style.
      - **Error handling** — swallowed exceptions, missing validation, unhelpful error messages.
   c. **Assign a confidence score (0-100)** to each finding based on how certain you are that it is a real issue.

## Filter and Validate

8. **Drop low-confidence findings.** Only report issues with confidence >= 80.

9. **Exclude false positives.** Remove findings that are:
   - Pre-existing issues not introduced by this PR.
   - Pure style nitpicks that a linter or formatter would catch.
   - Subjective preferences with no functional impact.
   - Suggestions that conflict with the project's stated conventions.

10. **Validate remaining issues.** For each surviving finding, re-read the relevant code to confirm it is a genuine problem and not a misunderstanding of context.

## Output Format

Start with a one-paragraph summary: what the PR does, overall quality, and whether it is ready to merge.

Then list findings grouped by severity:

### Critical
Issues that will cause data loss, security vulnerabilities, or crashes in production.

### High
Bugs, logic errors, or missing error handling that will cause incorrect behavior.

### Medium
Performance problems, missing tests for important paths, or convention violations that hurt maintainability.

### Low
Minor improvements, documentation gaps, or small readability wins.

For each finding:
- **File**: `path/to/file.ext:LINE`
- **Issue**: Clear description of the problem
- **Suggestion**: Concrete fix or direction
- **Confidence**: score/100

End with a verdict: **Approve**, **Request Changes**, or **Comment**.

## Edge Cases

- **No PR number and no current-branch PR:** Tell the user to provide a PR number.
- **Very large PR (>1000 lines changed):** Focus review on the most impactful files (core logic, security-sensitive, public API). Note that a full review was not feasible and recommend splitting the PR.
- **PR with no code changes (docs only):** Review for accuracy, formatting, and broken links. Adjust the checklist accordingly.
