const DATE_KEY_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * The device's local calendar date as YYYY-MM-DD.
 * Deliberately not `toISOString().slice(0, 10)`: that is the UTC date, which is the wrong
 * day for part of every day in most timezones.
 */
export function localDateKey(date: Date): string {
  const year = String(date.getFullYear()).padStart(4, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isLocalDateKey(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = DATE_KEY_PATTERN.exec(value);
  if (!match) return false;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return localDateKey(date) === value;
}

/** Local midnight at the start of the given day. */
export function dateFromKey(key: string): Date {
  const [year, month, day] = key.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** The `count` most recent days ending at `todayKey`, newest first. */
export function recentDateKeys(todayKey: string, count: number): string[] {
  const today = dateFromKey(todayKey);
  return Array.from({ length: count }, (_, daysAgo) =>
    // Going through the Date constructor handles month ends and daylight-saving changes.
    localDateKey(new Date(today.getFullYear(), today.getMonth(), today.getDate() - daysAgo)),
  );
}
