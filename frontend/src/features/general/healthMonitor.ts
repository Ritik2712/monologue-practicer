/**
 * Keeps an eye on the local backend while the General Practice screen is open, so the page
 * can say plainly when the API, the worker or the speech model is missing.
 *
 * It checks only while something is subscribed, and stops when the screen is left.
 */
import type { GeneralApi } from "./api";
import type { Health } from "./types";

export const HEALTH_CHECK_MS = 10_000;

export type HealthState =
  | { status: "checking" }
  | { status: "unreachable" }
  | { status: "reachable"; health: Health };

export type HealthMonitor = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => HealthState;
  /** Checks now, e.g. straight after the user says they started something. */
  refresh: () => void;
};

export const INITIAL_HEALTH: HealthState = { status: "checking" };

export function createHealthMonitor(
  api: Pick<GeneralApi, "getHealth">,
  schedule: (callback: () => void, ms: number) => () => void,
): HealthMonitor {
  const listeners = new Set<() => void>();
  let state: HealthState = INITIAL_HEALTH;
  let cancelNext: (() => void) | null = null;
  /** Goes up on every stop, so an answer that arrives afterwards changes nothing. */
  let session = 0;

  function set(next: HealthState) {
    // Same answer as before: no need to redraw anything.
    if (JSON.stringify(next) === JSON.stringify(state)) return;
    state = next;
    listeners.forEach((listener) => listener());
  }

  function check() {
    const current = session;
    cancelNext?.();
    cancelNext = null;
    api.getHealth().then(
      (health) => current === session && set({ status: "reachable", health }),
      () => current === session && set({ status: "unreachable" }),
    ).finally(() => {
      if (current === session && listeners.size > 0) cancelNext = schedule(check, HEALTH_CHECK_MS);
    });
  }

  return {
    subscribe(listener) {
      listeners.add(listener);
      if (listeners.size === 1) check();
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) {
          session += 1;
          cancelNext?.();
          cancelNext = null;
        }
      };
    },
    getSnapshot: () => state,
    refresh: check,
  };
}
