/**
 * Checks on an audio file before it is sent, so an obviously wrong file gets a clear answer
 * straight away. The backend makes the same checks again and has the final say.
 */
import { formatBytes } from "./format";
import type { UploadLimits } from "./types";

export type FileCheck = { ok: true } | { ok: false; message: string };

export function fileExtension(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot > 0 ? filename.slice(dot).toLowerCase() : "";
}

export function validateAudioFile(
  file: { name: string; type: string; size: number },
  limits: UploadLimits,
): FileCheck {
  const extension = fileExtension(file.name);
  const knownExtension = limits.acceptedExtensions.includes(extension);
  // Some files have no useful name (a recording handed over by another app, say).
  const audioType = file.type.toLowerCase().startsWith("audio/");
  if (!knownExtension && !audioType) {
    return {
      ok: false,
      message: `This does not look like an audio file. Accepted types: ${limits.acceptedExtensions
        .map((item) => item.slice(1).toUpperCase())
        .join(", ")}.`,
    };
  }
  if (file.size === 0) {
    return { ok: false, message: "This file is empty." };
  }
  if (file.size > limits.maxUploadBytes) {
    return {
      ok: false,
      message: `This file is ${formatBytes(file.size)}. The limit is ${formatBytes(limits.maxUploadBytes)}.`,
    };
  }
  return { ok: true };
}

/** The `accept` attribute for the file picker. */
export function acceptAttribute(limits: UploadLimits): string {
  return ["audio/*", ...limits.acceptedExtensions].join(",");
}
