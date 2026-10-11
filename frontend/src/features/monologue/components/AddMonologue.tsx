"use client";

import { useId, useRef, useState } from "react";

import { Button } from "@/components/Button";
import { FOCUS_RING, MUTED } from "@/features/general/components/parts";
import { formatBytes } from "@/features/general/format";
import type { GeneralStore } from "@/features/general/generalStore";
import type { AnalysisOptions, LanguageHint } from "@/features/general/types";
import { acceptAttribute, validateAudioFile } from "@/features/general/validation";

type AddMonologueProps = {
  store: GeneralStore;
  /** Upload limits and language choices. Null until they have loaded. */
  options: AnalysisOptions | null;
  /** True while an analysis is in progress, when another cannot be started. */
  busy: boolean;
  /** Open from the start when there is no monologue yet. */
  initiallyOpen: boolean;
};

/**
 * Adds a monologue to practise: the original recording of it, which is measured on this
 * computer exactly like one of your own takes and then compared with them.
 */
export function AddMonologue({ store, options, busy, initiallyOpen }: AddMonologueProps) {
  const titleId = useId();
  const fileId = useId();
  const languageId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [language, setLanguage] = useState<LanguageHint>("auto");
  // On by default, unlike a take: the original is something you come back to on other days.
  const [keep, setKeep] = useState(true);

  const choose = (chosen: File | null) => {
    setFileError(null);
    if (!chosen || !options) {
      setFile(null);
      return;
    }
    const check = validateAudioFile(chosen, options.limits);
    if (!check.ok) {
      setFile(null);
      setFileError(check.message);
      return;
    }
    setFile(chosen);
  };

  const add = () => {
    if (!file || busy) return;
    const started = store.submit({
      audio: file,
      filename: file.name,
      profile: "custom",
      language,
      retainAudio: keep,
      role: "reference",
      title: title.trim() || undefined,
      // Lets the original be played in this session even if it is not kept.
      previewUrl: URL.createObjectURL(file),
    });
    if (!started) return;
    setTitle("");
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
  };

  return (
    <details open={initiallyOpen} className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
        Add a monologue
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        <p className={`text-sm ${MUTED}`}>
          Add the original recording of the monologue: the performance you want to practise
          against. Use only a recording you have the right to use. It is analysed on this
          computer and is never sent anywhere. The app measures its pauses and pace; it does
          not copy or imitate the voice.
        </p>
        <div>
          <label htmlFor={titleId} className="block text-sm font-medium">
            Name <span className={`font-normal ${MUTED}`}>(optional)</span>
          </label>
          <input
            id={titleId}
            type="text"
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="For example: The one who knocks, original"
            className={`mt-1 block min-h-11 w-full max-w-xl rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
          />
        </div>
        <div>
          <label htmlFor={fileId} className="block text-sm font-medium">
            The original recording (an audio file)
          </label>
          <input
            ref={fileInput}
            id={fileId}
            type="file"
            accept={options ? acceptAttribute(options.limits) : "audio/*"}
            disabled={!options}
            onChange={(event) => choose(event.target.files?.[0] ?? null)}
            className={`mt-1 block w-full max-w-xl text-sm file:mr-3 file:min-h-11 file:rounded-md file:border file:border-zinc-300 file:bg-white file:px-3 file:text-sm file:font-medium dark:file:border-zinc-700 dark:file:bg-zinc-900 ${FOCUS_RING}`}
          />
          {file && (
            <p className={`mt-1 text-sm ${MUTED}`}>
              {file.name} · {formatBytes(file.size)}
            </p>
          )}
          {fileError && (
            <p role="alert" className="mt-1 text-sm text-red-800 dark:text-red-300">
              {fileError}
            </p>
          )}
          {options && (
            <p className={`mt-1 text-xs ${MUTED}`}>
              Up to {formatBytes(options.limits.maxUploadBytes)} and{" "}
              {Math.round(options.limits.maxAudioSeconds / 60)} minutes.
            </p>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor={languageId} className="block text-sm font-medium">
              Language spoken
            </label>
            <select
              id={languageId}
              value={language}
              onChange={(event) => setLanguage(event.target.value as LanguageHint)}
              className={`mt-1 block min-h-11 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
            >
              {(options?.languages ?? [{ id: "auto" as const, label: "Detect automatically" }]).map(
                (item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ),
              )}
            </select>
          </div>
          <label className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={keep}
              onChange={(event) => setKeep(event.target.checked)}
              className={`mt-0.5 h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
            />
            <span>
              Keep this recording on this device
              <span className={`block text-xs ${MUTED}`}>
                On: it can be replayed and listened to side by side with your takes on any day,
                until you delete it. Off: only its measurements are saved, and it can be played
                only until this page is closed.
              </span>
            </span>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" disabled={!file || busy} onClick={add}>
            Add monologue
          </Button>
          <p className={`text-sm ${MUTED}`}>
            {busy
              ? "Wait for the run in progress to finish."
              : file
                ? "It is measured like a take, which takes roughly a quarter of its length."
                : "Choose a file first."}
          </p>
        </div>
      </div>
    </details>
  );
}
