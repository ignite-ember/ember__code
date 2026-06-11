import { useCallback, useEffect, useState } from "react";
import type { EmberClient } from "../../protocol/client";
import { Drawer } from "./Drawer";

interface McpServer {
  name: string;
  connected: boolean;
  tools?: number;
  error?: string;
}

export function McpPanel({ client, onClose }: { client: EmberClient; onClose: () => void }) {
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      await client.rpc("ensure_mcp");
      const details = await client.rpc<Record<string, unknown>[]>("get_mcp_server_details");
      setServers(
        (details || []).map((d) => ({
          name: String(d.name ?? "?"),
          connected: Boolean(d.connected),
          tools: Number(d.tools ?? d.tool_count ?? 0),
          error: d.error ? String(d.error) : undefined,
        })),
      );
    } catch (e) {
      setServers([]);
      console.error(e);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (s: McpServer) => {
    setBusy(s.name);
    try {
      await client.mcpToggle(s.name, !s.connected);
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  return (
    <Drawer title="MCP Servers" onClose={onClose}>
      {servers === null && <div className="msg-info">Loading…</div>}
      {servers?.length === 0 && <div className="msg-info">No MCP servers configured.</div>}
      {servers?.map((s) => (
        <div className="row" key={s.name}>
          <div>
            <div className="name">
              <span className={`tool-status ${s.connected ? "done" : "error"}`} /> {s.name}
            </div>
            <div className="meta">
              {s.connected ? `connected · ${s.tools} tools` : s.error || "disconnected"}
            </div>
          </div>
          <button className="btn btn-sm" disabled={busy === s.name} onClick={() => toggle(s)}>
            {busy === s.name ? "…" : s.connected ? "Disconnect" : "Connect"}
          </button>
        </div>
      ))}
    </Drawer>
  );
}
