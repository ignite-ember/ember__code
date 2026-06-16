/**
 * Reducer tests for ``applyOrchestrateEvent``.
 *
 * The function is pure and folds an event stream into an
 * ``{agents, order}`` shape. Each test feeds a small event sequence
 * and pins the resulting shape — keeps regressions visible the
 * moment they happen, no need to spin up a real broadcast.
 */

import { describe, expect, it } from "vitest";
import {
  applyOrchestrateEvent,
  isOrchestrateActive,
  PREVIEW_WINDOW,
  type OrchestrateAgent,
  type OrchestrateEvent,
} from "./model";

function play(events: OrchestrateEvent[]): {
  agents: Record<string, OrchestrateAgent>;
  order: string[];
} {
  let state: { agents: Record<string, OrchestrateAgent>; order: string[] } = {
    agents: {},
    order: [],
  };
  for (const ev of events) state = applyOrchestrateEvent(state.agents, state.order, ev);
  return state;
}

describe("applyOrchestrateEvent", () => {
  describe("agent_started", () => {
    it("registers a new agent in order with running status + zero tokens", () => {
      const { agents, order } = play([
        { type: "agent_started", agent_path: "security", agent: "security" },
      ]);
      expect(order).toEqual(["security"]);
      const a = agents.security;
      expect(a.name).toBe("security");
      expect(a.status).toBe("running");
      expect(a.tools).toEqual([]);
      expect(a.previewLines).toEqual([]);
      expect(a.inputTokens).toBe(0);
      expect(a.outputTokens).toBe(0);
      expect(a.reasoningTokens).toBe(0);
      expect(a.runId).toBe("");
      expect(a.task).toBe("");
    });

    it("captures run_id + task when supplied", () => {
      const { agents } = play([
        {
          type: "agent_started",
          agent_path: "qa",
          agent: "qa",
          run_id: "run-qa-1",
          task: "Audit auth tests",
        },
      ]);
      expect(agents.qa.runId).toBe("run-qa-1");
      expect(agents.qa.task).toBe("Audit auth tests");
    });

    it("repeated agent_started doesn't duplicate or clobber existing data", () => {
      const { agents, order } = play([
        { type: "agent_started", agent_path: "qa", agent: "qa", run_id: "run-1", task: "first" },
        { type: "content_preview", agent_path: "qa", text: "thinking…" },
        // Stray re-start (e.g. nested team re-issued the start event).
        { type: "agent_started", agent_path: "qa", agent: "qa" },
      ]);
      expect(order).toEqual(["qa"]);
      expect(agents.qa.runId).toBe("run-1"); // preserved
      expect(agents.qa.task).toBe("first"); // preserved
      expect(agents.qa.previewLines).toEqual(["thinking…"]); // preserved
    });

    it("backfills run_id / task on a later started event when first was bare", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "qa", agent: "qa" },
        { type: "agent_started", agent_path: "qa", agent: "qa", run_id: "late", task: "late" },
      ]);
      expect(agents.qa.runId).toBe("late");
      expect(agents.qa.task).toBe("late");
    });
  });

  describe("tool lifecycle", () => {
    it("appends a running tool on tool_started", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "sec", agent: "sec" },
        {
          type: "tool_started",
          agent_path: "sec",
          tool: "rg",
          tool_call_id: "t1",
          args: "{pattern: 'TODO'}",
        },
      ]);
      expect(agents.sec.tools).toHaveLength(1);
      expect(agents.sec.tools[0]).toMatchObject({
        tool: "rg",
        args: "{pattern: 'TODO'}",
        status: "running",
        toolCallId: "t1",
        result: "",
      });
    });

    it("matches completion by tool_call_id even with parallel same-name tools", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "sec", agent: "sec" },
        { type: "tool_started", agent_path: "sec", tool: "rg", tool_call_id: "a", args: "first" },
        { type: "tool_started", agent_path: "sec", tool: "rg", tool_call_id: "b", args: "second" },
        // Complete the SECOND one first — id-based match must pick it.
        {
          type: "tool_completed",
          agent_path: "sec",
          tool: "rg",
          tool_call_id: "b",
          result: "B result",
          is_error: false,
        },
      ]);
      const [first, second] = agents.sec.tools;
      expect(first.toolCallId).toBe("a");
      expect(first.status).toBe("running"); // still going
      expect(second.toolCallId).toBe("b");
      expect(second.status).toBe("done");
      expect(second.result).toBe("B result");
    });

    it("falls back to last-running-with-same-name when no tool_call_id", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "sec", agent: "sec" },
        { type: "tool_started", agent_path: "sec", tool: "rg", args: "first" },
        { type: "tool_started", agent_path: "sec", tool: "rg", args: "second" },
        {
          type: "tool_completed",
          agent_path: "sec",
          tool: "rg",
          result: "done",
          is_error: false,
        },
      ]);
      const tools = agents.sec.tools;
      // Most-recent matching one gets closed first (LIFO).
      expect(tools[0].status).toBe("running");
      expect(tools[1].status).toBe("done");
    });

    it("marks tool as error on is_error=true", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "sec", agent: "sec" },
        { type: "tool_started", agent_path: "sec", tool: "ls", tool_call_id: "x", args: "/missing" },
        {
          type: "tool_completed",
          agent_path: "sec",
          tool: "ls",
          tool_call_id: "x",
          result: "no such dir",
          is_error: true,
        },
      ]);
      expect(agents.sec.tools[0].status).toBe("error");
      expect(agents.sec.tools[0].result).toBe("no such dir");
    });
  });

  describe("content_preview rolling window", () => {
    it("single-line text replaces the window with that one line", () => {
      // Each event from the BE is the full current preview window
      // (joined by \n). A single-line text means the agent has only
      // produced one non-empty line so far — the FE shows just that.
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "content_preview", agent_path: "p", text: "line one" },
        { type: "content_preview", agent_path: "p", text: "line one" }, // duplicate — dedupped, no change
        { type: "content_preview", agent_path: "p", text: "line two" }, // newer snapshot, replaces
      ]);
      expect(agents.p.previewLines).toEqual(["line two"]);
    });

    it("multi-line text replaces the window with the split lines", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        {
          type: "content_preview",
          agent_path: "p",
          text: "line one\nline two\nline three",
        },
      ]);
      expect(agents.p.previewLines).toEqual(["line one", "line two", "line three"]);
    });

    it("caps at PREVIEW_WINDOW (keeps the last lines)", () => {
      const lines = Array.from({ length: PREVIEW_WINDOW + 4 }, (_, i) => `line ${i}`);
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "content_preview", agent_path: "p", text: lines.join("\n") },
      ]);
      expect(agents.p.previewLines).toHaveLength(PREVIEW_WINDOW);
      // Trailing window: last N lines kept, leading ones dropped.
      expect(agents.p.previewLines[0]).toBe(`line 4`);
      expect(agents.p.previewLines[agents.p.previewLines.length - 1]).toBe(
        `line ${PREVIEW_WINDOW + 3}`,
      );
    });

    it("empty preview text is ignored", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "content_preview", agent_path: "p", text: "   " }, // whitespace only
      ]);
      expect(agents.p.previewLines).toEqual([]);
    });

    it("identical preview is dedupped (same references back)", () => {
      let state: { agents: Record<string, OrchestrateAgent>; order: string[] } = {
        agents: {},
        order: [],
      };
      state = applyOrchestrateEvent(state.agents, state.order, {
        type: "agent_started",
        agent_path: "p",
        agent: "p",
      });
      const afterFirst = applyOrchestrateEvent(state.agents, state.order, {
        type: "content_preview",
        agent_path: "p",
        text: "alpha\nbeta",
      });
      const afterSecond = applyOrchestrateEvent(afterFirst.agents, afterFirst.order, {
        type: "content_preview",
        agent_path: "p",
        text: "alpha\nbeta",
      });
      // Same references → caller can short-circuit the React re-render.
      expect(afterSecond.agents).toBe(afterFirst.agents);
      expect(afterSecond.order).toBe(afterFirst.order);
    });
  });

  describe("status transitions", () => {
    it("agent_completed flips status + records tokens", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        {
          type: "agent_completed",
          agent_path: "p",
          is_error: false,
          input_tokens: 4200,
          output_tokens: 380,
          reasoning_tokens: 95,
        },
      ]);
      expect(agents.p.status).toBe("done");
      expect(agents.p.inputTokens).toBe(4200);
      expect(agents.p.outputTokens).toBe(380);
      expect(agents.p.reasoningTokens).toBe(95);
    });

    it("agent_completed with is_error=true flips to error", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "agent_completed", agent_path: "p", is_error: true },
      ]);
      expect(agents.p.status).toBe("error");
    });

    it("agent_paused flips status to paused", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "agent_paused", agent_path: "p", count: 1 },
      ]);
      expect(agents.p.status).toBe("paused");
    });

    it("run_error appends to preview tail + flips status", () => {
      const { agents } = play([
        { type: "agent_started", agent_path: "p", agent: "p" },
        { type: "content_preview", agent_path: "p", text: "doing stuff" },
        { type: "run_error", agent_path: "p", error: "timed out" },
      ]);
      expect(agents.p.status).toBe("error");
      const tail = agents.p.previewLines[agents.p.previewLines.length - 1];
      expect(tail).toContain("ERROR: timed out");
    });
  });

  describe("event ordering / unknown agents", () => {
    it("auto-creates agent on tool_started even without prior agent_started", () => {
      const { agents, order } = play([
        { type: "tool_started", agent_path: "ghost", tool: "rg", tool_call_id: "1", args: "x" },
      ]);
      expect(order).toEqual(["ghost"]);
      expect(agents.ghost.tools).toHaveLength(1);
    });

    it("preserves insertion order across multiple agents", () => {
      const { order } = play([
        { type: "agent_started", agent_path: "first", agent: "first" },
        { type: "agent_started", agent_path: "second", agent: "second" },
        { type: "tool_started", agent_path: "first", tool: "rg", args: "" },
        { type: "agent_started", agent_path: "third", agent: "third" },
      ]);
      expect(order).toEqual(["first", "second", "third"]);
    });
  });
});

describe("isOrchestrateActive", () => {
  it("true when any agent is running", () => {
    const { agents, order } = play([
      { type: "agent_started", agent_path: "a", agent: "a" },
      { type: "agent_started", agent_path: "b", agent: "b" },
      { type: "agent_completed", agent_path: "a", is_error: false },
    ]);
    expect(isOrchestrateActive(agents, order)).toBe(true);
  });

  it("true when any agent is paused", () => {
    const { agents, order } = play([
      { type: "agent_started", agent_path: "a", agent: "a" },
      { type: "agent_paused", agent_path: "a" },
    ]);
    expect(isOrchestrateActive(agents, order)).toBe(true);
  });

  it("false when all agents have settled", () => {
    const { agents, order } = play([
      { type: "agent_started", agent_path: "a", agent: "a" },
      { type: "agent_started", agent_path: "b", agent: "b" },
      { type: "agent_completed", agent_path: "a", is_error: false },
      { type: "agent_completed", agent_path: "b", is_error: true },
    ]);
    expect(isOrchestrateActive(agents, order)).toBe(false);
  });

  it("true for an empty card (waiting for the team to spin up)", () => {
    expect(isOrchestrateActive({}, [])).toBe(true);
  });
});

describe("token totals across agents (rendered as team sum)", () => {
  it("sums input/output across all agents", () => {
    const { agents } = play([
      { type: "agent_started", agent_path: "a", agent: "a" },
      { type: "agent_started", agent_path: "b", agent: "b" },
      {
        type: "agent_completed",
        agent_path: "a",
        is_error: false,
        input_tokens: 3000,
        output_tokens: 200,
      },
      {
        type: "agent_completed",
        agent_path: "b",
        is_error: false,
        input_tokens: 1500,
        output_tokens: 80,
      },
    ]);
    const totalIn = Object.values(agents).reduce((n, a) => n + a.inputTokens, 0);
    const totalOut = Object.values(agents).reduce((n, a) => n + a.outputTokens, 0);
    expect(totalIn).toBe(4500);
    expect(totalOut).toBe(280);
  });
});
