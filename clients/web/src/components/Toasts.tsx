/**
 * Toasts — top-right notification stack.
 *
 * Scheduled tasks (and other project-level async events) shouldn't
 * inject into whichever chat the user happens to be in — that buries
 * the result in an unrelated conversation. They land here instead,
 * outside the chat scroll, persist across conversation switches, and
 * auto-dismiss after a few seconds.
 *
 * Stays pure-state-via-callback: ``App`` owns the toast list and the
 * click action; this component only renders.
 */

import { useEffect, useState } from "react";

export interface Toast {
  id: number;
  title: string;
  body?: string;
  /** Optional handler when the user clicks the toast body. */
  onClick?: () => void;
  /** Auto-dismiss after this many ms. Defaults to 8000. */
  ttlMs?: number;
}

const DEFAULT_TTL = 8000;

export function Toasts({
  items,
  onDismiss,
}: {
  items: Toast[];
  onDismiss: (id: number) => void;
}) {
  if (items.length === 0) return null;
  return (
    <div className="toasts" role="region" aria-label="Notifications">
      {items.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const [closing, setClosing] = useState(false);
  useEffect(() => {
    const ttl = toast.ttlMs ?? DEFAULT_TTL;
    const t = window.setTimeout(() => {
      setClosing(true);
      // Wait for the exit animation, then drop from the list.
      window.setTimeout(onDismiss, 200);
    }, ttl);
    return () => window.clearTimeout(t);
  }, [toast.ttlMs, onDismiss]);
  return (
    <div className={`toast${closing ? " is-closing" : ""}`}>
      <button
        type="button"
        className="toast-body-btn"
        onClick={() => {
          toast.onClick?.();
          setClosing(true);
          window.setTimeout(onDismiss, 150);
        }}
      >
        <div className="toast-title">{toast.title}</div>
        {toast.body && <div className="toast-body">{toast.body}</div>}
      </button>
      <button
        type="button"
        className="toast-close"
        aria-label="Dismiss"
        onClick={(e) => {
          e.stopPropagation();
          setClosing(true);
          window.setTimeout(onDismiss, 150);
        }}
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      </button>
    </div>
  );
}
