"use client";

import Link from "next/link";
import { useId, useRef, useState } from "react";

import { Button } from "@/components/Button";

import { audioSourceFor } from "../coaching";
import { formatDateTime, formatSpan } from "../format";
import type { LanguageHint } from "../types";
import {
  generalApi,
  useBackendHealth,
  useFeedback,
  useGeneralStore,
  useRecorder,
} from "../useGeneralPractice";
import { validateAudioFile } from "../validation";
import { BackendNotice } from "./BackendNotice";
import { FOCUS_RING, MUTED, Notice } from "./parts";
import { ReferenceComparison } from "./ReferenceComparison";
import { ReferenceLibrary } from "./ReferenceLibrary";
import { Results } from "./Results";
import { RunPanel } from "./RunPanel";
import { AudioPicker, OptionsRow, type AudioSource, type ChosenFile } from "./SetupForm";

function recordingFilename(extension: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `take-${stamp}${extension}`;
}

/**
 * Practising one monologue against its original: add the reference recording once, study
 * it, then record takes and see where each differs from it.
 */
export function MonologuePractice() {
  const { state, store } = useGeneralStore();
  const { state: recorderState, recorder } = useRecorder();
  const { health, refresh: refreshHealth } = useBackendHealth();
  // Only the calibration is needed here: feedback itself is given in General Practice.
  const { state: feedbackState } = useFeedback(null);
  const calibration =
    feedbackState.calibration.status === "ready" ? feedbackState.calibration.data : null;
  const takeSelectId = useId();

  const [language, setLanguage] = useState<LanguageHint>("auto");
  const [retainAudio, setRetainAudio] = useState(false);
  const [source, setSource] = useState<AudioSource>("record");
  const [chosenFile, setChosenFile] = useState<ChosenFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  // Addresses of audio that an analysis now depends on: these must not be released.
  const submittedUrls = useRef(new Set<string>());

  const options = state.options.status === "ready" ? state.options.data : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);
  const reference = state.references.items.find(
    (item) => item.analysisId === state.selectedReferenceId,
  );
  const referenceDetail =
    state.referenceDetail.status === "ready" ? state.referenceDetail.analysis : null;
  // Only one of your own takes is set against the reference.
  const take =
    state.viewed.status === "ready" && state.viewed.analysis.role === "take"
      ? state.viewed.analysis
      : null;

  const release = (url: string | null | undefined) => {
    if (url && !submittedUrls.current.has(url)) URL.revokeObjectURL(url);
  };

  const chooseFile = (file: File | null) => {
    release(chosenFile?.url);
    setFileError(null);
    if (!file || !options) {
      setChosenFile(null);
      return;
    }
    const check = validateAudioFile(file, options.limits);
    if (!check.ok) {
      setChosenFile(null);
      setFileError(check.message);
      return;
    }
    setChosenFile({ file, url: URL.createObjectURL(file) });
  };

  const discardRecording = () => {
    if (recorderState.status === "recorded") release(recorderState.recording.url);
    recorder.discard();
  };

  const audio =
    source === "record"
      ? recorderState.status === "recorded"
        ? {
            blob: recorderState.recording.blob,
            filename: recordingFilename(recorderState.recording.extension),
            url: recorderState.recording.url,
          }
        : null
      : chosenFile
        ? { blob: chosenFile.file, filename: chosenFile.file.name, url: chosenFile.url }
        : null;

  const analyse = () => {
    if (!audio || busy) return;
    if (audio.url) submittedUrls.current.add(audio.url);
    store.submit({
      audio: audio.blob,
      filename: audio.filename,
      // This screen is about matching the reference, not a delivery profile.
      profile: "custom",
      language,
      retainAudio,
      previewUrl: audio.url,
    });
  };

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Monologue</h1>
        <p className="mt-2 text-zinc-700 dark:text-zinc-300">
          Practise one monologue against its original. Add the reference recording once and
          study how it is delivered. Then record your own take and see where the two differ,
          pause by pause and phrase by phrase, with both versions to listen to.
        </p>
        <p className={`mt-1 text-sm ${MUTED}`}>
          Both recordings are analysed on this computer and never leave it. The app compares
          timing and delivery; it does not copy or imitate anyone&rsquo;s voice.
        </p>
      </header>

      <BackendNotice health={health} onCheckAgain={refreshHealth} />

      {state.notice && (
        <Notice
          kind={state.notice.kind}
          action={<Button onClick={() => store.dismissNotice()}>Dismiss</Button>}
        >
          {state.notice.text}
        </Notice>
      )}

      {/* --- 1. The reference ----------------------------------------------------------- */}
      <section aria-labelledby="reference-step" className="flex flex-col gap-3">
        <h2 id="reference-step" className="text-lg font-semibold">
          1. The reference recording
        </h2>
        <ReferenceLibrary
          state={state}
          store={store}
          options={options}
          busy={busy}
          calibration={calibration}
        />

        {state.referenceDetail.status === "loading" && (
          <p className={`text-sm ${MUTED}`}>Loading the reference…</p>
        )}
        {state.referenceDetail.status === "error" && (
          <Notice kind="error">
            The reference could not be opened. {state.referenceDetail.message}
          </Notice>
        )}
        {referenceDetail && (
          <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
              Study this reference: its pauses, pace, loudness and pitch
            </summary>
            <div className="mt-4">
              <Results
                key={referenceDetail.analysisId}
                mode="reference"
                analysis={referenceDetail}
                profile={undefined}
                history={[]}
                audioSrc={audioSourceFor(referenceDetail, state.localAudio, generalApi)}
                coach={null}
                busy={busy}
                regeneration={{ status: "idle" }}
                onRegenerateCoaching={() => {}}
                onClose={() => {}}
                onDelete={() => {}}
                onDeleteAudio={() => store.deleteAudio(referenceDetail.analysisId)}
              />
            </div>
          </details>
        )}
      </section>

      {/* --- 2. Your take --------------------------------------------------------------- */}
      {state.options.status === "loading" && <p className={MUTED}>Loading…</p>}
      {state.options.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.loadOptions()}>Try again</Button>}>
          The form could not be loaded. {state.options.message}
        </Notice>
      )}
      {options && (
        <div className="flex flex-col gap-6">
          <AudioPicker
            title="2. Your take"
            limits={options.limits}
            source={source}
            onSourceChange={setSource}
            recorderState={recorderState}
            recorder={recorder}
            onDiscardRecording={discardRecording}
            chosenFile={chosenFile}
            fileError={fileError}
            onFileChosen={chooseFile}
          />
          <OptionsRow
            options={options}
            language={language}
            onLanguageChange={setLanguage}
            retainAudio={retainAudio}
            onRetainAudioChange={setRetainAudio}
          />
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" disabled={!audio || busy} onClick={analyse}>
              Analyse and compare
            </Button>
            <p className={`text-sm ${MUTED}`}>
              {busy
                ? "A run is already in progress."
                : !audio
                  ? source === "record"
                    ? "Record something first."
                    : "Choose a file first."
                  : reference
                    ? `It will be compared with “${reference.title ?? "the reference"}”.`
                    : "No reference is chosen, so it will be measured but not compared."}
            </p>
          </div>
        </div>
      )}

      <RunPanel
        run={state.run}
        kind={state.runKind}
        role={state.runRole}
        coachingFor={state.coachingFor}
        again={state.reanalysisFor !== null}
        store={store}
      />

      {/* --- 3. The comparison ---------------------------------------------------------- */}
      <section aria-labelledby="comparison-step" className="flex flex-col gap-3">
        <h2 id="comparison-step" className="text-lg font-semibold">
          3. Your take against the reference
        </h2>

        {state.history.items.length > 0 && (
          <div>
            <label htmlFor={takeSelectId} className="block text-sm font-medium">
              Take
            </label>
            <select
              id={takeSelectId}
              value={take?.analysisId ?? ""}
              onChange={(event) =>
                event.target.value ? store.openAnalysis(event.target.value) : store.closeAnalysis()
              }
              className={`mt-1 block min-h-11 w-full max-w-xl rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
            >
              <option value="">Choose a take</option>
              {state.history.items.map((item) => (
                <option key={item.analysisId} value={item.analysisId}>
                  {formatDateTime(item.createdAt)} · {formatSpan(item.durationSeconds)}
                  {item.originalFilename ? ` · ${item.originalFilename}` : ""}
                  {/* Several results can come from one recording: say which this is. */}
                  {item.revision > 1 ? ` · revision ${item.revision}` : ""}
                </option>
              ))}
            </select>
          </div>
        )}

        {state.viewed.status === "loading" && <p className={`text-sm ${MUTED}`}>Loading that take…</p>}
        {state.viewed.status === "error" && (
          <Notice kind="error">That take could not be opened. {state.viewed.message}</Notice>
        )}

        {!reference && (
          <p className={`text-sm ${MUTED}`}>Choose or add a reference recording in step 1.</p>
        )}
        {reference && !take && state.viewed.status !== "loading" && (
          <p className={`text-sm ${MUTED}`}>
            {state.history.items.length > 0
              ? "Choose a take above, or record a new one in step 2."
              : "Record or upload a take in step 2."}
          </p>
        )}
        {reference && take && (
          <>
            <ReferenceComparison
              // Fresh players and a closed waveform for each pair of recordings.
              key={`${take.analysisId}-${reference.analysisId}`}
              comparison={state.comparison}
              reference={reference}
              takeId={take.analysisId}
              takeAudioSrc={audioSourceFor(take, state.localAudio, generalApi)}
              referenceAudioSrc={audioSourceFor(reference, state.localAudio, generalApi)}
              waveforms={state.waveforms}
              onLoadWaveform={(analysisId) => store.loadWaveform(analysisId)}
            />
            <p className="text-sm">
              <Link
                href={`/general?analysis=${encodeURIComponent(take.analysisId)}`}
                className={`rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS_RING}`}
              >
                See this take&rsquo;s full measurements and coaching, and give feedback on them,
                in General Practice
              </Link>
            </p>
          </>
        )}
      </section>
    </div>
  );
}
