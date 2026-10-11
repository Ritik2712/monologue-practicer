/** Turning measured values into the text shown on screen. */
import type { MetricValue, PauseSignificance, Profile, Quality } from "./types";

/** Shown wherever a value could not be measured. Never "0". */
export const UNAVAILABLE = "—";

/** A position in the recording, e.g. 0:04.7 or 12:03.0. */
export function formatTimecode(seconds: number): string {
  const tenths = Math.round(Math.max(0, seconds) * 10);
  const minutes = Math.floor(tenths / 600);
  const rest = (tenths % 600) / 10;
  return `${minutes}:${rest.toFixed(1).padStart(4, "0")}`;
}

/** A length of time, e.g. "0.8 s", "17.1 s" or "2 min 13 s". */
export function formatSpan(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)} min ${whole % 60} s`;
}

export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return UNAVAILABLE;
  return value.toLocaleString("en", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A change between two attempts, always with its sign: "+12.3" or "−4.0". */
export function formatDelta(delta: number, digits = 1): string {
  const rounded = Number(delta.toFixed(digits));
  if (rounded === 0) return `±${(0).toFixed(digits)}`;
  // A real minus sign, not a hyphen.
  return `${rounded > 0 ? "+" : "−"}${formatNumber(Math.abs(rounded), digits)}`;
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return UNAVAILABLE;
  return `${Math.round(ratio * 100)}%`;
}

export function formatMetric(metric: MetricValue | undefined, digits = 1): string {
  return formatNumber(metric?.value, digits);
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

const PROFILE_NAMES: Record<Profile, string> = {
  walter_white: "Walter White",
  joker: "Joker",
  thomas_shelby: "Thomas Shelby",
  custom: "Custom / neutral",
};

export function profileName(profile: Profile): string {
  return PROFILE_NAMES[profile] ?? profile;
}

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  hinglish: "Hinglish",
  unknown: "Unknown",
};

export function languageName(code: string): string {
  return LANGUAGE_NAMES[code] ?? code.toUpperCase();
}

export const QUALITY_LABELS: Record<Quality, string> = {
  measured: "Measured",
  estimated: "Estimate",
  unavailable: "Unavailable",
};

export const PAUSE_LABELS: Record<PauseSignificance, string> = {
  short: "Short",
  medium: "Medium",
  long: "Long silence",
};

/** Why a segment's WPM carries a caution, in plain words. */
export const FLAG_LABELS: Record<string, string> = {
  short_segment: "Too short to measure reliably",
  few_words: "Too few words to measure reliably",
  low_confidence: "The speech recogniser was unsure of the words",
  wpm_outlier: "Unusually fast: worth checking the transcript",
  no_words: "No words were recognised here",
  no_transcript: "No transcript",
};

export const STAGE_LABELS = {
  preparing_audio: "Reading the audio",
  detecting_speech: "Finding where you speak",
  transcribing: "Recognising the words",
  measuring_audio: "Measuring pace, pauses, loudness and pitch",
  generating_feedback: "Writing the coaching",
  summarising_feedback: "Picking out your most telling notes",
} as const;
