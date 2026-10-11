"use client";

import { useId, useRef, useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";

import { madeWithOlderSettings } from "../feedback";
import { formatBytes, formatDateTime, formatSpan } from "../format";
import type { GeneralState, GeneralStore } from "../generalStore";
import type { AnalysisOptions, Calibration, LanguageHint } from "../types";
import { acceptAttribute, validateAudioFile } from "../validation";
import { FOCUS_RING, LinkButton, MUTED, Notice } from "./parts";

type ReferenceLibraryProps = {
  state: Pick<GeneralState, "references" | "selectedReferenceId">;
  store: GeneralStore;
  /** Upload limits and language choices. Null until they have loaded. */
  options: AnalysisOptions | null;
  /** True while an analysis is in progress, when another cannot be started. */
  busy: boolean;
  /** The settings in force now, to tell when a reference was measured with older ones. */
  calibration?: Calibration | null;
};

/**
 * The reference recordings: choose the one to compare takes with, add one, delete one.
 *
 * A reference is a recording you supply, such as the original performance. It is measured
 * on this computer exactly like one of your own takes.
 */
export function ReferenceLibrary({
  state,
  store,
  options,
  busy,
  calibration = null,
}: ReferenceLibraryProps) {
  const selectId = useId();
  const { references, selectedReferenceId } = state;
  const selected = references.items.find((item) => item.analysisId === selectedReferenceId);
  const [confirming, setConfirming] = useState(false);
  const outdated = selected
    ? madeWithOlderSettings({ settings: selected.settings ?? {} }, calibration)
    : null;

  return (
    <div className="flex flex-col gap-3">
      {references.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.refreshReferences()}>Try again</Button>}>
          The reference recordings could not be loaded. {references.message}
        </Notice>
      )}

      {references.items.length > 0 && (
        <div>
          <label htmlFor={selectId} className="block text-sm font-medium">
            Compare with
          </label>
          <select
            id={selectId}
            value={selectedReferenceId ?? ""}
            onChange={(event) => store.selectReference(event.target.value || null)}
            className={`mt-1 block min-h-11 w-full max-w-xl rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
          >
            <option value="">No reference</option>
            {references.items.map((item) => (
              <option key={item.analysisId} value={item.analysisId}>
                {item.title ?? "Reference"} · {formatSpan(item.durationSeconds)} · added{" "}
                {formatDateTime(item.createdAt)}
                {item.revision > 1 ? ` · revision ${item.revision}` : ""}
              </option>
            ))}
          </select>
          {selected && (
            <p className={`mt-1 text-sm ${MUTED}`}>
              {selected.audioRetained
                ? "Its recording is stored on this device, so it can be played."
                : "Its recording was not kept: it can be compared with, but not played."}{" "}
              <LinkButton onClick={() => setConfirming(true)}>Delete this reference</LinkButton>
            </p>
          )}
          {selected && outdated && (
            <Notice kind="info">
              <p>
                This reference was measured when a silence counted as a pause from{" "}
                {outdated.then} ms. Your feedback has since moved that to {outdated.now} ms, so
                takes analysed now are cut differently from it.
              </p>
              {selected.audioRetained ? (
                <div className="mt-2">
                  <Button
                    disabled={busy}
                    onClick={() => store.reanalyse(selected.analysisId, "reference")}
                  >
                    Measure this reference again
                  </Button>
                  <p className={`mt-1 ${MUTED}`}>
                    That adds it again as a new revision, measured with the settings as they are
                    now. The earlier one stays until you delete it.
                  </p>
                </div>
              ) : (
                <p className={`mt-1 ${MUTED}`}>
                  Its recording was not kept, so it cannot be measured again. Add the recording
                  again to measure it with the settings as they are now.
                </p>
              )}
            </Notice>
          )}
        </div>
      )}

      {references.status === "ready" && references.items.length === 0 && (
        <p className="text-sm">
          No reference recording yet. Add the recording you want to compare your takes with.
        </p>
      )}

      <AddReference
        // Starts open when there is nothing to choose from yet.
        key={references.items.length === 0 ? "first" : "more"}
        initiallyOpen={references.status === "ready" && references.items.length === 0}
        store={store}
        options={options}
        busy={busy}
      />

      <ConfirmDialog
        open={confirming}
        title="Delete this reference?"
        description="Its measurements and its stored recording are deleted from this device. Your own takes are not affected. This cannot be undone."
        confirmLabel="Delete reference"
        onConfirm={() => {
          if (selected) store.deleteReference(selected.analysisId);
          setConfirming(false);
        }}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}

type AddReferenceProps = Pick<ReferenceLibraryProps, "store" | "options" | "busy"> & {
  initiallyOpen: boolean;
};

function AddReference({ store, options, busy, initiallyOpen }: AddReferenceProps) {
  const titleId = useId();
  const fileId = useId();
  const languageId = useId();
  const fileInput = useRef<HTMLInputElement>(null);
  const [title, setTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [language, setLanguage] = useState<LanguageHint>("auto");
  // On by default, unlike a take: a reference is something you come back to on other days.
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
      // Lets the reference be played in this session even if it is not kept.
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
        Add a reference recording
      </summary>
      <div className="mt-3 flex flex-col gap-3">
        <p className={`text-sm ${MUTED}`}>
          For example the original performance of the monologue. Use only a recording you have
          the right to use. It is analysed on this computer and is never sent anywhere. The app
          measures its pauses and pace; it does not copy or imitate the voice.
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
            Audio file
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
            Add reference
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
