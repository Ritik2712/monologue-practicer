"use client";

import { useId, useState } from "react";

import { Button } from "@/components/Button";

import { describeFeedback, PAUSE_CHOICES, silencesIn, wordBefore } from "../feedback";
import type { FeedbackState, FeedbackStore } from "../feedbackStore";
import { formatNumber, formatTimecode } from "../format";
import type { CorrectionState } from "../generalStore";
import type {
  AnalysisResult,
  FeedbackCategory,
  FeedbackItem,
  PauseEvent,
  SegmentCorrection,
  SpeechSegment,
  WpmReview,
} from "../types";
import { FOCUS_RING, LinkButton, MUTED, Notice } from "./parts";

/** What the feedback controls inside a result need: what is saved, and how to save more. */
export type FeedbackTools = { state: FeedbackState; store: FeedbackStore };

const FIELD = `rounded-md border border-zinc-300 bg-white px-3 text-sm dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`;

/** The one thing said about a detected pause, chosen from a short list. */
export function PauseFeedbackSelect({
  pause,
  item,
  disabled,
  store,
}: {
  pause: PauseEvent;
  item: FeedbackItem | undefined;
  disabled: boolean;
  store: FeedbackStore;
}) {
  const at = formatTimecode(pause.startSeconds);
  return (
    <div className="max-w-xs min-w-[13rem]">
      <select
        aria-label={`Your feedback on the pause at ${at}`}
        value={item?.category ?? ""}
        disabled={disabled}
        onChange={(event) => {
          const category = event.target.value as FeedbackCategory | "";
          if (category) store.give({ category, targetId: pause.id });
          else if (item) store.remove(item.id);
        }}
        className={`block min-h-11 w-full ${FIELD}`}
      >
        <option value="">No feedback</option>
        {PAUSE_CHOICES.map((choice) => (
          <option key={choice.category} value={choice.category}>
            {choice.label}
          </option>
        ))}
      </select>
      {item && <p className={`mt-1 text-xs ${MUTED}`}>{item.message}</p>}
    </div>
  );
}

/** How a WPM figure was arrived at: the arithmetic, then each thing that feeds it. */
export function WpmReviewView({ review }: { review: WpmReview }) {
  return (
    <div className="mt-2 rounded-md border border-zinc-200 p-3 text-sm dark:border-zinc-800">
      <p className="font-medium">How this figure was worked out: {review.target.toLowerCase()}</p>
      <p className="mt-1 tabular-nums">{review.formula}</p>
      <dl className="mt-2 flex flex-col gap-2">
        {review.checks.map((check) => (
          <div key={check.label}>
            <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>{check.label}</dt>
            <dd>{check.text}</dd>
          </div>
        ))}
      </dl>
      <p className={`mt-2 text-xs ${MUTED}`}>
        Nothing here multiplies the WPM by a correction. The figure changes only when the words
        or the speaking time behind it are corrected.
      </p>
    </div>
  );
}

/** One piece of saved feedback: what it is about, what it does, its note, and a way to take it back. */
export function FeedbackEntry({
  item,
  analysis,
  disabled,
  store,
}: {
  item: FeedbackItem;
  analysis: AnalysisResult;
  disabled: boolean;
  store: FeedbackStore;
}) {
  const noteId = useId();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(item.note ?? "");
  const what = describeFeedback(item, analysis);

  const saveNote = () => {
    store.give({
      category: item.category,
      targetId: item.targetId,
      atSeconds: item.atSeconds,
      note: note.trim(),
    });
    setEditing(false);
  };

  return (
    <li className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800">
      <p className="font-medium">{what}</p>
      <p className={`mt-0.5 ${MUTED}`}>{item.message}</p>
      {item.review && <WpmReviewView review={item.review} />}
      {item.note && !editing && <p className="mt-1">Your note: “{item.note}”</p>}
      {editing ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1">
            <label htmlFor={noteId} className="block text-xs font-medium">
              Note <span className={`font-normal ${MUTED}`}>(optional, up to 280 characters)</span>
            </label>
            <input
              id={noteId}
              type="text"
              value={note}
              maxLength={280}
              onChange={(event) => setNote(event.target.value)}
              className={`mt-1 block min-h-11 w-full ${FIELD}`}
            />
          </div>
          <Button onClick={saveNote} disabled={disabled}>
            Save note
          </Button>
          <Button
            onClick={() => {
              setNote(item.note ?? "");
              setEditing(false);
            }}
          >
            Cancel
          </Button>
        </div>
      ) : (
        <div className="mt-1 flex flex-wrap gap-x-3">
          <LinkButton aria-label={`${item.note ? "Edit" : "Add"} a note: ${what}`} onClick={() => setEditing(true)}>
            {item.note ? "Edit note" : "Add a note"}
          </LinkButton>
          <LinkButton
            disabled={disabled}
            aria-label={`Remove this feedback: ${what}`}
            onClick={() => store.remove(item.id)}
          >
            Remove
          </LinkButton>
        </div>
      )}
    </li>
  );
}

type Problem = "pause_missed" | "wpm_too_high" | "wpm_too_low" | "transcript_wrong";

const PROBLEMS: { value: Problem; label: string }[] = [
  { value: "pause_missed", label: "A pause was missed in this phrase: it should be two phrases" },
  { value: "wpm_too_high", label: "Its WPM looks too high" },
  { value: "wpm_too_low", label: "Its WPM looks too low" },
  { value: "transcript_wrong", label: "The words are wrong" },
];

type SegmentReportProps = {
  analysis: AnalysisResult;
  segment: SpeechSegment;
  /** The feedback already saved about this segment. */
  saved: FeedbackItem[];
  tools: FeedbackTools;
  correction: CorrectionState;
  /** Where the player is, if the recording can be played. */
  playheadSeconds: number | null;
  playButton: (label: string, start: number, end?: number) => React.ReactNode;
  onCorrectTranscript: (corrections: SegmentCorrection[]) => void;
  onClose: () => void;
};

/** The form for reporting what the analysis got wrong about one phrase. */
export function SegmentReport({
  analysis,
  segment,
  saved,
  tools,
  correction,
  playheadSeconds,
  playButton,
  onCorrectTranscript,
  onClose,
}: SegmentReportProps) {
  const groupId = useId();
  const wordsId = useId();
  const [problem, setProblem] = useState<Problem>("pause_missed");
  const silences = silencesIn(analysis, segment.id);
  const [spot, setSpot] = useState<string>(silences.length > 0 ? "0" : "unknown");
  const [words, setWords] = useState(segment.transcript ?? "");
  const { state, store } = tools;
  const number = segment.index + 1;

  const playerInside =
    playheadSeconds !== null &&
    playheadSeconds >= segment.startSeconds &&
    playheadSeconds <= segment.endSeconds;
  // A choice that has since become impossible falls back to "cannot say where".
  const chosenSpot = spot === "player" && !playerInside ? "unknown" : spot;
  const sameWords = words.trim().split(/\s+/).join(" ") === (segment.transcript ?? "").trim();
  const savingWords = correction.status === "saving";

  const report = () => {
    if (problem === "pause_missed") {
      const silence = silences[Number(chosenSpot)];
      const atSeconds =
        chosenSpot === "player"
          ? playheadSeconds
          : silence
            ? (silence.startSeconds + silence.endSeconds) / 2
            : null;
      store.give({ category: "pause_missed", targetId: segment.id, atSeconds });
    } else {
      store.give({ category: problem, targetId: segment.id });
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">Report on segment {number}</p>
          <p className={`text-sm ${MUTED}`}>
            {formatTimecode(segment.startSeconds)} – {formatTimecode(segment.endSeconds)}
            {segment.transcript ? `: “${segment.transcript}”` : ""}
          </p>
        </div>
        <Button onClick={onClose}>Close</Button>
      </div>
      <fieldset>
        <legend className="text-sm font-medium">What did the analysis get wrong about this phrase?</legend>
        <div className="mt-1 flex flex-col gap-1">
          {PROBLEMS.map((option) => (
            <label key={option.value} className="flex cursor-pointer items-start gap-2 text-sm">
              <input
                type="radio"
                name={`${groupId}-problem`}
                checked={problem === option.value}
                onChange={() => setProblem(option.value)}
                className={`mt-0.5 h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>

      {problem === "pause_missed" && (
        <fieldset>
          <legend className="text-sm font-medium">Where was the pause?</legend>
          <p className={`text-xs ${MUTED}`}>
            {analysis.shortSilences == null
              ? "This result was made before short silences were kept, so the report cannot be checked against what the detector heard."
              : silences.length > 0
                ? "Listed first are the silences the detector heard inside this phrase that were too short to count as pauses."
                : "The detector heard no silence inside this phrase."}
          </p>
          <div className="mt-1 flex flex-col gap-1">
            {silences.map((silence, index) => {
              const before = wordBefore(analysis, silence.startSeconds);
              const at = formatTimecode(silence.startSeconds);
              return (
                <div key={silence.startSeconds} className="flex flex-wrap items-center gap-x-2">
                  <label className="flex cursor-pointer items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name={`${groupId}-spot`}
                      checked={chosenSpot === String(index)}
                      onChange={() => setSpot(String(index))}
                      className={`h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
                    />
                    <span>
                      At {at}: a silence of {formatNumber(silence.durationSeconds, 2)} s
                      {before ? `, after “${before}”` : ""}
                    </span>
                  </label>
                  {playButton(
                    `Play the silence at ${at} with a little either side`,
                    silence.startSeconds - 1,
                    silence.endSeconds + 1,
                  )}
                </div>
              );
            })}
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name={`${groupId}-spot`}
                checked={chosenSpot === "player"}
                disabled={!playerInside}
                onChange={() => setSpot("player")}
                className={`h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
              />
              <span className={playerInside ? "" : MUTED}>
                {playerInside
                  ? `Where the player is now: ${formatTimecode(playheadSeconds ?? 0)}`
                  : "Where the player is now (move the player to a point inside this phrase first)"}
              </span>
            </label>
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="radio"
                name={`${groupId}-spot`}
                checked={chosenSpot === "unknown"}
                onChange={() => setSpot("unknown")}
                className={`h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
              />
              I cannot say exactly where
            </label>
          </div>
        </fieldset>
      )}

      {(problem === "wpm_too_high" || problem === "wpm_too_low") && (
        <p className={`text-sm ${MUTED}`}>
          No figure is changed by this report. You are shown what went into the WPM, so the
          words or the speaking time can be corrected if one of them is wrong.
        </p>
      )}

      {problem === "transcript_wrong" ? (
        <div className="flex flex-col gap-2">
          <div>
            <label htmlFor={wordsId} className="block text-sm font-medium">
              The words as you said them
            </label>
            <textarea
              id={wordsId}
              value={words}
              rows={3}
              maxLength={4000}
              onChange={(event) => setWords(event.target.value)}
              className={`mt-1 block w-full py-2 ${FIELD}`}
            />
            <p className={`mt-1 text-xs ${MUTED}`}>
              Saving makes a new revision of this result. Its word counts and WPM are worked out
              again from your words and this phrase&rsquo;s own {formatNumber(segment.speechActiveSeconds, 2)}{" "}
              s. The result you are looking at stays in your history, unchanged.
            </p>
          </div>
          {correction.status === "failed" && correction.analysisId === analysis.analysisId && (
            <Notice kind="error">The correction was not saved. {correction.message}</Notice>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="primary"
              disabled={sameWords || savingWords}
              onClick={() => onCorrectTranscript([{ segmentId: segment.id, text: words }])}
            >
              {savingWords ? "Saving…" : "Save corrected words"}
            </Button>
            <Button disabled={state.saving} onClick={report}>
              Only flag it, without correcting
            </Button>
            {sameWords && <p className={`text-sm ${MUTED}`}>Change the words above to correct them.</p>}
          </div>
        </div>
      ) : (
        <div>
          <Button variant="primary" disabled={state.saving} onClick={report}>
            Save this report
          </Button>
        </div>
      )}

      {saved.length > 0 && (
        <div>
          <p className="text-sm font-medium">Saved about this phrase</p>
          <ul className="mt-1 flex flex-col gap-2">
            {saved.map((item) => (
              <FeedbackEntry
                key={item.id}
                item={item}
                analysis={analysis}
                disabled={state.saving}
                store={store}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** "Useful" and "Not useful" for one correction in the coaching. */
export function CorrectionRating({
  findingId,
  title,
  item,
  disabled,
  store,
}: {
  findingId: string;
  title: string;
  item: FeedbackItem | undefined;
  disabled: boolean;
  store: FeedbackStore;
}) {
  const choose = (category: FeedbackCategory) => {
    if (item?.category === category) store.remove(item.id);
    else store.give({ category, targetId: findingId });
  };
  const button = (category: FeedbackCategory, label: string) => {
    const pressed = item?.category === category;
    return (
      <button
        type="button"
        aria-pressed={pressed}
        aria-label={`${label}: ${title}`}
        // Stays focusable while a save is in flight, like the app's other buttons.
        aria-disabled={disabled || undefined}
        onClick={() => {
          if (!disabled) choose(category);
        }}
        className={`min-h-11 rounded-md border px-3 text-sm font-medium ${disabled ? "cursor-not-allowed opacity-60" : ""} ${FOCUS_RING} ${
          pressed
            ? "border-indigo-700 bg-indigo-700 text-white dark:border-indigo-400 dark:bg-indigo-400 dark:text-zinc-950"
            : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        }`}
      >
        {label}
      </button>
    );
  };
  return (
    <div>
      <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>Was this useful?</dt>
      <dd className="mt-1">
        <div className="flex flex-wrap items-center gap-2">
          {button("coaching_useful", "Useful")}
          {button("coaching_not_useful", "Not useful")}
        </div>
        {item && <p className={`mt-1 text-xs ${MUTED}`}>{item.message}</p>}
      </dd>
    </div>
  );
}
