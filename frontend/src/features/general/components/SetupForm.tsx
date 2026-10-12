"use client";

import { Button } from "@/components/Button";

import { resolveUnknownDuration } from "../audioDuration";
import { formatBytes, formatSpan } from "../format";
import type { Recorder, RecorderState } from "../recorder";
import type {
  AnalysisOptions,
  DeliveryProfile,
  LanguageHint,
  Profile,
  UploadLimits,
  VoiceGoal,
} from "../types";
import { acceptAttribute } from "../validation";
import { FOCUS_RING, MUTED, Notice } from "./parts";

export type AudioSource = "record" | "upload";
export type ChosenFile = { file: File; url: string };

// --- Delivery profile --------------------------------------------------------------------

type ProfilePickerProps = {
  options: AnalysisOptions;
  value: Profile;
  onChange: (profile: Profile) => void;
};

export function ProfilePicker({ options, value, onChange }: ProfilePickerProps) {
  const selected = options.profiles.find((profile) => profile.id === value);
  return (
    <fieldset>
      <legend className="text-lg font-semibold">1. Choose a delivery profile</legend>
      <p className={`mt-1 text-sm ${MUTED}`}>{options.profileNote}</p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {options.profiles.map((profile) => (
          <label
            key={profile.id}
            className={`flex cursor-pointer gap-3 rounded-lg border p-3 has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-indigo-600 dark:has-focus-visible:outline-indigo-400 ${
              profile.id === value
                ? "border-indigo-600 bg-indigo-50 dark:border-indigo-400 dark:bg-indigo-950/40"
                : "border-zinc-200 dark:border-zinc-800"
            }`}
          >
            <input
              type="radio"
              name="delivery-profile"
              value={profile.id}
              checked={profile.id === value}
              onChange={() => onChange(profile.id)}
              className="mt-1 h-4 w-4 shrink-0 accent-indigo-700 outline-none dark:accent-indigo-400"
            />
            <span>
              <span className="font-semibold">{profile.name}</span>
              <span className="mt-0.5 block text-sm text-zinc-700 dark:text-zinc-300">
                {profile.summary}
              </span>
            </span>
          </label>
        ))}
      </div>
      {selected && <ProfileDetails profile={selected} />}
    </fieldset>
  );
}

function ProfileDetails({ profile }: { profile: DeliveryProfile }) {
  if (profile.targets.length === 0) return null;
  return (
    <div className="mt-3 grid gap-4 rounded-lg border border-zinc-200 p-3 text-sm sm:grid-cols-2 dark:border-zinc-800">
      <div>
        <p className="font-medium">The {profile.name} style aims for</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-zinc-700 dark:text-zinc-300">
          {profile.targets.map((target) => (
            <li key={target}>{target}</li>
          ))}
        </ul>
      </div>
      <div>
        <p className="font-medium">Measurements it depends on most</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-zinc-700 dark:text-zinc-300">
          {profile.focus.map((focus) => (
            <li key={focus.metric + focus.label}>
              <span className="font-medium">{focus.label}:</span> {focus.looksFor.toLowerCase()}
            </li>
          ))}
        </ul>
        {profile.notMeasured.length > 0 && (
          <p className={`mt-2 ${MUTED}`}>
            Not measured by this app: {profile.notMeasured.join(", ").toLowerCase()}.
          </p>
        )}
      </div>
    </div>
  );
}

// --- Recording and uploading -------------------------------------------------------------

type AudioPickerProps = {
  /** The heading above the picker. */
  title?: string;
  limits: UploadLimits;
  source: AudioSource;
  onSourceChange: (source: AudioSource) => void;
  recorderState: RecorderState;
  recorder: Recorder;
  onDiscardRecording: () => void;
  chosenFile: ChosenFile | null;
  fileError: string | null;
  onFileChosen: (file: File | null) => void;
};

function formatElapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

export function AudioPicker({
  title = "2. Add your audio",
  limits,
  source,
  onSourceChange,
  recorderState,
  recorder,
  onDiscardRecording,
  chosenFile,
  fileError,
  onFileChosen,
}: AudioPickerProps) {
  const maxMinutes = limits.maxAudioSeconds / 60;
  const tab = (id: AudioSource, label: string) => (
    <button
      type="button"
      aria-pressed={source === id}
      onClick={() => onSourceChange(id)}
      className={`min-h-11 flex-1 rounded-md px-3 text-sm font-medium ${FOCUS_RING} ${
        source === id
          ? "bg-white shadow-sm dark:bg-zinc-700"
          : "text-zinc-700 hover:bg-white/60 dark:text-zinc-300 dark:hover:bg-zinc-700/50"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <div
        role="group"
        aria-label="How to add your audio"
        className="mt-3 flex gap-1 rounded-lg bg-zinc-100 p-1 dark:bg-zinc-800"
      >
        {tab("record", "Record here")}
        {tab("upload", "Upload a file")}
      </div>

      {source === "record" ? (
        <div className="mt-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <RecordPanel
            state={recorderState}
            recorder={recorder}
            maxMs={limits.maxAudioSeconds * 1000}
            maxMinutes={maxMinutes}
            onDiscard={onDiscardRecording}
          />
        </div>
      ) : (
        <div className="mt-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
          <label htmlFor="audio-file" className="block text-sm font-medium">
            Audio file
          </label>
          <input
            id="audio-file"
            type="file"
            accept={acceptAttribute(limits)}
            onChange={(event) => {
              onFileChosen(event.target.files?.[0] ?? null);
              // Clearing lets the same file be chosen again after removing it.
              event.target.value = "";
            }}
            className={`mt-1 block w-full rounded text-sm file:mr-3 file:min-h-11 file:cursor-pointer file:rounded-md file:border file:border-solid file:border-zinc-300 file:bg-white file:px-4 file:text-sm file:font-medium file:text-zinc-900 dark:file:border-zinc-700 dark:file:bg-zinc-900 dark:file:text-zinc-100 ${FOCUS_RING}`}
          />
          <p className={`mt-2 text-sm ${MUTED}`}>
            {limits.acceptedExtensions.map((item) => item.slice(1).toUpperCase()).join(", ")}. Up
            to {formatBytes(limits.maxUploadBytes)} and {maxMinutes} minutes.
          </p>
          {fileError && (
            <div className="mt-3">
              <Notice kind="error">{fileError}</Notice>
            </div>
          )}
          {chosenFile && (
            <div className="mt-3 flex flex-col gap-2">
              <p className="text-sm">
                <span className="font-medium break-all">{chosenFile.file.name}</span>{" "}
                <span className={MUTED}>({formatBytes(chosenFile.file.size)})</span>
              </p>
              <audio
                controls
                src={chosenFile.url}
                className="w-full"
                aria-label="Preview of the chosen file"
                onLoadedMetadata={(event) => resolveUnknownDuration(event.currentTarget)}
              />
              <div>
                <Button onClick={() => onFileChosen(null)}>Remove file</Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

type RecordPanelProps = {
  state: RecorderState;
  recorder: Recorder;
  maxMs: number;
  maxMinutes: number;
  onDiscard: () => void;
};

function RecordPanel({ state, recorder, maxMs, maxMinutes, onDiscard }: RecordPanelProps) {
  switch (state.status) {
    case "idle":
      return (
        <div className="flex flex-col items-start gap-2">
          <Button variant="primary" onClick={() => recorder.start(maxMs)}>
            Start recording
          </Button>
          <p className={`text-sm ${MUTED}`}>
            Your browser will ask to use the microphone. Up to {maxMinutes} minutes.
          </p>
        </div>
      );
    case "requesting":
      return (
        <div className="flex flex-col items-start gap-2">
          <p role="status">Waiting for microphone access. Answer the browser&apos;s prompt.</p>
          <Button onClick={onDiscard}>Cancel</Button>
        </div>
      );
    case "recording":
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="flex items-center gap-2 font-medium">
            <span aria-hidden="true" className="h-3 w-3 rounded-full bg-red-600 motion-safe:animate-pulse" />
            Recording
            <span role="timer" aria-label="Recording time" className="font-mono text-xl tabular-nums">
              {formatElapsed(state.elapsedMs)}
            </span>
            <span className={`text-sm font-normal ${MUTED}`}>of {maxMinutes}:00</span>
          </p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => recorder.stop()}>
              Stop
            </Button>
            <Button onClick={onDiscard}>Discard</Button>
          </div>
        </div>
      );
    case "recorded":
      return (
        <div className="flex flex-col gap-3">
          <p role="status">
            <span className="font-medium">Recorded {formatSpan(state.recording.durationMs / 1000)}</span>{" "}
            <span className={MUTED}>({formatBytes(state.recording.blob.size)})</span>
          </p>
          {state.recording.reachedLimit && (
            <Notice kind="warning">
              Recording stopped by itself at the {maxMinutes}-minute limit.
            </Notice>
          )}
          {state.recording.url && (
            <audio
              controls
              src={state.recording.url}
              className="w-full"
              aria-label="Preview of your new recording"
              // Browser recordings carry no length; this lets the player show one and seek.
              onLoadedMetadata={(event) => resolveUnknownDuration(event.currentTarget)}
              onDurationChange={(event) => resolveUnknownDuration(event.currentTarget)}
            />
          )}
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => recorder.start(maxMs)}>Record again</Button>
            <Button onClick={onDiscard}>Discard</Button>
          </div>
        </div>
      );
    case "error":
      return (
        <div className="flex flex-col items-start gap-3">
          <Notice kind="error">{state.message}</Notice>
          <Button onClick={() => recorder.start(maxMs)}>Try again</Button>
        </div>
      );
  }
}

// --- Language and keeping the recording --------------------------------------------------

type OptionsRowProps = {
  options: AnalysisOptions;
  language: LanguageHint;
  onLanguageChange: (language: LanguageHint) => void;
  retainAudio: boolean;
  onRetainAudioChange: (retain: boolean) => void;
  /** What the speaker is working towards with their voice, and how to change it. */
  voiceGoal: VoiceGoal;
  onVoiceGoalChange: (goal: VoiceGoal) => void;
};

export function OptionsRow({
  options,
  language,
  onLanguageChange,
  retainAudio,
  onRetainAudioChange,
  voiceGoal,
  onVoiceGoalChange,
}: OptionsRowProps) {
  const note = options.languages.find((item) => item.id === language)?.note;
  const goals = options.voiceGoals ?? [];
  const goalNote = goals.find((item) => item.id === voiceGoal)?.note;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {goals.length > 0 && (
        // Last in the row, across its full width: it is the one choice that needs explaining.
        <div className="order-last sm:col-span-2">
          <label htmlFor="voice-goal" className="block text-sm font-medium">
            Voice goal <span className={`font-normal ${MUTED}`}>(optional)</span>
          </label>
          <select
            id="voice-goal"
            value={voiceGoal}
            onChange={(event) => onVoiceGoalChange(event.target.value as VoiceGoal)}
            className={`mt-1 block min-h-11 w-full max-w-xl rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
          >
            {goals.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
          <p className={`mt-1 text-sm ${MUTED}`}>
            {goalNote ? `${goalNote} ` : ""}
            {options.voiceGoalNote}
          </p>
        </div>
      )}
      <div>
        <label htmlFor="spoken-language" className="block text-sm font-medium">
          Language spoken
        </label>
        <select
          id="spoken-language"
          value={language}
          onChange={(event) => onLanguageChange(event.target.value as LanguageHint)}
          className={`mt-1 block min-h-11 w-full rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
        >
          {options.languages.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        {note && <p className={`mt-1 text-sm ${MUTED}`}>{note}</p>}
      </div>
      <div>
        <label className="flex cursor-pointer items-start gap-3">
          <input
            type="checkbox"
            checked={retainAudio}
            onChange={(event) => onRetainAudioChange(event.target.checked)}
            className={`mt-0.5 h-5 w-5 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
          />
          <span className="text-sm">
            <span className="font-medium">Keep this recording on this device</span>
            <span className={`mt-0.5 block ${MUTED}`}>
              Off: the audio is deleted as soon as it has been analysed and only the measurements
              are saved. On: the audio is stored too, so you can replay it later and delete it when
              you choose.
            </span>
          </span>
        </label>
      </div>
    </div>
  );
}
