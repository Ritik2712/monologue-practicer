/**
 * The addresses analyses are downloaded from, as Markdown documents.
 *
 * A download is a plain link to the backend, which answers with a file to save. Nothing
 * is fetched by the page and nothing is built in the browser: the document is written by
 * the backend from the stored results, so it says exactly what they hold.
 */
import { apiUrl } from "@/lib/api";

/** One analysis: a take, or a monologue's original. */
export function analysisExportUrl(analysisId: string): string {
  return apiUrl(`/api/analyses/${encodeURIComponent(analysisId)}/export`);
}

/** A monologue's original and every take recorded for it. */
export function monologueExportUrl(monologueId: string): string {
  return apiUrl(`/api/export?scope=monologue&monologue=${encodeURIComponent(monologueId)}`);
}

/** Every take that belongs to no monologue. */
export function generalExportUrl(): string {
  return apiUrl("/api/export?scope=general");
}

/** Every monologue with its takes, and the General Practice takes. */
export function everythingExportUrl(): string {
  return apiUrl("/api/export?scope=all");
}
