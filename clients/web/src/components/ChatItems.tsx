import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatItem } from "../chat/model";

function ToolCard({ item }: { item: Extract<ChatItem, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="tool-card">
      <div className="tool-card-header" onClick={() => setOpen(!open)}>
        <span className={`tool-status ${item.status}`} />
        <span className="tool-name">{item.name}</span>
        <span className="tool-args">{item.args}</span>
      </div>
      {open && item.result && <div className="tool-card-body">{item.result}</div>}
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
          <ReactMarkdown>{item.text}</ReactMarkdown>
        </div>
      );
    case "thinking":
      return <div className="msg-thinking">{item.text}</div>;
    case "tool":
      return <ToolCard item={item} />;
    case "agent":
      return <div className="agent-dispatch">{item.text}</div>;
    case "info":
      return <div className="msg-info">{item.text}</div>;
    case "error":
      return <div className="msg-error">{item.text}</div>;
  }
}
