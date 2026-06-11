import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyEvent,
  assistantItem,
  errorItem,
  infoItem,
  shellItem,
  userItem,
  type ChatItem,
} from "./chat/model";
import { ChatItemView } from "./components/ChatItems";
import { Composer, BUILTIN_COMMANDS, type SlashCommand } from "./components/Composer";
import { HitlDialog, type HitlDecision } from "./components/HitlDialog";
import { Sidebar, type SessionEntry } from "./components/Sidebar";
import { CodeIndexPanel } from "./components/panels/CodeIndexPanel";
import { InfoPanel } from "./components/panels/InfoPanel";
import { LoginPanel } from "./components/panels/LoginPanel";
import { LoopPanel } from "./components/panels/LoopPanel";
import { McpPanel } from "./components/panels/McpPanel";
import { SchedulePanel } from "./components/panels/SchedulePanel";
import { EmberClient, type ConnectionState } from "./protocol/client";
import type { HITLRequest, ServerMessage, StatusUpdate } from "./protocol/messages";

type PanelState =
  | { kind: "none" }
  | { kind: "mcp" }
  | { kind: "codeindex" }
  | { kind: "loop" }
  | { kind: "schedule" }
  | { kind: "login" }
  | { kind: "info"; title: string; markdown: string };

interface ModelRegistry {
  default: string;
  registry: Record<string, Record<string, unknown>>;
}

export default function App() {
  const client = useMemo(() => new EmberClient(), []);
  const [conn, setConn] = useState<ConnectionState>("connecting");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [processing, setProcessing] = useState(false);
  const [status, setStatus] = useState<StatusUpdate | null>(null);
  const [hitl, setHitl] = useState<HITLRequest[] | null>(null);
  const [panel, setPanel] = useState<PanelState>({ kind: "none" });
  const [sidebarOpen, setSidebarOpen] = useState(window.innerWidth > 700);
  const [sessions, setSessions] = useState<SessionEntry[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [skills, setSkills] = useState<SlashCommand[]>([]);
  const [modelMenu, setModelMenu] = useState<
    { name: string; current: boolean }[] | null
  >(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const processingRef = useRef(false);

  const append = useCallback(
    (item: ChatItem) => setItems((prev) => [...prev, item]),
    [],
  );

  const setProc = useCallback((v: boolean) => {
    processingRef.current = v;
    setProcessing(v);
  }, []);

  // ── Streamed event handler (run + HITL-resume streams) ───────────
  const onStreamEvent = useCallback(
    (m: ServerMessage) => {
      if (m.type === "streaming_done") {
        // Same contract as the TUI: unblock input when content ends,
        // even though the BE tail (memory, compression) still drains.
        setProc(false);
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
        if (text) {
          setItems((prev) => [
            ...prev,
            m.kind === "error" ? errorItem(text) : assistantItem(text),
          ]);
        }
        return;
      }
      setItems((prev) => applyEvent(prev, m));
    },
    [setProc],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const s = await client.rpc<StatusUpdate>("get_status");
      if (s) setStatus(s);
    } catch {
      /* disconnected */
    }
  }, [client]);

  const refreshSessions = useCallback(async () => {
    try {
      const list = await client.rpc<Record<string, unknown>[]>("list_sessions");
      setSessions(
        (list || []).map((s) => ({
          session_id: String(s.session_id ?? s.id ?? ""),
          name: String(s.name ?? s.session_id ?? "?"),
          detail: String(s.created_at ?? ""),
        })),
      );
    } catch {
      /* older BE or empty */
    }
  }, [client]);

  // ── Wiring ────────────────────────────────────────────────────────
  useEffect(() => {
    const offState = client.onStateChange((s) => {
      setConn(s);
      if (s === "connected") {
        void (async () => {
          try {
            setSessionId(await client.rpc<string>("get_session_id"));
          } catch {
            /* ignore */
          }
          void refreshStatus();
          void refreshSessions();
          try {
            const defs = await client.rpc<{ name: string; description: string }[]>(
              "get_skill_definitions",
            );
            setSkills(
              (defs || []).map((d) => ({
                name: `/${d.name}`,
                description: d.description || "skill",
              })),
            );
          } catch {
            /* skills optional */
          }
        })();
      }
    });
    const offEvent = client.onEvent((m) => {
      if (m.type === "run_paused") setHitl(m.requirements);
      else if (m.type === "status_update") setStatus(m);
      else if (m.type === "push_notification") {
        if (m.channel === "background_process_done") {
          const p = m.payload as { cmd?: string; exit_code?: number };
          append(infoItem(`Background process finished (exit ${p.exit_code}): ${p.cmd}`));
        } else if (m.channel === "scheduler_started") {
          append(infoItem(`Scheduled task started: ${m.payload.description ?? ""}`));
        } else if (m.channel === "scheduler_completed") {
          append(infoItem(`Scheduled task completed: ${m.payload.description ?? ""}`));
        } else if (m.channel === "orchestrate_progress") {
          // Rendered inside tool cards by the TUI; keep as dim info.
          append({ kind: "agent", id: Date.now(), text: String(m.payload.line ?? "") });
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  // Status poll — mirrors the TUI status-bar cadence.
  useEffect(() => {
    if (conn !== "connected") return;
    const t = setInterval(refreshStatus, 5_000);
    return () => clearInterval(t);
  }, [conn, refreshStatus]);

  // Esc cancels the in-flight run (TUI parity).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && processingRef.current && !hitl) {
        client.cancel();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [client, hitl]);

  // Autoscroll on new content.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [items, processing]);

  // ── Loop continuation (TUI parity: refire after each run) ────────
  const continueLoopIfPending = useCallback(async () => {
    try {
      const next = await client.rpc<{ prompt?: string } | null>(
        "pop_pending_loop_iteration",
      );
      if (next?.prompt) {
        append(infoItem(`↻ loop: ${next.prompt}`));
        await runUserMessage(next.prompt);
      }
    } catch {
      /* no loop pending */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  const runUserMessage = useCallback(
    async (text: string) => {
      setProc(true);
      try {
        await client.runMessage(text, onStreamEvent);
      } catch (e) {
        append(errorItem(String(e)));
      } finally {
        setProc(false);
        void continueLoopIfPending();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, onStreamEvent],
  );

  // ── Slash command routing ─────────────────────────────────────────
  const runCommand = useCallback(
    async (text: string) => {
      append(userItem(text));
      try {
        const result = await client.handleCommand(text);
        if (result.type !== "command_result") {
          onStreamEvent(result);
          return;
        }
        const content = result.display_content || result.content;
        switch (result.action) {
          case "clear":
            setItems([]);
            try {
              setSessionId(await client.rpc<string>("get_session_id"));
            } catch {
              /* ignore */
            }
            append(infoItem("New conversation started."));
            void refreshSessions();
            return;
          case "sessions":
            setSidebarOpen(true);
            void refreshSessions();
            return;
          case "model": {
            const reg = await client.rpc<ModelRegistry>("get_model_registry");
            setModelMenu(
              Object.keys(reg.registry)
                .sort()
                .map((name) => ({ name, current: name === reg.default })),
            );
            return;
          }
          case "model_switched":
            if (content) append(infoItem(content));
            void refreshStatus();
            return;
          case "login":
            setPanel({ kind: "login" });
            return;
          case "mcp":
            setPanel({ kind: "mcp" });
            return;
          case "codeindex":
            setPanel({ kind: "codeindex" });
            return;
          case "loop":
            if (content) append(assistantItem(content));
            setPanel({ kind: "loop" });
            return;
          case "schedule":
            if (content) append(assistantItem(content));
            setPanel({ kind: "schedule" });
            return;
          case "agents":
          case "skills":
          case "plugins":
          case "knowledge":
          case "hooks":
            setPanel({
              kind: "info",
              title: result.action[0].toUpperCase() + result.action.slice(1),
              markdown: content,
            });
            return;
          case "help": {
            const lines = [...BUILTIN_COMMANDS, ...skills].map(
              (c) => `- \`${c.name}\` — ${c.description}`,
            );
            setPanel({
              kind: "info",
              title: "Help",
              markdown: `### Commands\n\n${lines.join("\n")}`,
            });
            return;
          }
          case "run_prompt":
            // Skills expand to a prompt that runs as a user message.
            if (content) await runUserMessage(content);
            return;
          case "compact":
            append(infoItem(content || "Context compacted."));
            return;
          case "quit":
            append(infoItem("Use the window/tab close button to quit."));
            return;
          default:
            if (content) {
              onStreamEvent(result);
            }
        }
      } catch (e) {
        append(errorItem(String(e)));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, onStreamEvent, skills],
  );

  // ── Submit (message / command / shell) ────────────────────────────
  const submit = useCallback(
    async (text: string) => {
      if (text.startsWith("/")) {
        await runCommand(text);
        return;
      }
      if (text.startsWith("$")) {
        const command = text.slice(1).trim();
        const item = shellItem(command);
        append(item);
        try {
          const res = await client.runShell(command);
          setItems((prev) =>
            prev.map((it) =>
              it.id === item.id && it.kind === "shell"
                ? { ...it, output: res.output, exitCode: res.exit_code }
                : it,
            ),
          );
        } catch (e) {
          append(errorItem(String(e)));
        }
        return;
      }
      append(userItem(text));
      if (processingRef.current) {
        client.queueMessage(text);
        append(infoItem("Queued — will run after the current turn."));
        return;
      }
      await runUserMessage(text);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, runCommand, runUserMessage],
  );

  const resolveHitl = useCallback(
    async (decisions: HitlDecision[]) => {
      setHitl(null);
      setProc(true);
      try {
        await client.resolveHitlBatch(decisions, onStreamEvent);
      } catch (e) {
        append(errorItem(String(e)));
      } finally {
        setProc(false);
        void continueLoopIfPending();
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client, onStreamEvent],
  );

  const pickSession = useCallback(
    async (id: string) => {
      try {
        await client.rpc("switch_session", { session_id: id });
        setSessionId(id);
        setItems([]);
        // Load persisted history for the resumed session (TUI parity).
        try {
          const history = await client.rpc<Record<string, unknown>[]>(
            "get_chat_history",
            { session_id: id },
          );
          const loaded: ChatItem[] = [];
          for (const turn of history || []) {
            const role = String(turn.role ?? "");
            const content = String(turn.content ?? "");
            if (!content) continue;
            if (role === "user") loaded.push(userItem(content));
            else if (role === "assistant") loaded.push(assistantItem(content));
          }
          setItems(loaded);
        } catch {
          /* no history RPC result — start empty */
        }
        append(infoItem(`Resumed session ${id}.`));
      } catch (e) {
        append(errorItem(String(e)));
      }
      if (window.innerWidth <= 700) setSidebarOpen(false);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client],
  );

  const pickModel = useCallback(
    async (name: string) => {
      setModelMenu(null);
      try {
        const res = await client.switchModel(name);
        if (res.type === "info") append(infoItem(res.text));
        void refreshStatus();
      } catch (e) {
        append(errorItem(String(e)));
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [client],
  );

  // ── Render ────────────────────────────────────────────────────────
  const ctxPct = status
    ? Math.round((status.context_tokens / Math.max(status.max_context, 1)) * 100)
    : 0;

  return (
    <div className="shell">
      <Sidebar
        open={sidebarOpen}
        sessions={sessions}
        currentId={sessionId}
        onNewChat={() => void runCommand("/clear")}
        onPick={(id) => void pickSession(id)}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="main">
        <header className="app-header">
          <button
            className="icon-btn"
            title="Toggle sessions"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            ☰
          </button>
          {!sidebarOpen && (
            <div className="brand">
              <div className="brand-flame" />
              <span>Ember Code</span>
            </div>
          )}
          <div className="header-spacer" />
          <button className="chip" onClick={() => void runCommand("/model")}>
            <span className="chip-label">{status?.model || "model"}</span> ▾
          </button>
          {status?.cloud_connected && (
            <span className="chip" style={{ cursor: "default" }}>
              <span className="chip-label">☁ {status.cloud_org}</span>
            </span>
          )}
          <span className="chip" style={{ cursor: "default" }}>
            <span className={`dot ${conn}`} />
            <span className="chip-label">{conn}</span>
          </span>
          {modelMenu && (
            <>
              <div
                style={{ position: "fixed", inset: 0, zIndex: 39 }}
                onClick={() => setModelMenu(null)}
              />
              <div className="dropdown">
                {modelMenu.map((m) => (
                  <div
                    key={m.name}
                    className={`popup-item ${m.current ? "active" : ""}`}
                    onClick={() => void pickModel(m.name)}
                  >
                    <span className="cmd">{m.name}</span>
                    {m.current && <span className="desc">current</span>}
                  </div>
                ))}
              </div>
            </>
          )}
        </header>

        <div className="conversation" ref={scrollRef}>
          <div className="col">
            {items.length === 0 && (
              <div className="welcome">
                <div
                  className="brand-flame"
                  style={{ width: 52, height: 52, margin: "0 auto", borderRadius: 14 }}
                />
                <h1>Ember Code</h1>
                <p>Your AI coding agent, in this project.</p>
                <div className="welcome-hints">
                  <button className="chip" onClick={() => void runCommand("/help")}>
                    /help
                  </button>
                  <button className="chip" onClick={() => void runCommand("/model")}>
                    /model
                  </button>
                  <button className="chip" onClick={() => void runCommand("/codeindex")}>
                    /codeindex
                  </button>
                  <button className="chip" onClick={() => void runCommand("/agents")}>
                    /agents
                  </button>
                </div>
              </div>
            )}
            {items.map((item) => (
              <ChatItemView key={item.id} item={item} />
            ))}
            {processing && (
              <div className="msg-info" style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="dot connecting" />
                Thinking… <span style={{ color: "var(--fg-faint)" }}>Esc to cancel</span>
              </div>
            )}
          </div>
        </div>

        <Composer
          client={client}
          connected={conn === "connected"}
          processing={processing}
          skills={skills}
          onSubmit={(t) => void submit(t)}
          onStop={() => client.cancel()}
        />
        <div className="statusline" style={{ marginTop: 0, paddingBottom: 8 }}>
          {status && (
            <>
              <span>{status.model}</span>
              <span>session {sessionId || "—"}</span>
              {status.cloud_connected && <span>☁ {status.cloud_org}</span>}
              <span>ctx {ctxPct}%</span>
            </>
          )}
        </div>
      </div>

      {hitl && <HitlDialog requirements={hitl} onResolve={(d) => void resolveHitl(d)} />}
      {panel.kind === "mcp" && (
        <McpPanel client={client} onClose={() => setPanel({ kind: "none" })} />
      )}
      {panel.kind === "codeindex" && (
        <CodeIndexPanel client={client} onClose={() => setPanel({ kind: "none" })} />
      )}
      {panel.kind === "loop" && (
        <LoopPanel client={client} onClose={() => setPanel({ kind: "none" })} />
      )}
      {panel.kind === "schedule" && (
        <SchedulePanel client={client} onClose={() => setPanel({ kind: "none" })} />
      )}
      {panel.kind === "info" && (
        <InfoPanel
          title={panel.title}
          markdown={panel.markdown}
          onClose={() => setPanel({ kind: "none" })}
        />
      )}
      {panel.kind === "login" && (
        <LoginPanel
          client={client}
          onDone={(ok, detail) => {
            setPanel({ kind: "none" });
            append(ok ? infoItem(`Logged in as ${detail}`) : errorItem(`Login failed: ${detail}`));
            void refreshStatus();
          }}
        />
      )}
    </div>
  );
}
