/** The addresses of the monologue screens, built in one place. */

/** Daily Practice for one monologue. */
export function practiceHref(monologueId: string): string {
  return `/practice?monologue=${encodeURIComponent(monologueId)}`;
}

/** The full analysis of one take of a monologue. */
export function takeHref(analysisId: string): string {
  return `/monologue/take?analysis=${encodeURIComponent(analysisId)}`;
}

export const MONOLOGUES_HREF = "/monologue";
