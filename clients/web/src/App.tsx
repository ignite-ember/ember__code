import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyEvent,
  errorItem,
  infoItem,
  userItem,
  type ChatItem,
} from "./chat/model";
import { ChatItemView } from "./components/ChatItems";
import { HitlDialog, type HitlDecision } from "./components/HitlDialog";
import { Picker, type PickerEntry } from "./components/Pickers";
import { PromptInput } from "./components/PromptInput";
import { EmberClient, type ConnectionState } from "./protocol/client";
import type { HITLRequest, ServerMessage, StatusUpdate } from "./protocol/messages";

interface ModelRegistry {
  default: string;
  registry: Record<string, Record<string, unknown>>;
}

interface SessionEntry {
  session_id?: string;
  name?: string;
  created_at?: string;
}

export default function App() {
  const client = useMemo(() => new EmberClient(), []);
  const [conn, setConn] = useState<ConnectionState>("connecting");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [processing, setProcessing] = useState(false);
  const [status, setStatus] = useState<StatusUpdate | null>(null);
  const [hitl, setHitl] = useState<HITLRequest[] | null>(null);
  const [picker, setPicker] = useState<"model" | "sessions" | null>(null);
  const [pickerEntries, setPickerEntries] = useState<PickerEntry[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const append = useCallback((item: ChatItem) => setItems((prev) => [...prev, item]), []);

  // ── Streamed event handler (shared by run + HITL-resume streams) ──
  const onStreamEvent = useCallback((m: ServerMessage) => {
    if (m.type === "streaming_done") {
      // Same contract as the TUI: unblock input when content ends,
      // even though the BE tail (memory, compression) still drains.
      setProcessing(false);
      return;
    }
    if (m.type === "run_paused") {
      setHitl(m.requirements);
      return;
    }
    if (m.type === "status_update") {
      setStatus(m);
      return;
    }
    if (m.type === "command_result") {
      const text = m.display_content || m.content;
      setItems((prev) => [
        ...prev,
        m.kind === "error" ? errorItem(text) : infoItem(text),
      ]);
      return;
    }
    setItems((prev) => applyEvent(prev, m));
  }, []);

  // ── Wiring ────────────────────────────────────────────────────────
  useEffect(() => {
    const offState = client.onStateChange(setConn);
    const offEvent = client.onEvent((m) => {
      // Uncorrelated events: late HITL, BE status pushes, push
      // notifications (scheduler, background processes).
      if (m.type === "run_paused") setHitl(m.requirements);
      else if (m.type === "status_update") setStatus(m);
      else if (m.type === "push_notification") {
        if (m.channel === "background_process_done") {
          const p = m.payload as { cmd?: string; exit_code?: number };
          setItems((prev) => [
            ...prev,
            infoItem(`Background process finished (exit ${p.exit_code}): ${p.cmd}`),
          ]);
        }
      } else if (m.type === "info" || m.type === "error") {
        setItems((prev) => applyEvent(prev, m));
      }
    });
    client.connect();
    return () => {
      offState();
      offEvent();
      client.close();
    };
  }, [client, onStreamEvent]);

  // Status poll — mirrors the TUI status bar cadence.
  useEffect(() => {
    if (conn !== "connected") return;
    let alive = true;
    const tick = async () => {
      try {
        const s = await client.rpc<StatusUpdate>("get_status");
        if (alive && s) setStatus(s);
      } catch {
        /* disconnected mid-poll */
      }
    };
    tick();
    const t = setInterval(tick, 5_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [client, conn]);

  // Autoscroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items, processing]);

  // ── Actions ───────────────────────────────────────────────────────
  const submit = useCallback(
    async (text: string) => {
      if (text.startsWith("/")) {
        await runCommand(text);
        return;
      }
      append(userItem(text));
      if (processing) {
        client.queueMessage(text);
        return;
      }
      setProcessing(true);
      try {
        await client.runMessage(text, onStreamEvent);
      } catch (e) {
        append(errorItem(String(e)));
      } finally {
        setProcessing(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, processing, onStreamEvent],
  );

  const runCommand = useCallback(
    async (text: string) => {
      append(userItem(text));
      try {
        const result = await client.handleCommand(text);
        if (result.type !== "command_result") {
          onStreamEvent(result);
          return;
        }
        switch (result.action) {
          case "clear":
            setItems([]);
            append(infoItem("Conversation cleared."));
            return;
          case "model": {
            const reg = await client.rpc<ModelRegistry>("get_model_registry");
            setPickerEntries(
              Object.keys(reg.registry)
                .sort()
                .map((name) => ({
                  key: name,
                  label: name,
                  current: name === reg.default,
                })),
            );
            setPicker("model");
            return;
          }
          case "sessions": {
            const sessions = await client.rpc<SessionEntry[]>("list_sessions");
            setPickerEntries(
              (sessions || []).map((s) => ({
                key: s.session_id || "",
                label: s.name || s.session_id || "?",
                detail: s.created_at,
              })),
            );
            setPicker("sessions");
            return;
          }
          case "quit":
            append(infoItem("Use the window close button to quit."));
            return;
          case "help":
            // The TUI draws its own help panel for this action; the
            // BE sends no content. Render a compact equivalent.
            setItems((prev) => [
              ...prev,
              {
                kind: "assistant",
                id: Date.now(),
                text: [
                  "### Commands",
                  "",
                  "- `/model` — pick a model",
                  "- `/sessions` — switch session",
                  "- `/clear` — clear conversation",
                  "- `/compact` — summarize old context",
                  "- `/agents`, `/skills`, `/mcp`, `/plugins` — list resources",
                  "- `/codeindex` — semantic index status",
                ].join("\n"),
              } as ChatItem,
            ]);
            return;
          default:
            onStreamEvent(result);
        }
      } catch (e) {
        append(errorItem(String(e)));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, onStreamEvent],
  );

  const resolveHitl = useCallback(
    async (decisions: HitlDecision[]) => {
      setHitl(null);
      setProcessing(true);
      try {
        await client.resolveHitlBatch(
          decisions.map((d) => ({ ...d, action: d.action })),
          onStreamEvent,
        );
      } catch (e) {
        append(errorItem(String(e)));
      } finally {
        setProcessing(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, onStreamEvent],
  );

  const onPick = useCallback(
    async (key: string) => {
      const which = picker;
      setPicker(null);
      try {
        if (which === "model") {
          const res = await client.switchModel(key);
          if (res.type === "info") append(infoItem(res.text));
          const s = await client.rpc<StatusUpdate>("get_status");
          if (s) setStatus(s);
        } else if (which === "sessions") {
          await client.rpc("switch_session", { session_id: key });
          setItems([]);
          append(infoItem(`Switched to session ${key}.`));
        }
      } catch (e) {
        append(errorItem(String(e)));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, picker],
  );

  // ── Render ────────────────────────────────────────────────────────
  return (
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <div className="brand-flame" />
          Ember Code
        </div>
        <div className="header-spacer" />
        {status && (
          <button className="btn" onClick={() => runCommand("/model")}>
            {status.model || "model"}
          </button>
        )}
        <button className="btn" onClick={() => runCommand("/sessions")}>
          Sessions
        </button>
        <span className="conn-badge">
          <span className={`conn-dot ${conn}`} />
          {conn}
        </span>
      </header>

      <div className="conversation" ref={scrollRef}>
        {items.length === 0 && (
          <div className="welcome">
            <div
              className="brand-flame"
              style={{ width: 48, height: 48, margin: "0 auto", borderRadius: 12 }}
            />
            <h1>Ember Code</h1>
            <p>Type a message or /help for commands.</p>
          </div>
        )}
        {items.map((item) => (
          <ChatItemView key={item.id} item={item} />
        ))}
        {processing && (
          <div className="thinking-indicator">
            <span className="conn-dot" />
            Thinking…
            <button className="btn" style={{ marginLeft: 8 }} onClick={() => client.cancel()}>
              Cancel (Esc)
            </button>
          </div>
        )}
      </div>

      <div className="prompt-row">
        <div className="prompt-box">
          <PromptInput
            disabled={conn !== "connected"}
            placeholder={
              conn === "connected"
                ? "Type a message or /help  ·  Enter to send, Shift+Enter for newline"
                : "Connecting to backend…"
            }
            onSubmit={submit}
          />
        </div>
        <div className="statusbar">
          {status && (
            <>
              <span>{status.model}</span>
              {status.cloud_connected && <span>☁ {status.cloud_org}</span>}
              <span>
                ctx {Math.round((status.context_tokens / Math.max(status.max_context, 1)) * 100)}%
              </span>
            </>
          )}
        </div>
      </div>

      {hitl && <HitlDialog requirements={hitl} onResolve={resolveHitl} />}
      {picker && (
        <Picker entries={pickerEntries} onPick={onPick} onClose={() => setPicker(null)} />
      )}
    </div>
  );
}
