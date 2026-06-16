import { useState } from "react";

const fmtTokens = (n: number): string =>
  n >= 1000 ? `${(n / 1000).toFixed(n >= 10_000 ? 0 : 1)}k` : String(n);

/** Click to copy the full session id. Visible label is the short
 *  prefix the BE uses everywhere else. */
export function SessionChip({ sessionId }: { sessionId: string }) {
  const [copied, setCopied] = useState(false);

  if (!sessionId) return <span>session —</span>;

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Clipboard API blocked (insecure context, etc.); silently ignore.
    }
  };

  return (
    <button
      type="button"
      className={`session-chip${copied ? " copied" : ""}`}
      title={copied ? "Copied!" : `Copy ${sessionId}`}
      onClick={onCopy}
    >
      <span className="session-chip-label">session</span>
      <code>{sessionId}</code>
      {copied && <span className="session-chip-toast">copied</span>}
    </button>
  );
}

/** Context meter: a slim bar that fills as the conversation grows,
 *  color-graded (calm → warning → danger). The numeric readout sits
 *  next to it so the user can read both at a glance. */
export function CtxMeter({
  tokens,
  max,
  pct,
}: {
  tokens: number;
  max: number;
  pct: number;
}) {
  const safe = Math.min(100, Math.max(0, pct));
  const tone = safe >= 85 ? "danger" : safe >= 60 ? "warn" : "ok";
  return (
    <span
      className={`ctx-meter tone-${tone}`}
      title={
        max
          ? `${tokens.toLocaleString()} of ${max.toLocaleString()} tokens used`
          : `${tokens.toLocaleString()} tokens`
      }
    >
      <span className="ctx-meter-label">ctx</span>
      <span className="ctx-meter-track">
        <span className="ctx-meter-fill" style={{ width: `${safe}%` }} />
      </span>
      <span className="ctx-meter-text">
        {fmtTokens(tokens)} <span className="ctx-meter-pct">· {safe}%</span>
      </span>
    </span>
  );
}
