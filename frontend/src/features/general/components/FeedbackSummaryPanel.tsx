"use client";

import { Button } from "@/components/Button";

import { COACH_STATUS_TEXT, coachHelp } from "../coaching";
import { summaryHint } from "../feedback";
import type { FeedbackStore, SummaryState } from "../feedbackStore";
import { formatDateTime, formatSpan } from "../format";
import type { CoachStatus, NotePick, SummaryNote } from "../types";
import { Command, FOCUS_RING, MUTED, Notice } from "./parts";

type FeedbackSummaryPanelProps = {
  summary: SummaryState;
  store: FeedbackStore;
  /** Whether the local AI model is available, as the worker last reported. Null if unknown. */
  coach: { status: CoachStatus; model: string | null } | null;
};

function NoteList({ notes, label }: { notes: SummaryNote[]; label: string }) {
  return (
    <ul aria-label={label} className="flex flex-col gap-1 text-sm">
      {notes.map((note, index) => (
        // Two notes can say the same thing, so the position is part of the key.
        <li key={`${index}-${note.text}`}>
          “{note.text}”<span className={`block text-xs ${MUTED}`}>On {note.about}</span>
        </li>
      ))}
    </ul>
  );
}

/** The few notes the AI model picked out, exactly as they were written. */
function Picked({ picked }: { picked: NotePick }) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <p className="text-sm font-medium">The most telling, as picked by the AI model</p>
      {picked.stale && (
        <p className="mt-1 text-sm font-medium text-amber-900 dark:text-amber-200">
          Out of date: your notes have changed since these were picked.
        </p>
      )}
      <div className="mt-2">
        <NoteList notes={picked.notes} label="Notes picked by the AI model" />
      </div>
      <p className={`mt-2 text-xs ${MUTED}`}>
        Picked from {picked.noteCount} notes by the AI model{" "}
        <span className="font-medium">{picked.model}</span>, running on this computer, on{" "}
        {formatDateTime(picked.generatedAt)}
        {picked.modelSeconds !== null && ` in ${formatSpan(picked.modelSeconds)}`}. The model
        only chose: every word above is yours, and no setting is changed by its choice.
      </p>
    </div>
  );
}

/**
 * What all the feedback given so far adds up to. The counts are worked out by the app and
 * are always current. The notes are listed as written; picking out the most telling of
 * them is optional and asked of the AI model by hand.
 */
export function FeedbackSummaryPanel({ summary, store, coach }: FeedbackSummaryPanelProps) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="font-semibold">What your feedback adds up to</h3>
      {(summary.status === "idle" || summary.status === "loading") && (
        <p className={`text-sm ${MUTED}`}>Counting your feedback…</p>
      )}
      {summary.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.loadSummary()}>Try again</Button>}>
          Your feedback could not be counted. {summary.message}
        </Notice>
      )}
      {summary.status === "ready" && <Ready summary={summary} store={store} coach={coach} />}
    </div>
  );
}

function Ready({
  summary,
  store,
  coach,
}: FeedbackSummaryPanelProps & { summary: Extract<SummaryState, { status: "ready" }> }) {
  const { data, asking, error } = summary;
  if (data.feedbackCount === 0) {
    return (
      <p className={`text-sm ${MUTED}`}>
        No feedback yet. Once you have given some, it is counted up here.
      </p>
    );
  }
  const job = data.job;
  const working = job !== null && (job.status === "queued" || job.status === "running");
  const failed = job?.status === "failed" ? job.error : null;
  const help = failed ? coachHelp(failed.code, coach?.model ?? null) : null;
  const unavailable =
    coach && coach.status !== "ready" && coach.status !== "unknown" ? coach.status : null;
  const tooFew = data.pickableNotes < data.minNotes;
  const older = data.noteCount - data.notes.length;
  const hint = summaryHint({
    working,
    queued: job?.status === "queued",
    workerAlive: job?.workerAlive ?? true,
    cancelRequested: job?.cancelRequested ?? false,
    pickableNotes: data.pickableNotes,
    minNotes: data.minNotes,
    unavailable: unavailable ? COACH_STATUS_TEXT[unavailable] : null,
  });

  return (
    <>
      <ul aria-label="What your feedback adds up to" className="list-disc space-y-1 pl-5 text-sm">
        {data.facts.map((fact) => (
          <li key={fact.id}>{fact.text}</li>
        ))}
      </ul>
      <p className={`text-xs ${MUTED}`}>
        Counted by the app from your stored feedback, so it is always up to date. The AI model
        has no part in these lines.
      </p>

      {data.notes.length > 0 && (
        <>
          {data.picked && <Picked picked={data.picked} />}

          {failed && (
            <Notice kind="error">
              <p>The AI model did not pick any notes. {failed.message}</p>
              {help && (
                <p className="mt-1">
                  {help.text}
                  {help.command && <Command>{help.command}</Command>}
                </p>
              )}
            </Notice>
          )}
          {error && <Notice kind="error">{error}</Notice>}

          <div className="flex flex-wrap items-center gap-3">
            {working ? (
              <Button disabled={asking || !job.canCancel} onClick={() => store.cancelSummary()}>
                Stop
              </Button>
            ) : (
              <Button
                disabled={asking || tooFew || unavailable !== null}
                onClick={() => store.askForSummary()}
              >
                {failed
                  ? "Try again"
                  : data.picked
                    ? "Ask the AI model to pick again"
                    : "Ask the AI model to pick out the most telling notes"}
              </Button>
            )}
            <p role="status" className={`min-w-0 flex-1 text-sm ${MUTED}`}>
              {hint}
            </p>
          </div>

          <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
              Your notes, as you wrote them ({data.notes.length}
              {older > 0 ? ` most recent of ${data.noteCount}` : ""})
            </summary>
            <div className="mt-2">
              <NoteList notes={data.notes} label="Your notes, oldest first" />
            </div>
            {older > 0 && (
              <p className={`mt-2 text-xs ${MUTED}`}>
                The {older} older {older === 1 ? "note is" : "notes are"} still on the results
                they were written on.
              </p>
            )}
          </details>
        </>
      )}
    </>
  );
}
