import { useCallback, useEffect, useState } from "react";
import type { EmberClient } from "../../protocol/client";
import { Drawer } from "./Drawer";

interface ScheduledTask {
  id?: string;
  task_id?: string;
  description?: string;
  schedule?: string;
  status?: string;
  next_run?: string;
}

export function SchedulePanel({
  client,
  onClose,
}: {
  client: EmberClient;
  onClose: () => void;
}) {
  const [tasks, setTasks] = useState<ScheduledTask[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      setTasks(await client.rpc<ScheduledTask[]>("get_scheduled_tasks", { include_done: false }));
    } catch (e) {
      console.error(e);
      setTasks([]);
    }
  }, [client]);

  useEffect(() => {
    void refresh();
    const t = setInterval(refresh, 5_000);
    return () => clearInterval(t);
  }, [refresh]);

  const cancel = async (t: ScheduledTask) => {
    const id = t.task_id || t.id;
    if (!id) return;
    await client.rpc("cancel_scheduled_task", { task_id: id });
    void refresh();
  };

  return (
    <Drawer title="Scheduled tasks" onClose={onClose}>
      {tasks === null && <div className="msg-info">Loading…</div>}
      {tasks?.length === 0 && (
        <div className="msg-info">
          Nothing scheduled. Use <code>/schedule &lt;description&gt;</code>.
        </div>
      )}
      {tasks?.map((t, i) => (
        <div className="row" key={t.task_id || t.id || i}>
          <div>
            <div className="name">{t.description || "(no description)"}</div>
            <div className="meta">
              {[t.schedule, t.status, t.next_run && `next: ${t.next_run}`]
                .filter(Boolean)
                .join(" · ")}
            </div>
          </div>
          <button className="btn btn-sm btn-danger" onClick={() => cancel(t)}>
            Cancel
          </button>
        </div>
      ))}
    </Drawer>
  );
}
