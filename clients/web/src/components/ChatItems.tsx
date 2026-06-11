import { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import "highlight.js/styles/github-dark-dimmed.css";
import type { ChatItem } from "../chat/model";
import type { DiffRow } from "../protocol/messages";

function DiffTable({ rows }: { rows: DiffRow[] }) {
  return (
    <table className="diff-table">
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={r.kind === "add" ? "add" : r.kind === "del" ? "del" : ""}>
            <td className="lineno">{r.left_no}</td>
            <td className="code">{r.left}</td>
            <td className="lineno">{r.right_no}</td>
            <td className="code">{r.right}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ToolCard({ item }: { item: Extract<ChatItem, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const expandable = Boolean(item.result || item.diffRows?.length);
  return (
    <div className="tool-card">
      <div className="tool-card-header" onClick={() => expandable && setOpen(!open)}>
        <span className={`tool-chevron ${open ? "open" : ""}`}>{expandable ? "▶" : ""}</span>
        <span className={`tool-status ${item.status}`} />
        <span className="tool-name">{item.name}</span>
        <span className="tool-args">{item.args}</span>
      </div>
      {open && item.diffRows?.length ? (
        <div className="tool-card-body">
          <DiffTable rows={item.diffRows} />
        </div>
      ) : open && item.result ? (
        <div className="tool-card-body">{item.result}</div>
      ) : null}
    </div>
  );
}

function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <div className="thinking-toggle" onClick={() => setOpen(!open)}>
        {open ? "▾" : "▸"} thinking…
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

export function ChatItemView({ item }: { item: ChatItem }) {
  switch (item.kind) {
    case "user":
      return <div className="msg-user">{item.text}</div>;
    case "assistant":
      return (
        <div className="msg-assistant">
          <ReactMarkdown rehypePlugins={[rehypeHighlight]}>{item.text}</ReactMarkdown>
        </div>
      );
    case "thinking":
      return <ThinkingBlock text={item.text} />;
    case "tool":
      return <ToolCard item={item} />;
    case "agent":
      return <div className="agent-dispatch">{item.text}</div>;
    case "info":
      return <div className="msg-info">{item.text}</div>;
    case "error":
      return <div className="msg-error">{item.text}</div>;
    case "shell":
      return <ShellBlock item={item} />;
  }
}
