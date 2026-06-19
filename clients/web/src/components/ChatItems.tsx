import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark-dimmed.css";
import { formatStats, type ChatItem } from "../chat/model";
import type { DiffRow } from "../protocol/messages";
import { ChevronIcon } from "./Icons";
import { FilePill } from "./FilePill";
import { host } from "../lib/host";

const AT_PATH_INLINE_RE = /(?:^|\s)@(\S+)/g;

/** LLMs sometimes emit a whole GFM table on a single line (no
 *  newlines between header, separator, and rows). Detect a
 *  separator like `|---|---|...|` glued to surrounding pipe
 *  segments and split each `|...|` group onto its own line so
 *  ``remark-gfm`` can parse it. */
export function normalizeAssistantMarkdown(text: string): string {
  if (!text) return text;

  // Models frequently emit headings without a preceding/following
  // blank line, which CommonMark renders as a heading immediately
  // attached to the next paragraph — visually they glue together
  // (e.g. "Origins Beyond the MountainsBefore ever he walked…").
  // Insert blank lines around any line that starts with `# ` … `###### `
  // so a heading always renders as its own block. Same for fenced
  // code blocks: prepend a blank line so they don't get folded into
  // the previous paragraph.
  let out = text;

  // Heading on its own line — ensure blank line before AND after.
  // Match start-of-line `#`s followed by a space (ATX heading), but
  // skip already-blank-separated headings.
  out = out.replace(/([^\n])\n(#{1,6} )/g, "$1\n\n$2");
  out = out.replace(/(^|\n)(#{1,6} [^\n]*)\n([^\n#])/g, "$1$2\n\n$3");

  // Stuck-word heading: the model emitted the heading and the
  // following paragraph WITHOUT any whitespace between them, so the
  // entire paragraph reads as part of the heading. Example seen in
  // the wild: ``## Origins Beyond the MountainsBefore ever he walked
  // among the peoples…``. Detect by:
  //   - the line starts with an ATX heading
  //   - it contains a 4+ lowercase run immediately followed by a
  //     capital + word (lowercase letters) + space + more content —
  //     the trailing space + more proves it's a multi-word
  //     continuation, not a legitimate camelCase brand like
  //     "JavaScript" or "iPhone" (which have ≤3 lowercase before the
  //     capital and no trailing space-then-words pattern).
  // Apply per-line via the /m flag.
  out = out.replace(
    /^(#{1,6}\s\S.+?[a-z]{4})([A-Z][a-z]+\s.+)$/gm,
    "$1\n\n$2",
  );

  // Heading glued to a GFM table header on the same line. Seen in
  // the wild: ``### ✅ What's Solid| Area | Detail |``. Without a
  // blank line between the heading and the table, ReactMarkdown
  // parses the whole thing as a heading and the rest of the table
  // (divider + rows) becomes literal text. Split before the first
  // pipe that's surrounded by spaces (the table-cell separator).
  out = out.replace(
    /^(#{1,6}\s[^\n|]+?\S)(\s\|\s.+)$/gm,
    "$1\n\n$2",
  );

  // Heading glued to an opening code fence on the same line. Seen
  // in the wild: ``### Recommended Fix Order```\n1 …``. CommonMark
  // parses ``` as inline code inside the heading; the following
  // lines become a paragraph; and the closing ``` later in the
  // message opens a NEW fence that swallows the rest of the body.
  // Split so the fence starts on its own line.
  out = out.replace(
    /^(#{1,6}\s+\S[^\n`]*?)\s*(```[\w-]*)\s*$/gm,
    "$1\n\n$2",
  );

  // GFM table fix — keep the original behaviour: split a single-line
  // table back onto rows.
  if (out.includes("|") && /\|\s*-{2,}/.test(out)) {
    out = out
      .split("\n")
      .map((line) => {
        const trimmed = line.trim();
        if (!trimmed.startsWith("|") || !/\|\s*-{2,}/.test(trimmed)) return line;
        const cells = trimmed.split(/(?<=\|)\s+(?=\|)/g);
        if (cells.length < 2) return line;
        return cells.join("\n");
      })
      .join("\n");
  }

  return out;
}

/** Split a user message into:
 *   - ``[code-paste …]…[/code-paste]`` blocks → ``UserCodePill`` (the
 *     same inline pill the composer showed before send; click to
 *     toggle the snippet underneath).
 *   - Inline ``@<path>`` file pills (clickable, open-in-editor).
 *   - Plain text everywhere else.
 *
 *  The composer emits messages like
 *      "and @code:c1 then @code:c2"
 *  which submit-time expansion turns into
 *      "and [code-paste hello.py:9 lines=9-16]\n…\n[/code-paste]
 *       then [code-paste hello.py:19 lines=19-33]\n…\n[/code-paste]"
 *  — so the user bubble can match by tag instead of trying to
 *  reconstruct rendering from raw fenced code. */
const CODE_PASTE_RE =
  /\[code-paste (\S+):(\d+) lines=([^\]]+)\]\n([\s\S]*?)\n\[\/code-paste\]/g;

/** Edit-mode round-trip helper. Replace each ``[code-paste …]…[/code-paste]``
 *  block with a compact ``«code:path lines»`` placeholder and remember
 *  the original block in ``store`` so we can swap it back on save.
 *  Visible to the user in the textarea so they can reorder snippets
 *  by cut-and-paste, but they can't accidentally edit snippet content. */
function swapCodeBlocks(text: string, store: Map<string, string>): string {
  store.clear();
  let n = 0;
  return text.replace(CODE_PASTE_RE, (match, p1, _l, lineSpec) => {
    n += 1;
    const filename = String(p1).split("/").pop() || String(p1);
    const placeholder = `«code:${filename} ${lineSpec}#${n}»`;
    store.set(placeholder, match);
    return placeholder;
  });
}

/** Inverse of ``swapCodeBlocks``: walk the edited text and substitute
 *  each surviving placeholder for its original block. Placeholders the
 *  user deleted simply stay gone — i.e. removing the placeholder from
 *  the textarea removes the snippet from the message. */
function restoreCodeBlocks(text: string, store: Map<string, string>): string {
  return text.replace(/«code:[^«»]*?#\d+»/g, (placeholder) => {
    return store.get(placeholder) ?? "";
  });
}

function renderUserText(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  CODE_PASTE_RE.lastIndex = 0;
  while ((m = CODE_PASTE_RE.exec(text)) !== null) {
    if (m.index > last) out.push(...pillifyText(text.slice(last, m.index), out.length));
    out.push(
      <UserCodePill
        key={`cp-${m.index}`}
        path={m[1]}
        line={Number(m[2])}
        lineSpec={m[3]}
        snippet={m[4]}
      />,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...pillifyText(text.slice(last), out.length));
  return out.length ? out : [text];
}

/** @-pill pass over a slice of plain text. Pulled out of
 *  ``renderUserText`` so fenced-block bypassing can call it on the
 *  surrounding chunks. */
function pillifyText(text: string, keyOffset: number): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  AT_PATH_INLINE_RE.lastIndex = 0;
  while ((m = AT_PATH_INLINE_RE.exec(text)) !== null) {
    const tokenStart = m[0].startsWith("@") ? m.index : m.index + 1;
    if (tokenStart > last) out.push(text.slice(last, tokenStart));
    out.push(<FilePill key={`pill-${keyOffset}-${tokenStart}`} path={m[1]} />);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Inline pill rendered inside a user message bubble for pasted-code
 *  snippets. Visually matches the composer's code pill (same tinted
 *  background, same code-bracket icon, same "filename N-M" label).
 *  Clicking the pill toggles a code block underneath so the reader
 *  can inspect the snippet without losing the inline-pill UX. */
function UserCodePill({
  path,
  line,
  lineSpec,
  snippet,
}: {
  path: string;
  line: number;
  lineSpec: string;
  snippet: string;
}) {
  const [open, setOpen] = useState(false);
  const name = path.split("/").pop() || path;
  const label = `${name} ${lineSpec}`;
  return (
    <span className="user-code-pill-wrap">
      <button
        type="button"
        className="file-pill code-pill inline-pill"
        title={`${path}:${line} — click to open in editor (alt-click to preview snippet)`}
        onClick={(e) => {
          e.stopPropagation();
          // Plain click = open the file in the IDE and SELECT the
          // attached snippet (so a 5-line paste highlights all 5
          // lines, not just line 71). Alt-click toggles an inline
          // preview for reading without leaving the chat.
          if (e.altKey) {
            setOpen((v) => !v);
            return;
          }
          // ``lineSpec`` is the same string that built the pill label —
          // "71", "71-75", or "9,11-13" (non-contiguous matches).
          // Send the first contiguous range; that's the segment the
          // user actually attached. Hosts that don't grok the
          // ``-end`` suffix fall back to opening at start.
          const firstRange = lineSpec.split(",")[0].trim();
          void host.openFile(`${path}:${firstRange}`);
        }}
      >
        <span className="file-pill-icon" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path
              d="M5.5 4L2.5 8L5.5 12M10.5 4L13.5 8L10.5 12"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinecap="round"
              strokeLinejoin="round"
              fill="none"
            />
          </svg>
        </span>
        <span className="file-pill-name">{label}</span>
      </button>
      {open && (
        <div className="user-code-pill-snippet">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
          >
            {"```" + guessLang(path) + "\n" + snippet + "\n```"}
          </ReactMarkdown>
        </div>
      )}
    </span>
  );
}

/** Guess a highlight.js language ID from a path's extension. Picks
 *  from the languages bundled into highlight.js's "common" set —
 *  anything not on this list falls back to plain text, which is
 *  still readable, just not coloured. */
function guessLang(p: string): string {
  const ext = p.split(".").pop()?.toLowerCase() || "";
  const map: Record<string, string> = {
    py: "python",
    pyi: "python",
    ts: "typescript",
    tsx: "tsx",
    js: "javascript",
    jsx: "jsx",
    json: "json",
    rs: "rust",
    go: "go",
    java: "java",
    kt: "kotlin",
    rb: "ruby",
    sh: "bash",
    bash: "bash",
    zsh: "bash",
    yml: "yaml",
    yaml: "yaml",
    toml: "toml",
    md: "markdown",
    html: "xml",
    xml: "xml",
    css: "css",
    sql: "sql",
    c: "c",
    h: "c",
    cpp: "cpp",
    hpp: "cpp",
    swift: "swift",
  };
  return map[ext] || "";
}

/** Live progress card for team-orchestration runs. Renders the
 *  structured agent tree (one entry per spawned specialist) with
 *  per-agent status pills, tool-call rows, and a live content
 *  preview — no ASCII art. */
function OrchestrateLog({
  item,
  onStopTeam,
  onStopAgent,
  onRetryAgent,
}: {
  item: Extract<ChatItem, { kind: "orchestrate" }>;
  onStopTeam?: () => void;
  onStopAgent?: (runId: string) => void;
  onRetryAgent?: (agentName: string, newTask: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const agentList = item.order
    .map((p) => item.agents[p])
    .filter((a): a is NonNullable<typeof a> => !!a);
  const agentCount = agentList.length;
  const runningCount = agentList.filter(
    (a) => a.status === "running" || a.status === "paused",
  ).length;
  // Derive "still streaming" from the agents themselves rather than
  // relying on a separate flag — that flag only ever fired on
  // top-level run_completed, which doesn't land between consecutive
  // spawn_team calls and left previous cards stuck as "running".
  const streaming = runningCount > 0;
  const lastPreview =
    [...agentList]
      .reverse()
      .map((a) => a.previewLines[a.previewLines.length - 1])
      .find((p): p is string => !!p) || "";
  const totalTools = agentList.reduce((n, a) => n + a.tools.length, 0);
  const totalInTokens = agentList.reduce((n, a) => n + a.inputTokens, 0);
  const totalOutTokens = agentList.reduce((n, a) => n + a.outputTokens, 0);
  return (
    <div
      className={`orchestrate-log${open ? " open" : " collapsed"}${streaming ? " streaming" : ""}`}
    >
      <div
        className="orchestrate-head"
        title={open ? "Collapse team progress" : "Expand team progress"}
      >
        <button
          type="button"
          className={`orchestrate-head-toggle${open ? " open" : ""}`}
          onClick={() => setOpen((v) => !v)}
          title={open ? "Collapse" : "Expand"}
          aria-label={open ? "Collapse" : "Expand"}
        >
          <ChevronIcon size={14} />
        </button>
        <span className="orchestrate-title">Team progress</span>
        {streaming && (
          <span className="orchestrate-spinner" aria-label="Running" />
        )}
        <span
          className="orchestrate-meta"
          onClick={() => setOpen((v) => !v)}
          role="button"
          tabIndex={0}
        >
          <span className="orch-totals">
            {agentCount} {agentCount === 1 ? "agent" : "agents"}
            {runningCount > 0 && (
              <span className="orch-totals-running"> · {runningCount} running</span>
            )}
            {totalTools > 0 && (
              <span className="orch-totals-tools">
                {" · "}
                {totalTools} {totalTools === 1 ? "tool" : "tools"}
              </span>
            )}
            {(totalInTokens > 0 || totalOutTokens > 0) && (
              <span className="orch-totals-tokens">
                {" · "}
                ↓ {fmtTokens(totalInTokens)} · ↑ {fmtTokens(totalOutTokens)}
              </span>
            )}
          </span>
          {!open && lastPreview && (
            <span className="orch-totals-preview"> · {lastPreview.slice(0, 60)}</span>
          )}
        </span>
        {streaming && onStopTeam && (
          <button
            type="button"
            className="orch-stop-btn orch-stop-team"
            title="Stop the team — cancels all running agents"
            onClick={(e) => {
              e.stopPropagation();
              onStopTeam();
            }}
          >
            <StopGlyph />
            Stop team
          </button>
        )}
      </div>
      {open && (
        <div className="orchestrate-body">
          {agentList.length === 0 ? (
            <div className="orchestrate-empty">Waiting for the team to spin up…</div>
          ) : (
            agentList.map((a) => (
              <OrchestrateAgentRow
                key={a.path}
                agent={a}
                onStop={onStopAgent}
                onRetry={onRetryAgent}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

/** Compact 1000s formatter — 1234 → "1.2k", 230 → "230". Used in the
 *  agent header tokens chips so a run of 30k input tokens doesn't
 *  blow the layout. */
function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

/** Circular arrow — the universal "retry" glyph. Inlined so the
 *  Retry button doesn't pull a whole icon-set dependency. */
function RetryGlyph() {
  return (
    <svg
      width="11"
      height="11"
      viewBox="0 0 16 16"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ display: "inline-block", verticalAlign: "middle" }}
    >
      <path d="M2.5 8a5.5 5.5 0 1 0 1.6-3.9" />
      <path d="M2.2 2.5v3h3" />
    </svg>
  );
}

/** Filled square — the universal "stop" glyph. Inlined so the Stop
 *  buttons don't need to import from the lucide-style icon set. */
function StopGlyph() {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 10 10"
      aria-hidden="true"
      style={{ display: "inline-block", verticalAlign: "middle" }}
    >
      <rect x="1.5" y="1.5" width="7" height="7" rx="1" fill="currentColor" />
    </svg>
  );
}

function OrchestrateAgentRow({
  agent,
  onStop,
  onRetry,
}: {
  agent: import("../chat/model").OrchestrateAgent;
  onStop?: (runId: string) => void;
  onRetry?: (agentName: string, newTask: string) => void;
}) {
  // Open by default while the agent is still running so users see
  // its tools live; auto-collapse once it's done/errored to keep
  // the card compact. User can override either way by clicking.
  const [open, setOpen] = useState(agent.status === "running" || agent.status === "paused");
  const [retryOpen, setRetryOpen] = useState(false);
  const [retryDraft, setRetryDraft] = useState(agent.task);
  // Sync the draft when the agent's task arrives after first render
  // (the BE sometimes ships task on a slightly later event tick).
  if (agent.task && !retryDraft) setRetryDraft(agent.task);
  const toolCount = agent.tools.length;
  const doneTools = agent.tools.filter((t) => t.status === "done").length;
  const errorTools = agent.tools.filter((t) => t.status === "error").length;
  const runningTools = agent.tools.filter((t) => t.status === "running").length;
  const statusLabel = {
    running: "running",
    paused: "paused",
    done: "done",
    error: "error",
  }[agent.status];
  // "Failed or stopped" — the only states where retry makes sense.
  // (A "done" agent succeeded; no need to retry. A "running" one is
  // still going; let it finish or use Stop.)
  const retriable = agent.status === "error";
  return (
    <section className={`orch-agent card status-${agent.status}`}>
      <div className="orch-agent-head" title={`${agent.path} — ${agent.status}`}>
        <button
          type="button"
          className={`orch-agent-chevron${open ? " open" : ""}`}
          onClick={() => setOpen((v) => !v)}
          aria-label={open ? "Collapse" : "Expand"}
        >
          <ChevronIcon size={10} />
        </button>
        <span
          className="orch-agent-id"
          onClick={() => setOpen((v) => !v)}
          role="button"
          tabIndex={0}
        >
          <span className={`orch-agent-dot status-${agent.status}`} />
          <span className="orch-agent-name">{agent.name}</span>
          <span className={`orch-agent-status status-${agent.status}`}>{statusLabel}</span>
        </span>
        <span className="orch-agent-counts">
          {runningTools > 0 && (
            <span className="orch-count count-running" title={`${runningTools} running`}>
              {runningTools}
              <span className="orch-count-icon" aria-hidden="true">●</span>
            </span>
          )}
          {doneTools > 0 && (
            <span className="orch-count count-done" title={`${doneTools} done`}>
              {doneTools}
              <span className="orch-count-icon" aria-hidden="true">✓</span>
            </span>
          )}
          {errorTools > 0 && (
            <span className="orch-count count-error" title={`${errorTools} errored`}>
              {errorTools}
              <span className="orch-count-icon" aria-hidden="true">✗</span>
            </span>
          )}
          {toolCount === 0 && (
            <span className="orch-count count-empty">no tools yet</span>
          )}
          {(agent.inputTokens > 0 || agent.outputTokens > 0) && (
            <span
              className="orch-count count-tokens"
              title={`${agent.inputTokens.toLocaleString()} in · ${agent.outputTokens.toLocaleString()} out${agent.reasoningTokens ? ` · ${agent.reasoningTokens.toLocaleString()} reasoning` : ""}`}
            >
              ↓ {fmtTokens(agent.inputTokens)} · ↑ {fmtTokens(agent.outputTokens)}
            </span>
          )}
        </span>
        {(agent.status === "running" || agent.status === "paused") &&
          onStop &&
          agent.runId && (
            <button
              type="button"
              className="orch-stop-btn orch-stop-agent"
              title={`Stop ${agent.name} — siblings keep running`}
              onClick={(e) => {
                e.stopPropagation();
                onStop(agent.runId);
              }}
            >
              <StopGlyph />
              Stop
            </button>
          )}
        {retriable && onRetry && (
          <button
            type="button"
            className="orch-retry-btn"
            title={`Retry ${agent.name} — tweak the prompt and try again`}
            onClick={(e) => {
              e.stopPropagation();
              setRetryOpen((v) => !v);
            }}
          >
            <RetryGlyph />
            Retry
          </button>
        )}
      </div>
      {retryOpen && retriable && onRetry && (
        <div className="orch-agent-retry">
          <label className="orch-retry-label">
            Retry <strong>{agent.name}</strong> with a tweaked prompt:
          </label>
          <textarea
            className="orch-retry-textarea"
            value={retryDraft}
            placeholder={
              agent.task
                ? "Edit the original task above…"
                : "Describe what you want this agent to do instead…"
            }
            rows={Math.min(8, Math.max(3, retryDraft.split("\n").length))}
            autoFocus
            onChange={(e) => setRetryDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setRetryOpen(false);
                setRetryDraft(agent.task);
              } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                const trimmed = retryDraft.trim();
                if (trimmed) {
                  onRetry(agent.name, trimmed);
                  setRetryOpen(false);
                }
              }
            }}
          />
          <div className="orch-retry-bar">
            <span className="orch-retry-hint">
              ⌘↵ to send · Esc to cancel — the main agent decides how to act on this.
            </span>
            <button
              className="btn btn-sm"
              onClick={() => {
                setRetryOpen(false);
                setRetryDraft(agent.task);
              }}
            >
              Cancel
            </button>
            <button
              className="btn btn-sm btn-primary"
              disabled={!retryDraft.trim()}
              onClick={() => {
                onRetry(agent.name, retryDraft.trim());
                setRetryOpen(false);
              }}
            >
              Retry
            </button>
          </div>
        </div>
      )}
      {agent.previewLines.length > 0 && (
        <div className="orch-agent-preview-window">
          {agent.previewLines.map((line, i) => {
            const isLatest = i === agent.previewLines.length - 1;
            return (
              <div
                key={i}
                className={`orch-preview-line${isLatest ? " latest" : ""}`}
                title={line}
              >
                <span className="orch-preview-glyph" aria-hidden="true">
                  {isLatest ? "›" : "·"}
                </span>
                <span className="orch-preview-text">{line}</span>
              </div>
            );
          })}
        </div>
      )}
      {open && toolCount > 0 && (
        <div className="orch-agent-body">
          {agent.tools.map((t) => (
            <ToolCardView
              key={t.id}
              name={t.tool}
              args={t.args}
              status={t.status}
              result={t.result}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function DiffTable({ rows }: { rows: DiffRow[] }) {
  return (
    <table className="diff-table">
      <tbody>
        {rows.map(([text], i) => (
          <tr key={i} className={text.startsWith("+") ? "add" : text.startsWith("-") ? "del" : ""}>
            <td className="code">{text}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ToolCard({ item }: { item: Extract<ChatItem, { kind: "tool" }> }) {
  return (
    <ToolCardView
      name={item.name}
      args={item.args}
      status={item.status}
      result={item.result}
      diffRows={item.diffRows}
      agentName={item.agentName}
    />
  );
}

/** Shared visual for a tool execution. Used by ``ToolCard`` (top-level
 *  tools from the FE's chat stream) and by ``OrchestrateAgentRow``
 *  (tools fired by sub-agents inside a team-progress card). Same
 *  affordances either way: chevron, status dot, tool name, truncated
 *  args, expandable result/diff. */
export function ToolCardView({
  name,
  args,
  status,
  result,
  diffRows,
  agentName,
}: {
  name: string;
  args: string;
  status: "running" | "done" | "error";
  result: string;
  diffRows?: DiffRow[] | null;
  agentName?: string;
}) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(result || diffRows?.length);
  return (
    <div className="tool-card">
      <div className="tool-card-header" onClick={() => expandable && setOpen(!open)}>
        <span className={`tool-chevron ${open ? "open" : ""}`}>
          {expandable ? <ChevronIcon /> : null}
        </span>
        <span className={`tool-status ${status}`} />
        <span className="tool-name">{name}</span>
        <span className="tool-args">{args}</span>
        {agentName && (
          <span
            className="tool-agent-badge"
            title={`Called by sub-agent ${agentName}`}
          >
            {agentName}
          </span>
        )}
      </div>
      {open && diffRows?.length ? (
        <div className="tool-card-body">
          <DiffTable rows={diffRows} />
        </div>
      ) : open && result ? (
        <div className="tool-card-body">{result}</div>
      ) : null}
    </div>
  );
}

function UserMessage({
  item,
  onEdit,
  onDelete,
}: {
  item: Extract<ChatItem, { kind: "user" }>;
  onEdit?: (item: Extract<ChatItem, { kind: "user" }>, newText: string) => void;
  onDelete?: (item: Extract<ChatItem, { kind: "user" }>) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [draft, setDraft] = useState(item.text);
  /** When the message contains ``[code-paste …]…[/code-paste]`` blocks,
   *  the inline edit textarea swaps each one for a compact placeholder
   *  like ``«code:hello.py 9-16»`` while the user is editing. This map
   *  remembers the original block content so we can restore it on
   *  Save — so editing the prose around a snippet never silently loses
   *  the snippet content. */
  const blockMapRef = useRef<Map<string, string>>(new Map());

  // Strip BE-side framing tags before classifying / rendering — same
  // logic the read-only path used.
  const stripped = item.text
    .replace(/^<system-context>[\s\S]*?<\/system-context>\s*/, "")
    .replace(/^<attached-files>[\s\S]*?<\/attached-files>\s*/, "");
  const mode = stripped.startsWith("/")
    ? "command"
    : stripped.startsWith("$")
      ? "shell"
      : "chat";

  // The bubble is only mutable if the BE knows which run owns it (we
  // truncate by run_id). Without runId, the operation has no target —
  // hide the controls so the user doesn't get a confusing failure.
  const canMutate = !!item.runId && (onEdit || onDelete);

  if (editing && onEdit) {
    const submit = () => {
      // Restore [code-paste] blocks from their compact placeholders
      // before sending. Whatever the user typed around the
      // placeholders becomes the final message body; the snippets
      // themselves round-trip untouched.
      const restored = restoreCodeBlocks(draft.trim(), blockMapRef.current);
      if (!restored || restored === item.text) {
        setEditing(false);
        return;
      }
      onEdit(item, restored);
      setEditing(false);
    };
    return (
      <div className={`msg-user msg-user-editing mode-${mode}`}>
        <textarea
          className="msg-user-edit"
          value={draft}
          autoFocus
          rows={Math.min(8, Math.max(2, draft.split("\n").length))}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setEditing(false);
              blockMapRef.current = new Map();
              setDraft(swapCodeBlocks(item.text, blockMapRef.current));
            } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              submit();
            }
          }}
        />
        <div className="msg-user-edit-bar">
          <span className="msg-user-edit-hint">
            ⌘↵ to save · Esc to cancel — saving wipes the rest of the conversation
          </span>
          <button
            className="btn btn-sm"
            onClick={() => {
              setEditing(false);
              blockMapRef.current = new Map();
              setDraft(swapCodeBlocks(item.text, blockMapRef.current));
            }}
          >
            Cancel
          </button>
          <button
            className="btn btn-sm btn-primary"
            disabled={!draft.trim() || draft === item.text}
            onClick={submit}
          >
            Save & resend
          </button>
        </div>
      </div>
    );
  }

  const body = mode === "chat" ? renderUserText(item.text) : item.text;
  return (
    <div className={`msg-user mode-${mode}`}>
      {body}
      {canMutate && (
        <div className="msg-user-actions" onClick={(e) => e.stopPropagation()}>
          {confirmingDelete ? (
            <>
              <span className="msg-user-confirm-text">Delete this and everything after?</span>
              <button
                className="btn btn-sm"
                onClick={() => setConfirmingDelete(false)}
              >
                Cancel
              </button>
              <button
                className="btn btn-sm btn-danger"
                onClick={() => {
                  setConfirmingDelete(false);
                  onDelete?.(item);
                }}
              >
                Delete
              </button>
            </>
          ) : (
            <>
              {onEdit && (
                <button
                  className="msg-user-icon-btn"
                  title="Edit & resend (wipes the rest of the chat)"
                  aria-label="Edit message"
                  onClick={() => {
                    blockMapRef.current = new Map();
                    setDraft(swapCodeBlocks(item.text, blockMapRef.current));
                    setEditing(true);
                  }}
                >
                  <EditIcon />
                </button>
              )}
              {onDelete && (
                <button
                  className="msg-user-icon-btn msg-user-icon-danger"
                  title="Delete this and everything after"
                  aria-label="Delete message"
                  onClick={() => setConfirmingDelete(true)}
                >
                  <TrashIcon />
                </button>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function EditIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M11.4 2.6l2 2L5.5 12.5l-3 0.5 0.5-3z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor"
      strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 4.5h10M6 4.5V3a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1.5M4.5 4.5l.7 8.4a1 1 0 0 0 1 .9h3.6a1 1 0 0 0 1-.9l.7-8.4M7 7.5v4M9 7.5v4" />
    </svg>
  );
}

function CompactCard({
  item,
}: {
  item: Extract<ChatItem, { kind: "compact" }>;
}) {
  const hasSummary = !!item.summary.trim();
  return (
    <div className="compact-card">
      <div className="compact-card-head">
        <span className="compact-card-badge" aria-hidden="true">∑</span>
        <span className="compact-card-title">Context compacted</span>
        <span className="compact-card-status">{item.status}</span>
      </div>
      {hasSummary && (
        <div className="compact-card-body">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
            {item.summary}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}

function LoopIterationCard({
  item,
}: {
  item: Extract<ChatItem, { kind: "loop" }>;
}) {
  const [expanded, setExpanded] = useState(false);
  // No iteration counter on the card. The loop primitive has its own
  // pass count (BE-side ``loop_iteration_index``), and the agent's
  // reply narrates its own task counter — those two diverge for
  // legitimate reasons (parallel presidents per pass, interrupted
  // resumes, sloppy LLM counting). Showing one number invites the
  // user to compare; the badge is now just a marker that "this is a
  // loop pass", and the agent's own text owns the iteration narrative.
  return (
    <div className="loop-iteration">
      <div className="loop-iteration-head">
        <span className="loop-iteration-badge" aria-label="Loop iteration">
          <span className="loop-iteration-arrow" aria-hidden="true">↻</span>
          <span>Loop</span>
        </span>
        <button
          type="button"
          className="loop-iteration-toggle"
          title={expanded ? "Hide the full wrapped prompt" : "Show what the model actually received"}
          onClick={() => setExpanded((v) => !v)}
        >
          <ChevronIcon size={9} down={expanded} />
          {expanded ? "hide prompt" : "show prompt"}
        </button>
      </div>
      <div className="loop-iteration-body">
        <span className="loop-iteration-slash">/loop</span> {item.body}
      </div>
      {expanded && <pre className="loop-iteration-raw">{item.raw}</pre>}
    </div>
  );
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <div
        className="thinking-toggle"
        style={{ display: "flex", alignItems: "center", gap: 5 }}
        onClick={() => setOpen(!open)}
      >
        <ChevronIcon size={9} down={open} /> thinking…
      </div>
      {open && <div className="msg-thinking">{text}</div>}
    </div>
  );
}

function ShellBlock({ item }: { item: Extract<ChatItem, { kind: "shell" }> }) {
  return (
    <div className="shell-output">
      <div className="prompt-line">$ {item.command}</div>
      {item.output ? item.output : item.exitCode === null ? "(running…)" : ""}
      {item.exitCode !== null && item.exitCode !== 0 && (
        <div style={{ color: "var(--danger)" }}>(exit {item.exitCode})</div>
      )}
    </div>
  );
}

export function ChatItemView({
  item,
  onEditUser,
  onDeleteUser,
  onStopTeam,
  onStopAgent,
  onRetryAgent,
}: {
  item: ChatItem;
  /** Callback when the user submits an edit on a previous message.
   *  The handler truncates session history from this item forward and
   *  re-sends the new text as a fresh user turn. */
  onEditUser?: (item: Extract<ChatItem, { kind: "user" }>, newText: string) => void;
  /** Callback when the user clicks delete on one of their messages.
   *  The handler truncates session history from this item forward. */
  onDeleteUser?: (item: Extract<ChatItem, { kind: "user" }>) => void;
  /** Cancel the whole top-level run (kills the team + all sub-agents). */
  onStopTeam?: () => void;
  /** Cancel a specific sub-agent by run_id (siblings keep going). */
  onStopAgent?: (runId: string) => void;
  /** Retry a failed / stopped sub-agent with a tweaked prompt.
   *  Implementation: usually sends a follow-up user message asking
   *  the main agent to respawn the specialist with the new task. */
  onRetryAgent?: (agentName: string, newTask: string) => void;
}) {
  switch (item.kind) {
    case "attachments":
      // Legacy item shape — files are now rendered as inline pills
      // inside the user bubble. Skip rendering anything.
      return null;
    case "user":
      return (
        <UserMessage
          item={item}
          onEdit={onEditUser}
          onDelete={onDeleteUser}
        />
      );
    case "assistant":
      return (
        <div className="msg-assistant">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
          >
            {normalizeAssistantMarkdown(item.text)}
          </ReactMarkdown>
        </div>
      );
    case "thinking":
      return <ThinkingBlock text={item.text} />;
    case "tool":
      return <ToolCard item={item} />;
    case "agent":
      return <div className="agent-dispatch">{item.text}</div>;
    case "orchestrate":
      return (
        <OrchestrateLog
          item={item}
          onStopTeam={onStopTeam}
          onStopAgent={onStopAgent}
          onRetryAgent={onRetryAgent}
        />
      );
    case "loop":
      return <LoopIterationCard item={item} />;
    case "compact":
      return <CompactCard item={item} />;
    case "stats": {
      const billed =
        `Billed by the model: ${item.outputTokens} output total, ` +
        `${item.reasoningTokens} of which was reasoning. ` +
        `Visible "think" and "out" estimate what you can see on screen.`;
      const inCtx = item.corrected
        ? "in: real session context (count_context_tokens)"
        : "in: still being corrected — RPC in flight";
      return (
        <div className="agent-dispatch" title={`${inCtx}\n${billed}`}>
          {formatStats(item)}
        </div>
      );
    }
    case "info":
      return <div className="msg-info">{item.text}</div>;
    case "error":
      return <div className="msg-error">{item.text}</div>;
    case "shell":
      return <ShellBlock item={item} />;
  }
}
