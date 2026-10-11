"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";

import { audioSourceFor, regenerationState } from "../coaching";
import type { LanguageHint, Profile } from "../types";
import {
  generalApi,
  useBackendHealth,
  useGeneralStore,
  useRecorder,
} from "../useGeneralPractice";
import { validateAudioFile } from "../validation";
import { BackendNotice } from "./BackendNotice";
import { HistoryPanel } from "./HistoryPanel";
import { MUTED, Notice, Section } from "./parts";
import { ReferenceComparison } from "./ReferenceComparison";
import { ReferenceLibrary } from "./ReferenceLibrary";
import { Results } from "./Results";
import { RunPanel } from "./RunPanel";
import {
  AudioPicker,
  OptionsRow,
  ProfilePicker,
  type AudioSource,
  type ChosenFile,
} from "./SetupForm";

type Confirmation =
  | { kind: "delete_analysis"; analysisId: string }
  | { kind: "delete_audio"; analysisId: string }
  | { kind: "clear_history" };

const CONFIRM_TEXT: Record<Confirmation["kind"], { title: string; description: string; confirmLabel: string }> = {
  delete_analysis: {
    title: "Delete this analysis?",
    description:
      "Its measurements and, if it was kept, its recording are deleted from this device. This cannot be undone.",
    confirmLabel: "Delete analysis",
  },
  delete_audio: {
    title: "Delete this recording?",
    description:
      "Only the audio is deleted. The measurements stay in your history, but the recording can no longer be played back. This cannot be undone.",
    confirmLabel: "Delete recording",
  },
  clear_history: {
    title: "Clear all history?",
    description:
      "Every saved analysis of your own takes, and every recording kept with them, is deleted from this device. Your reference recordings are not affected, nor is an analysis still in progress or the Daily Practice checklist. This cannot be undone.",
    confirmLabel: "Clear all history",
  },
};

function recordingFilename(extension: string): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  const stamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
  return `recording-${stamp}${extension}`;
}

export function GeneralPractice() {
  const { state, store } = useGeneralStore();
  const { state: recorderState, recorder } = useRecorder();
  const { health, refresh: refreshHealth } = useBackendHealth();

  const [profile, setProfile] = useState<Profile>("custom");
  const [language, setLanguage] = useState<LanguageHint>("auto");
  const [retainAudio, setRetainAudio] = useState(false);
  const [source, setSource] = useState<AudioSource>("record");
  const [chosenFile, setChosenFile] = useState<ChosenFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [lastConfirmation, setLastConfirmation] = useState<Confirmation["kind"]>("clear_history");
  // Addresses of audio that an analysis now depends on: these must not be released.
  const submittedUrls = useRef(new Set<string>());

  const options = state.options.status === "ready" ? state.options.data : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);

  // A link such as /general?analysis=<id>, as the Monologue screen gives, opens that result.
  useEffect(() => {
    const analysisId = new URLSearchParams(window.location.search).get("analysis");
    if (analysisId) store.openAnalysis(analysisId);
  }, [store]);

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
      profile,
      language,
      retainAudio,
      previewUrl: audio.url,
    });
  };

  const ask = (next: Confirmation) => {
    setLastConfirmation(next.kind);
    setConfirmation(next);
  };
  const confirm = () => {
    if (confirmation?.kind === "delete_analysis") store.deleteAnalysis(confirmation.analysisId);
    if (confirmation?.kind === "delete_audio") store.deleteAudio(confirmation.analysisId);
    if (confirmation?.kind === "clear_history") store.clearHistory();
    setConfirmation(null);
  };

  const viewed = state.viewed;
  const viewedAnalysis = viewed.status === "ready" ? viewed.analysis : null;
  const audioSrc = viewedAnalysis ? audioSourceFor(viewedAnalysis, state.localAudio, generalApi) : null;
  const chosenReference = state.references.items.find(
    (item) => item.analysisId === state.selectedReferenceId,
  );

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">General Practice</h1>
        <p className="mt-2 text-zinc-700 dark:text-zinc-300">
          Record yourself or upload a recording, and see how you spoke: pace, pauses, loudness and
          pitch, phrase by phrase, with coaching on what to change for the next take. Hindi,
          English and Hinglish.
        </p>
        <p className={`mt-1 text-sm ${MUTED}`}>
          Everything is analysed on this computer, including the AI coaching. Your audio and your
          words are never sent anywhere else.
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

      {state.options.status === "loading" && <p className={MUTED}>Loading…</p>}
      {state.options.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.loadOptions()}>Try again</Button>}>
          The form could not be loaded. {state.options.message}
        </Notice>
      )}

      {options && (
        <div className="flex flex-col gap-6">
          <ProfilePicker options={options} value={profile} onChange={setProfile} />
          <AudioPicker
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
              Analyse recording
            </Button>
            <p className={`text-sm ${MUTED}`}>
              {busy
                ? "An analysis is already in progress."
                : audio
                  ? "Measuring takes roughly a quarter of the recording's length; the AI coaching adds about half a minute."
                  : source === "record"
                    ? "Record something first."
                    : "Choose a file first."}
            </p>
          </div>
        </div>
      )}

      <RunPanel
        run={state.run}
        kind={state.runKind}
        role={state.runRole}
        coachingFor={state.coachingFor}
        store={store}
      />

      {viewed.status === "loading" && <p className={MUTED}>Loading that analysis…</p>}
      {viewed.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.closeAnalysis()}>Dismiss</Button>}>
          That analysis could not be opened. {viewed.message}
        </Notice>
      )}
      {viewedAnalysis && (
        <Results
          // A fresh component per analysis, so playback and choices do not carry over.
          key={viewedAnalysis.analysisId}
          analysis={viewedAnalysis}
          profile={options?.profiles.find((item) => item.id === viewedAnalysis.profile)}
          history={state.history.items}
          audioSrc={audioSrc}
          referenceSection={
            <Section
              id="reference-heading"
              title="Compare with a reference recording"
              description="Set this take against a recording you supply, such as the original performance: where each of you pauses, and how fast each phrase is said. This is a measured comparison of two real recordings, separate from the delivery profile above."
            >
              <ReferenceLibrary state={state} store={store} options={options} busy={busy} />
              {chosenReference && (
                <ReferenceComparison
                  // Fresh players and a closed waveform for each pair of recordings.
                  key={`${viewedAnalysis.analysisId}-${chosenReference.analysisId}`}
                  comparison={state.comparison}
                  reference={chosenReference}
                  takeId={viewedAnalysis.analysisId}
                  takeAudioSrc={audioSrc}
                  referenceAudioSrc={audioSourceFor(chosenReference, state.localAudio, generalApi)}
                  waveforms={state.waveforms}
                  onLoadWaveform={(analysisId) => store.loadWaveform(analysisId)}
                />
              )}
            </Section>
          }
          coach={
            health.status === "reachable"
              ? { status: health.health.coach, model: health.health.coachModel }
              : null
          }
          busy={busy}
          regeneration={regenerationState(state, viewedAnalysis.analysisId)}
          onRegenerateCoaching={() => store.regenerateCoaching(viewedAnalysis.analysisId)}
          onClose={() => store.closeAnalysis()}
          onDelete={() => ask({ kind: "delete_analysis", analysisId: viewedAnalysis.analysisId })}
          onDeleteAudio={() => ask({ kind: "delete_audio", analysisId: viewedAnalysis.analysisId })}
        />
      )}

      <HistoryPanel
        history={state.history}
        viewedId={viewedAnalysis?.analysisId ?? null}
        onOpen={(analysisId) => store.openAnalysis(analysisId)}
        onDelete={(analysisId) => ask({ kind: "delete_analysis", analysisId })}
        onDeleteAudio={(analysisId) => ask({ kind: "delete_audio", analysisId })}
        onClear={() => ask({ kind: "clear_history" })}
        onRetry={() => store.refreshHistory()}
      />

      <ConfirmDialog
        open={confirmation !== null}
        {...CONFIRM_TEXT[confirmation?.kind ?? lastConfirmation]}
        onConfirm={confirm}
        onCancel={() => setConfirmation(null)}
      />
    </div>
  );
}
