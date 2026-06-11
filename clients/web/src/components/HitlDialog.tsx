import { useState } from "react";
import type { HITLRequest } from "../protocol/messages";

export interface HitlDecision {
  requirement_id: string;
  action: "confirm" | "reject";
  choice: string;
}

/**
 * Permission dialog — steps through each pending requirement and
 * collects all decisions, then submits the batch in one round-trip
 * (mirrors the TUI's HITLResponseBatch flow).
 */
export function HitlDialog({
  requirements,
  onResolve,
}: {
  requirements: HITLRequest[];
  onResolve: (decisions: HitlDecision[]) => void;
}) {
  const [index, setIndex] = useState(0);
  const [decisions, setDecisions] = useState<HitlDecision[]>([]);
  const req = requirements[index];
  if (!req) return null;

  const decide = (action: "confirm" | "reject", choice: string) => {
    const next = [...decisions, { requirement_id: req.requirement_id, action, choice }];
    if (index + 1 < requirements.length) {
      setDecisions(next);
      setIndex(index + 1);
    } else {
      onResolve(next);
    }
  };

  return (
    <div className="hitl-overlay">
      <div className="hitl-dialog">
        <div className="hitl-title">
          Allow {req.friendly_name || req.tool_name}?
          {requirements.length > 1 && (
            <span className="dim">
              {" "}
              ({index + 1}/{requirements.length})
            </span>
          )}
        </div>
        {req.agent_path && <div className="hitl-subtitle">{req.agent_path}</div>}
        {req.details && <div className="hitl-subtitle">{req.details}</div>}
        <div className="hitl-args">{JSON.stringify(req.tool_args, null, 2)}</div>
        <div className="hitl-actions">
          <button className="btn btn-primary" onClick={() => decide("confirm", "once")}>
            Allow once
          </button>
          <button className="btn" onClick={() => decide("confirm", "always")}>
            Always allow
          </button>
          <button className="btn btn-danger" onClick={() => decide("reject", "")}>
            Reject
          </button>
        </div>
      </div>
    </div>
  );
}
