import { describe, expect, it } from "vitest";

import {
  canRegenerate,
  coachHelp,
  findingById,
  playRange,
  practiseLine,
  regenerationState,
} from "./coaching";
import type { RunState } from "./generalStore";
import type { Coaching, Evidence, JobStatus, SpeechSegment } from "./types";

const evidence = (overrides: Partial<Evidence>): Evidence => ({
  kind: "segment",
  id: "seg-1",
  label: "Segment 1",
  startSeconds: 4,
  endSeconds: 9,
  ...overrides,
});

const coaching = (overrides: Partial<Coaching> = {}): Coaching => ({
  source: "ai",
  model: "llama3.1:8b",
  notice: null,
  summary: [],
  findings: [
    { id: "f1", kind: "pace", level: "high", role: "issue", statement: "Fast.", evidence: [] },
  ],
  corrections: [],
  working: [],
  nextTake: [],
  caveats: [],
  settings: {},
  generatedAt: "2026-10-11T05:00:00Z",
  modelSeconds: 30,
  ...overrides,
});

describe("what to play for a piece of evidence", () => {
  it("plays a phrase from its start to its end", () => {
    expect(playRange(evidence({}))).toEqual({ start: 4, end: 9 });
  });

  it("plays a pause with a little speech either side", () => {
    expect(playRange(evidence({ kind: "pause", startSeconds: 4, endSeconds: 6 }))).toEqual({
      start: 2.5,
      end: 7.5,
    });
    // Never before the start of the recording.
    expect(playRange(evidence({ kind: "pause", startSeconds: 0.5, endSeconds: 2 }))?.start).toBe(0);
  });

  it("has nothing to play for a whole-recording measurement", () => {
    expect(
      playRange(evidence({ kind: "metric", id: "paceVariation", startSeconds: null, endSeconds: null })),
    ).toBeNull();
  });
});

describe("looking things up", () => {
  it("finds the finding a correction is about", () => {
    expect(findingById(coaching(), "f1")?.statement).toBe("Fast.");
    expect(findingById(coaching(), "f9")).toBeUndefined();
  });

  it("takes the practice line from the transcript, never from the model's wording", () => {
    const segments = [{ id: "seg-1", transcript: "I am the danger." }] as SpeechSegment[];
    expect(practiseLine(evidence({}), segments)).toBe("I am the danger.");
    expect(practiseLine(evidence({ id: "seg-7" }), segments)).toBeNull();
    expect(practiseLine(evidence({ kind: "pause", id: "pause-1" }), segments)).toBeNull();
    expect(practiseLine(null, segments)).toBeNull();
  });
});

describe("help when the AI model is not available", () => {
  it("gives the command to start Ollama", () => {
    expect(coachHelp("not_running", null)?.command).toBe("ollama serve");
  });

  it("names the configured model, and says the app will not download it", () => {
    const help = coachHelp("model_missing", "llama3.1:8b");
    expect(help?.command).toBe("ollama pull llama3.1:8b");
    expect(help?.text).toContain("never downloads a model");
  });

  it("has nothing to add for reasons the user cannot act on", () => {
    expect(coachHelp("ungrounded", null)).toBeNull();
    expect(coachHelp("bad_answer", null)).toBeNull();
  });
});

describe("offering to write the coaching again", () => {
  it("is offered when the model wrote it, or could not be reached", () => {
    expect(canRegenerate(coaching())).toBe(true);
    expect(
      canRegenerate(coaching({ source: "rules", notice: { code: "not_running", message: "" } })),
    ).toBe(true);
    // A result with no coaching stored at all.
    expect(canRegenerate(null)).toBe(true);
  });

  it("is not offered when asking again could not change anything", () => {
    expect(
      canRegenerate(coaching({ source: "none", notice: { code: "no_speech", message: "" } })),
    ).toBe(false);
    expect(
      canRegenerate(
        coaching({ source: "rules", notice: { code: "nothing_to_correct", message: "" } }),
      ),
    ).toBe(false);
  });
});

describe("the progress shown beside the button", () => {
  const job = { jobId: "job-c", kind: "coaching" } as JobStatus;
  const during = (run: RunState, coachingFor: string | null = "analysis-1") =>
    regenerationState({ run, runKind: coachingFor ? "coaching" : "analysis", coachingFor }, "analysis-1");

  it("follows a coaching run for this analysis", () => {
    expect(during({ phase: "submitting" })).toEqual({ status: "running" });
    expect(during({ phase: "tracking", job, contact: "ok" })).toEqual({ status: "running" });
    expect(during({ phase: "done", job, analysisId: "analysis-1" })).toEqual({ status: "done" });
    expect(
      during({
        phase: "failed",
        job,
        error: { code: "not_running", message: "Ollama is not running." },
        canResubmit: false,
      }),
    ).toEqual({ status: "failed", message: "Ollama is not running." });
    expect(during({ phase: "cancelled", job })).toEqual({ status: "idle" });
    expect(during({ phase: "idle" })).toEqual({ status: "idle" });
  });

  it("stays quiet for an ordinary analysis, or for another analysis's coaching", () => {
    expect(during({ phase: "tracking", job, contact: "ok" }, null)).toEqual({ status: "idle" });
    expect(during({ phase: "tracking", job, contact: "ok" }, "analysis-2")).toEqual({
      status: "idle",
    });
  });
});
