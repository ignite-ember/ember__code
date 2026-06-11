export interface SessionEntry {
  session_id: string;
  name: string;
  detail?: string;
}

export function Sidebar({
  open,
  sessions,
  currentId,
  onNewChat,
  onNewChatInFolder,
  onPick,
  onClose,
}: {
  open: boolean;
  sessions: SessionEntry[];
  currentId: string;
  onNewChat: () => void;
  onNewChatInFolder: () => void;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  return (
    <>
      {open && window.innerWidth <= 700 && (
        <div
          style={{ position: "fixed", inset: 0, zIndex: 55, background: "rgba(0,0,0,0.35)" }}
          onClick={onClose}
        />
      )}
      <nav className={`sidebar ${open ? "" : "closed"}`}>
        <div className="sidebar-head">
          <div className="brand-flame" />
          <strong>Ember Code</strong>
        </div>
        <div style={{ padding: "6px 12px", display: "flex", flexDirection: "column", gap: 6 }}>
          <button className="btn" style={{ width: "100%" }} onClick={onNewChat}>
            + New chat
          </button>
          <button
            className="btn btn-sm"
            style={{ width: "100%", fontWeight: 400 }}
            title="Start a session whose tools and shell run in a different directory"
            onClick={onNewChatInFolder}
          >
            + New chat in folder…
          </button>
        </div>
        <div className="sidebar-section">Sessions</div>
        <div className="sidebar-list">
          {sessions.length === 0 && (
            <div className="session-item" style={{ cursor: "default" }}>
              No past sessions
            </div>
          )}
          {sessions.map((s) => (
            <div
              key={s.session_id}
              className={`session-item ${s.session_id === currentId ? "current" : ""}`}
              title={s.detail || s.name}
              onClick={() => onPick(s.session_id)}
            >
              {s.name || s.session_id}
            </div>
          ))}
        </div>
      </nav>
    </>
  );
}
