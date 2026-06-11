/**
 * Conversation item model + the reducer applying streamed protocol
 * events. Mirrors the TUI's rendering rules in run_controller._render:
 * content deltas append to the open assistant block, thinking deltas
 * go to a dimmed block, tool events create/update cards.
 */

import type { DiffRow, ServerMessage } from "../protocol/messages";

export type ChatItem =
  | { kind: "user"; id: number; text: string }
  | { kind: "assistant"; id: number; text: string }
  | { kind: "thinking"; id: number; text: string }
  | {
      kind: "tool";
      id: number;
      runId: string;
      name: string;
      args: string;
      status: "running" | "done" | "error";
      result: string;
      isError: boolean;
      diffRows: DiffRow[] | null;
    }
  | { kind: "agent"; id: number; text: string }
  | { kind: "info"; id: number; text: string }
  | { kind: "error"; id: number; text: string }
  | { kind: "shell"; id: number; command: string; output: string; exitCode: number | null };

let itemId = 0;
const nid = () => ++itemId;

export function shellItem(command: string): ChatItem {
  return { kind: "shell", id: nid(), command, output: "", exitCode: null };
}

export function userItem(text: string): ChatItem {
  return { kind: "user", id: nid(), text };
}

export function infoItem(text: string): ChatItem {
  return { kind: "info", id: nid(), text };
}

export function errorItem(text: string): ChatItem {
  return { kind: "error", id: nid(), text };
}

export function assistantItem(text: string): ChatItem {
  return { kind: "assistant", id: nid(), text };
}

/**
 * Apply one streamed event to the item list, returning a new list.
 * Pure so React state updates stay predictable.
 */
export function applyEvent(items: ChatItem[], msg: ServerMessage): ChatItem[] {
  switch (msg.type) {
    case "content_delta": {
      if (!msg.text) return items;
      const wantKind = msg.is_thinking ? "thinking" : "assistant";
      const last = items[items.length - 1];
      if (last && last.kind === wantKind) {
        const updated = { ...last, text: last.text + msg.text };
        return [...items.slice(0, -1), updated];
      }
      return [...items, { kind: wantKind, id: nid(), text: msg.text } as ChatItem];
    }

    case "tool_started":
      return [
        ...items,
        {
          kind: "tool",
          id: nid(),
          runId: msg.run_id,
          name: msg.friendly_name || msg.tool_name,
          args: msg.args_summary,
          status: "running",
          result: "",
          isError: false,
          diffRows: null,
        },
      ];

    case "tool_completed": {
      // Update the most recent running tool card for this run.
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (it.kind === "tool" && it.status === "running") {
          const updated: ChatItem = {
            ...it,
            status: msg.is_error ? "error" : "done",
            result: msg.full_result || msg.summary,
            isError: msg.is_error,
            diffRows: msg.diff_rows ?? null,
          };
          return [...items.slice(0, i), updated, ...items.slice(i + 1)];
        }
      }
      return items;
    }

    case "tool_error": {
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (it.kind === "tool" && it.status === "running") {
          const updated: ChatItem = { ...it, status: "error", result: msg.error, isError: true };
          return [...items.slice(0, i), updated, ...items.slice(i + 1)];
        }
      }
      return [...items, errorItem(msg.error)];
    }

    case "run_started":
      // Sub-agent dispatch marker (the main run has no parent).
      if (msg.parent_run_id) {
        return [...items, { kind: "agent", id: nid(), text: `→ ${msg.agent_name}` }];
      }
      return items;

    case "run_error":
      return [...items, errorItem(msg.error)];

    case "info":
      return [...items, infoItem(msg.text)];

    case "error":
      return [...items, errorItem(msg.text)];

    default:
      return items;
  }
}
