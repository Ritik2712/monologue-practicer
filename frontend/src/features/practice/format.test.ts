import { describe, expect, it } from "vitest";

import { formatClock, formatDayLabel, formatDuration, totalMinutes } from "./format";
import { isLocalDateKey, localDateKey, recentDateKeys } from "./localDate";

describe("formatClock", () => {
  it("shows MM:SS and rounds up so 00:00 only appears when time is up", () => {
    expect(formatClock(180_000)).toBe("03:00");
    expect(formatClock(179_001)).toBe("03:00");
    expect(formatClock(179_000)).toBe("02:59");
    expect(formatClock(1)).toBe("00:01");
    expect(formatClock(0)).toBe("00:00");
    expect(formatClock(-500)).toBe("00:00");
  });

  it("switches to HH:MM:SS from one hour", () => {
    expect(formatClock(3_599_000)).toBe("59:59");
    expect(formatClock(3_600_000)).toBe("01:00:00");
    expect(formatClock(3_661_000)).toBe("01:01:01");
  });
});

describe("durations", () => {
  it("formats planned step lengths", () => {
    expect(formatDuration(180)).toBe("3 min");
    expect(formatDuration(90)).toBe("1 min 30 sec");
    expect(formatDuration(45)).toBe("45 sec");
  });

  it("totals a routine in minutes", () => {
    expect(totalMinutes([180, 180, 240, 180, 120])).toBe(15);
    expect(totalMinutes([90, 60])).toBe(2.5);
  });
});

describe("local dates", () => {
  it("builds the key from local calendar fields", () => {
    expect(localDateKey(new Date(2026, 0, 5, 23, 59, 59))).toBe("2026-01-05");
    expect(localDateKey(new Date(2026, 0, 6, 0, 0, 0))).toBe("2026-01-06");
  });

  it("differs from the UTC date slice early in the local day", () => {
    // Tests run in Asia/Kolkata (UTC+5:30).
    const earlyMorning = new Date(2026, 0, 6, 1, 0, 0);
    expect(earlyMorning.toISOString().slice(0, 10)).toBe("2026-01-05");
    expect(localDateKey(earlyMorning)).toBe("2026-01-06");
  });

  it("lists recent days across a month boundary, newest first", () => {
    expect(recentDateKeys("2026-03-02", 4)).toEqual([
      "2026-03-02",
      "2026-03-01",
      "2026-02-28",
      "2026-02-27",
    ]);
  });

  it("accepts only real calendar dates", () => {
    expect(isLocalDateKey("2026-02-28")).toBe(true);
    expect(isLocalDateKey("2026-02-30")).toBe(false);
    expect(isLocalDateKey("2026-2-3")).toBe(false);
    expect(isLocalDateKey(20260228)).toBe(false);
  });

  it("labels today and yesterday in words", () => {
    expect(formatDayLabel("2026-03-01", "2026-03-01")).toBe("Today");
    expect(formatDayLabel("2026-02-28", "2026-03-01")).toBe("Yesterday");
    expect(formatDayLabel("2026-02-27", "2026-03-01")).toContain("2026");
  });
});
