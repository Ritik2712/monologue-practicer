const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Base URL of the local FastAPI backend, without a trailing slash. */
export function apiBaseUrl(
  configured: string | undefined = process.env.NEXT_PUBLIC_API_BASE_URL,
): string {
  const base = configured?.trim() || DEFAULT_API_BASE_URL;
  return base.replace(/\/+$/, "");
}

export function apiUrl(path: string, base: string = apiBaseUrl()): string {
  return `${base}${path.startsWith("/") ? path : `/${path}`}`;
}
