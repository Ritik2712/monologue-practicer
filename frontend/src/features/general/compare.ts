/**
 * Comparing one attempt with an earlier one.
 *
 * Only the change is reported, never "better" or "worse": whether a slower pace or a longer
 * pause is an improvement depends on what the speaker was going for.
 */
import type { AnalysisSummary, MetricName, MetricValue } from "./types";

export type ComparedMetric = {
  key: MetricName;
  label: string;
  unit: string;
  digits: number;
  /** Shown as a percentage rather than a ratio. */
  percent?: boolean;
};

export const COMPARED_METRICS: ComparedMetric[] = [
  { key: "speechActiveWpm", label: "Speech-active WPM", unit: "WPM", digits: 1 },
  { key: "wholeClipWpm", label: "Whole-clip WPM (including pauses)", unit: "WPM", digits: 1 },
  { key: "paceVariation", label: "Pace variation", unit: "WPM", digits: 1 },
  { key: "pauseCount", label: "Pauses", unit: "", digits: 0 },
  { key: "medianPauseSeconds", label: "Median pause", unit: "s", digits: 2 },
  { key: "longestPauseSeconds", label: "Longest pause", unit: "s", digits: 2 },
  { key: "pauseRatio", label: "Share of the recording spent in pauses", unit: "%", digits: 0, percent: true },
  { key: "energyVariation", label: "Loudness variation", unit: "dB", digits: 1 },
  { key: "pitchVariationSemitones", label: "Pitch variation", unit: "semitones", digits: 2 },
];

export type ComparisonRow = ComparedMetric & {
  current: number | null;
  previous: number | null;
  /** Null when either side is unavailable: no number is invented for the gap. */
  delta: number | null;
  /** True when either value is an estimate, so the difference is one too. */
  estimated: boolean;
};

type MetricMap = Partial<Record<MetricName, MetricValue>>;

export function compareAttempts(current: MetricMap, previous: MetricMap): ComparisonRow[] {
  return COMPARED_METRICS.map((metric) => {
    const now = current[metric.key];
    const before = previous[metric.key];
    const scale = metric.percent ? 100 : 1;
    // Rounded to what is shown before subtracting, so the three columns always add up:
    // 32% against 50% reads as -18, never -19 because of hidden decimals.
    const shown = (value: number | null | undefined) =>
      value === null || value === undefined ? null : Number((value * scale).toFixed(metric.digits));
    const currentValue = shown(now?.value);
    const previousValue = shown(before?.value);
    return {
      ...metric,
      current: currentValue,
      previous: previousValue,
      delta: currentValue === null || previousValue === null ? null : currentValue - previousValue,
      estimated: now?.quality === "estimated" || before?.quality === "estimated",
    };
  });
}

/** Attempts made before the given one, newest first: the candidates to compare against. */
export function earlierAttempts(history: AnalysisSummary[], analysisId: string, createdAt: string) {
  const moment = Date.parse(createdAt);
  return history
    .filter((item) => item.analysisId !== analysisId && Date.parse(item.createdAt) <= moment)
    .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
}
