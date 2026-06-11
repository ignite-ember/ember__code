import { useCallback, useEffect, useState } from "react";
import type { EmberClient } from "../../protocol/client";
import { Drawer } from "./Drawer";

interface CodeIndexStatus {
  local_sha: string;
  head_indexed: boolean;
  sync_in_progress: boolean;
  sync_progress_pct: number | null;
  sync_step: string;
  sync_reason: string;
  sync_error: string;
  install_state: string;
  repository_id: string;
  install_url: string;
}

export function CodeIndexPanel({
  client,
  onClose,
}: {
  client: EmberClient;
  onClose: () => void;
}) {
  const [status, setStatus] = useState<CodeIndexStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await client.rpc<CodeIndexStatus>("codeindex_status"));
    } catch (e) {
      console.error(e);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 2_000);
    return () => clearInterval(t);
  }, [refresh]);

  const act = async (verb: string) => {
    setBusy(verb);
    try {
      await client.rpc(`codeindex_${verb}`, verb === "sync" || verb === "resync" ? { sha: null } : {});
    } catch (e) {
      console.error(e);
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  const indexedLabel = !status
    ? "…"
    : status.sync_error
      ? `sync error: ${status.sync_error}`
      : status.sync_in_progress
        ? `syncing${status.sync_progress_pct != null ? ` ${status.sync_progress_pct}%` : "…"}${status.sync_step ? ` · ${status.sync_step}` : ""}`
        : status.head_indexed
          ? "indexed"
          : status.sync_reason
            ? `not indexed · ${status.sync_reason}`
            : "not indexed";

  return (
    <Drawer title="CodeIndex" onClose={onClose}>
      {status && (
        <dl className="kv">
          <dt>HEAD</dt>
          <dd>{(status.local_sha || "—").slice(0, 12)}</dd>
          <dt>State</dt>
          <dd>{indexedLabel}</dd>
          <dt>Install</dt>
          <dd>{status.install_state}</dd>
          {status.repository_id && (
            <>
              <dt>Repo</dt>
              <dd>{status.repository_id}</dd>
            </>
          )}
        </dl>
      )}
      <div className="dialog-actions" style={{ marginTop: 16 }}>
        <button className="btn btn-sm" disabled={!!busy} onClick={() => act("sync")}>
          {busy === "sync" ? "…" : "Sync"}
        </button>
        <button className="btn btn-sm" disabled={!!busy} onClick={() => act("resync")}>
          {busy === "resync" ? "…" : "Resync"}
        </button>
        <button className="btn btn-sm" disabled={!!busy} onClick={() => act("clean")}>
          {busy === "clean" ? "…" : "Clean"}
        </button>
        {status?.install_state === "needs_install" && status.install_url && (
          <a className="btn btn-sm btn-primary" href={status.install_url} target="_blank" rel="noreferrer">
            Install GitHub App
          </a>
        )}
      </div>
    </Drawer>
  );
}
