import { describe, expect, it } from "vitest";
import {
  applyEvent,
  correctStatsCtx,
  formatStats,
  loopItem,
  newStreamState,
  onToolBoundary,
  parseLoopIteration,
  restoredItem,
  splitThinkTags,
  type ChatItem,
} from "./model";
import type { ServerMessage } from "../protocol/messages";

const delta = (text: string, is_thinking = false): ServerMessage =>
  ({ type: "content_delta", text, is_thinking }) as ServerMessage;

const toolStarted: ServerMessage = {
  type: "tool_started",
  tool_name: "read_file",
  friendly_name: "Read",
  args_summary: "settings.py",
  run_id: "r1",
} as ServerMessage;

const toolCompleted: ServerMessage = {
  type: "tool_completed",
  summary: "ok",
  full_result: "content",
  run_id: "r1",
  has_markup: false,
  diff_rows: null,
  is_error: false,
} as ServerMessage;

function play(events: ServerMessage[]): ChatItem[] {
  const stream = newStreamState();
  let items: ChatItem[] = [];
  for (const e of events) items = applyEvent(items, e, stream);
  return items;
}

describe("splitThinkTags", () => {
  it("routes <think> content to thinking and the rest to text", () => {
    const s = newStreamState();
    expect(splitThinkTags(s, "<think>plan</think>answer")).toEqual([
      ["plan", true],
      ["answer", false],
    ]);
    expect(s.usesThinkTags).toBe(true);
    expect(s.inThinking).toBe(false);
  });

  it("handles tags split across deltas", () => {
    const s = newStreamState();
    expect(splitThinkTags(s, "<thi")).toEqual([]);
    expect(splitThinkTags(s, "nk>deep ")).toEqual([["deep ", true]]);
    expect(splitThinkTags(s, "thought</th")).toEqual([["thought", true]]);
    expect(splitThinkTags(s, "ink>done")).toEqual([["done", false]]);
  });

  it("keeps multi-delta thinking in thinking mode", () => {
    const s = newStreamState();
    splitThinkTags(s, "<think>first ");
    expect(splitThinkTags(s, "second")).toEqual([["second", true]]);
    expect(s.inThinking).toBe(true);
  });

  it("strips cosmetic newlines after the close tag", () => {
    const s = newStreamState();
    expect(splitThinkTags(s, "<think>x</think>\n\nanswer")).toEqual([
      ["x", true],
      ["answer", false],
    ]);
  });

  it("treats a bare stray </think> as thinking-close, not literal text", () => {
    const s = newStreamState();
    expect(splitThinkTags(s, "resumed reasoning</think>answer")).toEqual([
      ["resumed reasoning", true],
      ["answer", false],
    ]);
  });

  it("pre-enters thinking after a tool boundary for think-tag models", () => {
    const s = newStreamState();
    splitThinkTags(s, "<think>a</think>b");
    onToolBoundary(s);
    expect(s.inThinking).toBe(true);
    expect(splitThinkTags(s, "post-tool reasoning</think>final")).toEqual([
      ["post-tool reasoning", true],
      ["final", false],
    ]);
  });

  it("does NOT pre-enter thinking for models without think tags", () => {
    const s = newStreamState();
    splitThinkTags(s, "plain answer");
    onToolBoundary(s);
    expect(s.inThinking).toBe(false);
  });
});

describe("applyEvent", () => {
  it("renders inline <think> content as a thinking item", () => {
    const items = play([delta("<think>let me see</think>"), delta("the answer")]);
    expect(items.map((i) => i.kind)).toEqual(["thinking", "assistant"]);
    expect((items[0] as { text: string }).text).toBe("let me see");
    expect((items[1] as { text: string }).text).toBe("the answer");
  });

  it("never shows literal think tags in any item", () => {
    const items = play([
      delta("<thi"),
      delta("nk>hidden</think>"),
      delta("visible"),
    ]);
    for (const it of items) {
      if ("text" in it) {
        expect(it.text).not.toContain("<think>");
        expect(it.text).not.toContain("</think>");
      }
    }
  });

  it("merges consecutive same-kind deltas into one item", () => {
    const items = play([delta("Hello "), delta("world")]);
    expect(items).toHaveLength(1);
    expect((items[0] as { text: string }).text).toBe("Hello world");
  });

  it("respects the is_thinking flag from Agno reasoning events", () => {
    const items = play([delta("native reasoning", true), delta("answer")]);
    expect(items.map((i) => i.kind)).toEqual(["thinking", "assistant"]);
  });

  it("handles post-tool thinking resume without an opening tag", () => {
    const items = play([
      delta("<think>before tool</think>calling now"),
      toolStarted,
      toolCompleted,
      delta("resumed thought</think>final answer"),
    ]);
    const kinds = items.map((i) => i.kind);
    expect(kinds).toEqual(["thinking", "assistant", "tool", "thinking", "assistant"]);
    expect((items[4] as { text: string }).text).toBe("final answer");
  });

  it("updates the running tool card on completion", () => {
    const items = play([toolStarted, toolCompleted]);
    const tool = items[0] as Extract<ChatItem, { kind: "tool" }>;
    expect(tool.status).toBe("done");
    expect(tool.result).toBe("content");
  });

  it("marks failed tools as errors", () => {
    const items = play([
      toolStarted,
      { ...toolCompleted, is_error: true } as ServerMessage,
    ]);
    const tool = items[0] as Extract<ChatItem, { kind: "tool" }>;
    expect(tool.status).toBe("error");
  });
});

describe("restoredItem", () => {
  it("strips injected system-context from user turns", () => {
    const item = restoredItem(
      "user",
      "<system-context>Current datetime: 2026-06-11 14:42 CEST</system-context>\nCount to 20.",
    );
    expect(item).toMatchObject({ kind: "user", text: "Count to 20." });
  });

  it("strips closed think blocks from assistant turns", () => {
    const item = restoredItem(
      "assistant",
      "<think>plan it out</think>\nDone. Created notes.txt.",
    );
    expect(item).toMatchObject({ kind: "assistant", text: "Done. Created notes.txt." });
  });

  it("strips a trailing unclosed think block (cancelled run)", () => {
    const item = restoredItem("assistant", "Partial answer.\n<think>was still reason");
    expect(item).toMatchObject({ kind: "assistant", text: "Partial answer." });
  });

  it("renders a /loop iteration as a structured loop item, not a raw user bubble", () => {
    const wrapped =
      '<loop-iteration index="3" total="5">\n' +
      "Autonomous loop iteration — do not ask the user; perform one unit of work and stop. " +
      "Tool-permission prompts are the only legitimate user interaction.\n\n" +
      "When you can determine the total number of items (e.g. after listing files or parsing the input), " +
      "call loop_set_total(N) once so the panel renders progress as N/total. " +
      "Call loop_stop() when all work is done — don't keep looping just because the safety cap hasn't been hit.\n\n" +
      "process file 3\n" +
      "</loop-iteration>";
    const item = restoredItem("user", wrapped);
    expect(item?.kind).toBe("loop");
    if (item?.kind === "loop") {
      expect(item.index).toBe(3);
      expect(item.total).toBe(5);
      expect(item.body).toBe("process file 3");
    }
  });

  it("returns null when nothing remains or role is unknown", () => {
    expect(restoredItem("assistant", "<think>only thoughts</think>")).toBeNull();
    expect(restoredItem("user", "  ")).toBeNull();
    expect(restoredItem("system", "boot")).toBeNull();
  });
});

describe("run stats line", () => {
  const modelCompleted = (input: number, output: number): ServerMessage =>
    ({ type: "model_completed", input_tokens: input, output_tokens: output, run_id: "r1", parent_run_id: "" }) as ServerMessage;
  const runCompleted = (
    input: number,
    output: number,
    duration: number,
    parent = "",
    reasoning = 0,
  ): ServerMessage =>
    ({
      type: "run_completed",
      input_tokens: input,
      output_tokens: output,
      reasoning_tokens: reasoning,
      duration,
      run_id: "r1",
      parent_run_id: parent,
    }) as ServerMessage;

  // Stats items render via formatStats — exercise that path here so
  // the tests pin the visible string the chat shows.
  const statsItem = (item: ChatItem) => {
    if (item.kind !== "stats") throw new Error("not a stats item: " + item.kind);
    return item;
  };
  const statsText = (item: ChatItem) => formatStats(statsItem(item));

  // 'out' / 'think' now count chars-of-rendered-text/4. Build helpers
  // that emit deltas of the right size so we can assert clean counts.
  const reply = (tokens: number) => delta("a".repeat(tokens * 4));      // visible
  const think = (tokens: number) => delta("a".repeat(tokens * 4), true); // reasoning
  const lastStats = (items: ChatItem[]) =>
    items.filter((i) => i.kind === "stats").at(-1) as ChatItem;

  it("does not render per-step model_completed badges", () => {
    expect(
      play([modelCompleted(14000, 90), modelCompleted(15000, 80)]).filter(
        (i) => i.kind === "stats",
      ),
    ).toHaveLength(0);
  });

  it("renders one roll-up line with duration on run_completed", () => {
    const items = play([reply(240), runCompleted(27400, 240, 12.4)]);
    expect(statsText(lastStats(items))).toBe("✦ 27.4k in · 240 out · 12.4s");
  });

  it("formats minute-scale durations and skips zero duration", () => {
    expect(
      statsText(lastStats(play([reply(1), runCompleted(1000, 1, 75)]))),
    ).toContain("1m 15s");
    expect(
      statsText(lastStats(play([reply(1), runCompleted(1000, 1, 0)]))),
    ).toBe("✦ 1.0k in · 1 out");
  });

  it("ignores sub-agent run_completed events", () => {
    expect(
      play([runCompleted(5000, 50, 3, "parent-run")]).filter(
        (i) => i.kind === "stats",
      ),
    ).toHaveLength(0);
  });

  it("splits visible thinking and visible reply into separate segments", () => {
    // Reasoning model: 280 tokens of thinking, 50 tokens of visible
    // reply. Agno billed it as 330 output total (280 reasoning) — we
    // don't read those for display; we count what we rendered.
    const items = play([think(280), reply(50), runCompleted(22000, 330, 16, "", 280)]);
    expect(statsText(lastStats(items))).toBe("✦ 22.0k in · 280 think · 50 out · 16.0s");
  });

  it("correctStatsCtx replaces input with count_context_tokens", () => {
    const items = play([think(280), reply(50), runCompleted(22000, 330, 16, "", 280)]);
    const fixed = correctStatsCtx(items, "r1", 13900);
    expect(statsText(lastStats(fixed))).toBe(
      "✦ 13.9k in · 280 think · 50 out · 16.0s",
    );
    // Other stats items (different runId) shouldn't move.
    const otherRun = correctStatsCtx(items, "r2", 9999);
    expect(statsText(lastStats(otherRun))).toBe(
      "✦ 22.0k in · 280 think · 50 out · 16.0s",
    );
  });
});

describe("parseLoopIteration", () => {
  const wrapped = (idx: number, total: number | null, body: string) =>
    `<loop-iteration index="${idx}"${total ? ` total="${total}"` : ""}>\n` +
    `Autonomous loop iteration — do not ask the user; perform one unit of work and stop. ` +
    `Tool-permission prompts are the only legitimate user interaction.\n\n` +
    `When you can determine the total number of items (e.g. after listing files or parsing the input), ` +
    `call loop_set_total(N) once so the panel renders progress as N/total. ` +
    `Call loop_stop() when all work is done — don't keep looping just because the safety cap hasn't been hit.\n\n` +
    `${body}\n` +
    `</loop-iteration>`;

  it("extracts iteration index, total, and the original ask", () => {
    const parsed = parseLoopIteration(
      wrapped(2, 45, "Through each president of the USA and sum all their dates of birth. Do it one by one"),
    );
    expect(parsed).toEqual({
      index: 2,
      total: 45,
      body:
        "Through each president of the USA and sum all their dates of birth. Do it one by one",
    });
  });

  it("returns total null when the BE omits the attribute", () => {
    const parsed = parseLoopIteration(wrapped(1, null, "do thing X"));
    expect(parsed?.total).toBeNull();
    expect(parsed?.body).toBe("do thing X");
  });

  it("preserves blank lines inside the user's prompt", () => {
    const body = "Step 1: list files\n\nStep 2: summarize each";
    const parsed = parseLoopIteration(wrapped(3, 10, body));
    expect(parsed?.body).toBe(body);
  });

  it("returns null when the wrapper is missing", () => {
    expect(parseLoopIteration("just plain text")).toBeNull();
  });

  it("loopItem builds a structured chat item; falls back to info on bad input", () => {
    const ok = loopItem(wrapped(7, 12, "the ask"));
    expect(ok.kind).toBe("loop");
    if (ok.kind === "loop") {
      expect(ok.index).toBe(7);
      expect(ok.total).toBe(12);
      expect(ok.body).toBe("the ask");
    }
    const bad = loopItem("not a loop wrapper");
    expect(bad.kind).toBe("info");
  });
});
