"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { createApi } from "./api";
import { isResolvingDuration, resolveUnknownDuration } from "./audioDuration";
import { createFeedbackStore, INITIAL_FEEDBACK_STATE } from "./feedbackStore";
import { createGeneralStore, INITIAL_GENERAL_STATE } from "./generalStore";
import { createHealthMonitor, INITIAL_HEALTH } from "./healthMonitor";
import { browserRecorderEnv, createRecorder, type RecorderState } from "./recorder";

function schedule(callback: () => void, ms: number) {
  const handle = window.setTimeout(callback, ms);
  return () => window.clearTimeout(handle);
}

function newKey(): string {
  // randomUUID needs a secure page; localhost counts, but fall back rather than fail.
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function localStorageOrNull() {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

// One of each for the whole page, as with the checklist: remounting a component can never
// start a second recording or a second set of status checks.
export const generalApi = createApi();
const generalStore = createGeneralStore({
  api: generalApi,
  schedule,
  newKey,
  getStorage: localStorageOrNull,
  revokeUrl: (url) => URL.revokeObjectURL(url),
});
const feedbackStore = createFeedbackStore(generalApi);
const healthMonitor = createHealthMonitor(generalApi, schedule);
const recorder = createRecorder(browserRecorderEnv());

const IDLE_RECORDER: RecorderState = { status: "idle" };

export function useGeneralStore() {
  const state = useSyncExternalStore(
    generalStore.subscribe,
    generalStore.getSnapshot,
    () => INITIAL_GENERAL_STATE,
  );
  useEffect(() => {
    generalStore.init();
  }, []);
  return { state, store: generalStore };
}

/**
 * The feedback given on one analysis, and the calibration it feeds. Pass null when no
 * result is on view: the calibration is still loaded.
 */
export function useFeedback(analysisId: string | null) {
  const state = useSyncExternalStore(
    feedbackStore.subscribe,
    feedbackStore.getSnapshot,
    () => INITIAL_FEEDBACK_STATE,
  );
  useEffect(() => {
    feedbackStore.loadCalibration();
  }, []);
  useEffect(() => {
    feedbackStore.watch(analysisId);
  }, [analysisId]);
  return { state, store: feedbackStore };
}

export function useBackendHealth() {
  const health = useSyncExternalStore(
    healthMonitor.subscribe,
    healthMonitor.getSnapshot,
    () => INITIAL_HEALTH,
  );
  return { health, refresh: healthMonitor.refresh };
}

export function useRecorder() {
  const state = useSyncExternalStore(recorder.subscribe, recorder.getSnapshot, () => IDLE_RECORDER);
  return { state, recorder };
}

/**
 * Playback of a recording, with "play just this stretch": a segment, a pause with a little
 * either side, or from a point on the timeline onwards.
 */
export function useSegmentPlayer() {
  const audioRef = useRef<HTMLAudioElement>(null);
  const stopAtRef = useRef<number | null>(null);
  const frameRef = useRef<number | null>(null);
  const [currentTime, setCurrentTime] = useState<number | null>(null);

  const playRange = useCallback((startSeconds: number, endSeconds?: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    frameRef.current = null;

    // Checked every frame: the audio element's own time events arrive only ~4 times a second,
    // which would overshoot the end of a short segment.
    function watchForEnd() {
      const stopAt = stopAtRef.current;
      if (!audio || stopAt === null) return;
      if (audio.currentTime >= stopAt || audio.paused) {
        if (!audio.paused) audio.pause();
        stopAtRef.current = null;
        frameRef.current = null;
        return;
      }
      frameRef.current = requestAnimationFrame(watchForEnd);
    }

    audio.currentTime = Math.max(0, startSeconds);
    stopAtRef.current = endSeconds ?? null;
    audio.play().then(
      () => {
        if (stopAtRef.current !== null) frameRef.current = requestAnimationFrame(watchForEnd);
      },
      () => {
        stopAtRef.current = null;
      },
    );
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  const audioProps = {
    ref: audioRef,
    onTimeUpdate: () => {
      const audio = audioRef.current;
      if (!audio || !Number.isFinite(audio.currentTime) || isResolvingDuration(audio)) return;
      setCurrentTime(audio.currentTime);
      // A second line of defence for the end of a range: browsers pause the per-frame check
      // while the tab is in the background, but these time events keep arriving.
      if (stopAtRef.current !== null && audio.currentTime >= stopAtRef.current) {
        audio.pause();
        stopAtRef.current = null;
      }
    },
    // A browser-made recording reports no length at first; see audioDuration.ts.
    onLoadedMetadata: () => {
      if (audioRef.current) resolveUnknownDuration(audioRef.current, () => setCurrentTime(null));
    },
    onDurationChange: () => {
      if (audioRef.current) resolveUnknownDuration(audioRef.current, () => setCurrentTime(null));
    },
  };

  return { audioProps, playRange, currentTime };
}

/**
 * The pixel width of an element, kept up to date as the layout changes.
 *
 * The element is handed over through a callback, not a ref object, so this also works for
 * an element that appears later than the component does (after its data has loaded).
 */
export function useElementWidth<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [element]);
  return { ref: setElement, width };
}
