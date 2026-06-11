import { useCallback, useEffect, useState } from "react";
import type { EmberClient } from "../../protocol/client";
import { Drawer } from "./Drawer";

interface LoopStatus {
  active?: boolean;
  prompt?: string;
  iteration?: number;
  max_iterations?: number;
  paused?: boolean;
}

export function LoopPanel({ client, onClose }: { client: EmberClient; onClose: () => void }) {
  const [status, setStatus] = useState<LoopStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await client.rpc<LoopStatus>("loop_status"));
    } catch (e) {
      console.error(e);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 1_500);
    return () => clearInterval(t);
  }, [refresh]);

  const act = async (method: string) => {
    try {
      await client.rpc(method);
    } finally {
      void refresh();
    }
  };

  return (
    <Drawer title="Loop" onClose={onClose}>
      {!status?.active && (
        <div className="msg-info">
          No active loop. Start one with <code>/loop &lt;prompt&gt;</code>.
        </div>
      )}
      {status?.active && (
        <>
          <dl className="kv">
            <dt>Prompt</dt>
            <dd>{status.prompt}</dd>
            <dt>Iteration</dt>
            <dd>
              {status.iteration}/{status.max_iterations}
            </dd>
            <dt>State</dt>
            <dd>{status.paused ? "paused" : "running"}</dd>
          </dl>
          <div className="dialog-actions" style={{ marginTop: 16 }}>
            {status.paused ? (
              <button className="btn btn-sm" onClick={() => act("loop_resume")}>
                Resume
              </button>
            ) : (
              <button className="btn btn-sm" onClick={() => act("loop_pause")}>
                Pause
              </button>
            )}
            <button className="btn btn-sm btn-danger" onClick={() => act("cancel_pending_loop")}>
              Stop loop
            </button>
          </div>
        </>
      )}
    </Drawer>
  );
}
