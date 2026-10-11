import { dateFromKey, recentDateKeys } from "./localDate";

/** Countdown text: MM:SS, or HH:MM:SS from one hour up. Rounds up so 00:00 means finished. */
export function formatClock(ms: number): string {
  const totalSeconds = Math.max(0, Math.ceil(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const mmss = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return hours > 0 ? `${String(hours).padStart(2, "0")}:${mmss}` : mmss;
}

/** Planned length of a step, e.g. "3 min" or "1 min 30 sec". */
export function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds} sec`;
  return seconds === 0 ? `${minutes} min` : `${minutes} min ${seconds} sec`;
}

/** Total routine length in minutes, to one decimal place at most, e.g. 15 or 12.5. */
export function totalMinutes(durationsSeconds: readonly number[]): number {
  const seconds = durationsSeconds.reduce((sum, value) => sum + value, 0);
  return Math.round((seconds / 60) * 10) / 10;
}

export function formatDayLabel(dateKey: string, todayKey: string): string {
  const [today, yesterday] = recentDateKeys(todayKey, 2);
  if (dateKey === today) return "Today";
  if (dateKey === yesterday) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(dateFromKey(dateKey));
}
