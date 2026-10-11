import { describe, expect, it, vi } from "vitest";

import { createHealthMonitor, HEALTH_CHECK_MS } from "./healthMonitor";
import type { Health } from "./types";

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
const healthy: Health = { status: "ok", database: "ok", worker: "running", speechModel: "ready" };

function setup() {
  const getHealth = vi.fn().mockResolvedValue(healthy);
  const timers: { callback: () => void; ms: number }[] = [];
  const monitor = createHealthMonitor({ getHealth }, (callback, ms) => {
    const timer = { callback, ms };
    timers.push(timer);
    return () => void timers.splice(timers.indexOf(timer), 1);
  });
  return { monitor, getHealth, timers };
}

describe("health monitor", () => {
  it("does nothing until something is watching", () => {
    const { monitor, getHealth } = setup();
    expect(monitor.getSnapshot()).toEqual({ status: "checking" });
    expect(getHealth).not.toHaveBeenCalled();
  });

  it("checks straight away, then again every ten seconds", async () => {
    const { monitor, getHealth, timers } = setup();
    const listener = vi.fn();
    monitor.subscribe(listener);
    await settle();

    expect(monitor.getSnapshot()).toEqual({ status: "reachable", health: healthy });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(timers.map((timer) => timer.ms)).toEqual([HEALTH_CHECK_MS]);

    timers[0].callback();
    await settle();
    expect(getHealth).toHaveBeenCalledTimes(2);
    // The answer did not change, so nothing is redrawn.
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("reports the worker stopping, and the backend going away", async () => {
    const { monitor, getHealth, timers } = setup();
    monitor.subscribe(() => {});
    await settle();

    getHealth.mockResolvedValue({ ...healthy, worker: "not_running" });
    timers[0].callback();
    await settle();
    expect(monitor.getSnapshot()).toMatchObject({ health: { worker: "not_running" } });

    getHealth.mockRejectedValue(new Error("connection refused"));
    timers[0].callback();
    await settle();
    expect(monitor.getSnapshot()).toEqual({ status: "unreachable" });
    expect(timers).toHaveLength(1); // still checking, so it notices when the backend returns
  });

  it("stops checking when the screen is left", async () => {
    const { monitor, getHealth, timers } = setup();
    const unsubscribe = monitor.subscribe(() => {});
    await settle();
    unsubscribe();
    expect(timers).toHaveLength(0);

    monitor.subscribe(() => {});
    await settle();
    expect(getHealth).toHaveBeenCalledTimes(2);
  });

  it("can be asked to check now", async () => {
    const { monitor, getHealth, timers } = setup();
    monitor.subscribe(() => {});
    await settle();
    monitor.refresh();
    await settle();
    expect(getHealth).toHaveBeenCalledTimes(2);
    expect(timers).toHaveLength(1); // the scheduled check was replaced, not doubled
  });
});
