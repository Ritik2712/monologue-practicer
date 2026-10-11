"use client";

import { Button } from "@/components/Button";

import { coachHelp } from "../coaching";
import { STAGE_LABELS } from "../format";
import type { GeneralStore, RunState } from "../generalStore";
import type { JobKind, JobStage, Role } from "../types";
import { Command, MUTED, Notice } from "./parts";

const ALL_STAGES = Object.keys(STAGE_LABELS) as JobStage[];

/**
 * The steps shown for a job. Writing coaching again skips the audio steps, and a reference
 * recording gets no coaching.
 */
function stagesFor(kind: JobKind, role: Role): JobStage[] {
  if (kind === "coaching") return ["generating_feedback"];
  return role === "reference"
    ? ALL_STAGES.filter((stage) => stage !== "generating_feedback")
    : ALL_STAGES;
}

type RunPanelProps = {
  run: RunState;
  /** Analysing a recording, or only writing an analysis's coaching again. */
  kind: JobKind;
  /** Whether the recording is one of your takes or a reference. */
  role: Role;
  /** The analysis whose coaching is being written again. */
  coachingFor: string | null;
  store: GeneralStore;
};

/** What is happening to the recording that was just submitted, or to its coaching. */
export function RunPanel({ run, kind, role, coachingFor, store }: RunPanelProps) {
  if (run.phase === "idle") return null;

  return (
    <section
      aria-labelledby="run-heading"
      aria-live="polite"
      className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <h2 id="run-heading" className="text-lg font-semibold">
        {HEADINGS[run.phase](run, kind, role)}
      </h2>
      <div className="mt-2 flex flex-col gap-3">
        <RunBody run={run} kind={kind} role={role} coachingFor={coachingFor} store={store} />
      </div>
    </section>
  );
}

type Heading = (run: RunState, kind: JobKind, role: Role) => string;

const HEADINGS: { [Phase in RunState["phase"]]: Heading } = {
  idle: () => "",
  submitting: (_, kind) =>
    kind === "coaching" ? "Asking for new coaching" : "Sending the recording to the local backend",
  tracking: (run, kind, role) => {
    if (run.phase !== "tracking") return "";
    if (run.job.cancelRequested) return "Cancelling";
    if (run.job.status === "queued") return "Waiting in the queue";
    if (kind === "coaching") return "Writing the coaching again";
    return role === "reference" ? "Measuring the reference recording" : "Analysing your recording";
  },
  loading_result: () => "Loading the result",
  done: (_, kind, role) =>
    kind === "coaching"
      ? "New coaching written"
      : role === "reference"
        ? "Reference added"
        : "Analysis finished",
  cancelled: (_, kind) => (kind === "coaching" ? "Coaching cancelled" : "Analysis cancelled"),
  failed: (_, kind, role) =>
    kind === "coaching"
      ? "New coaching could not be written"
      : role === "reference"
        ? "The reference could not be added"
        : "The analysis did not finish",
};

function RunBody({ run, kind, role, coachingFor, store }: RunPanelProps) {
  switch (run.phase) {
    case "idle":
      return null;
    case "submitting":
    case "loading_result":
      return <p className={MUTED}>One moment.</p>;

    case "tracking": {
      const { job } = run;
      const stages = stagesFor(kind, role);
      const currentIndex = job.stage ? stages.indexOf(job.stage) : -1;
      return (
        <>
          {job.status === "queued" && (
            <p>
              {job.queuePosition
                ? `${job.queuePosition} ${job.queuePosition === 1 ? "job is" : "jobs are"} ahead of this one.`
                : "It starts as soon as the worker picks it up."}
            </p>
          )}
          {/* Stages, not a percentage: the app cannot honestly say it is "40% done". */}
          <ol className="flex flex-col gap-1.5">
            {stages.map((stage, index) => {
              const state =
                job.status !== "running" || index > currentIndex
                  ? "waiting"
                  : index === currentIndex
                    ? "current"
                    : "done";
              return (
                <li key={stage} className="flex items-center gap-2 text-sm">
                  <span
                    aria-hidden="true"
                    className={`h-2.5 w-2.5 shrink-0 rounded-full ${
                      state === "done"
                        ? "bg-emerald-600"
                        : state === "current"
                          ? "bg-indigo-600 motion-safe:animate-pulse dark:bg-indigo-400"
                          : "bg-zinc-300 dark:bg-zinc-700"
                    }`}
                  />
                  <span className={state === "waiting" ? MUTED : state === "current" ? "font-semibold" : ""}>
                    {STAGE_LABELS[stage]}
                  </span>
                  <span className={`text-xs ${MUTED}`}>
                    {state === "done" ? "Done" : state === "current" ? "In progress" : ""}
                  </span>
                </li>
              );
            })}
          </ol>
          {job.cancelRequested && (
            <p className={`text-sm ${MUTED}`}>
              The worker stops at its next safe point, usually within a few seconds.
            </p>
          )}
          {!job.workerAlive && (
            <Notice kind="warning">
              The worker is not running, so this will wait. In a terminal, run:
              <Command>cd backend && uv run python -m app.worker</Command>
            </Notice>
          )}
          {run.contact === "lost" && (
            <Notice kind="warning">
              Lost contact with the local backend. Still trying; this is the last status it gave.
            </Notice>
          )}
          <div>
            <Button disabled={!job.canCancel} onClick={() => store.cancel()}>
              {kind === "coaching" ? "Cancel" : "Cancel analysis"}
            </Button>
          </div>
        </>
      );
    }

    case "done":
      return (
        <>
          <p>
            {kind === "coaching"
              ? "It replaces the earlier coaching in the results below. The measurements were not changed."
              : role === "reference"
                ? "It is now in your reference recordings and has been chosen to compare with."
                : "The results are below and have been added to your history."}
          </p>
          <div>
            <Button onClick={() => store.dismissRun()}>Dismiss</Button>
          </div>
        </>
      );

    case "cancelled":
      return (
        <>
          <p>
            {kind === "coaching"
              ? "The coaching that was already there has been left as it was."
              : "Nothing was saved, and the uploaded audio was deleted from the backend."}
          </p>
          <div>
            <Button onClick={() => store.dismissRun()}>Dismiss</Button>
          </div>
        </>
      );

    case "failed": {
      if (kind === "coaching") {
        const help = coachHelp(run.error.code, null);
        return (
          <>
            <Notice kind="error">{run.error.message}</Notice>
            {help && (
              <div className="text-sm">
                {help.text}
                {help.command && <Command>{help.command}</Command>}
              </div>
            )}
            <p className={`text-sm ${MUTED}`}>
              The coaching that was already there has been left as it was, and the measurements
              were not touched.
            </p>
            <div className="flex flex-wrap gap-2">
              {coachingFor && (
                <Button variant="primary" onClick={() => store.regenerateCoaching(coachingFor)}>
                  Try again
                </Button>
              )}
              <Button onClick={() => store.dismissRun()}>Dismiss</Button>
            </div>
          </>
        );
      }
      const canRetry = run.job?.canRetry ?? false;
      return (
        <>
          <Notice kind="error">{run.error.message}</Notice>
          {canRetry && (
            <p className={`text-sm ${MUTED}`}>
              The uploaded audio is still held on this device for a retry. It is deleted if you
              discard it, and automatically after a day.
            </p>
          )}
          {!canRetry && !run.canResubmit && (
            <p className={`text-sm ${MUTED}`}>
              Trying the same audio again would fail the same way. Record or upload again to
              start a new analysis.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {canRetry && (
              <>
                <Button variant="primary" onClick={() => store.retry()}>
                  Retry
                </Button>
                <Button onClick={() => store.cancel()}>Discard</Button>
              </>
            )}
            {run.canResubmit && (
              <Button variant="primary" onClick={() => store.resubmit()}>
                Send again
              </Button>
            )}
            {!canRetry && <Button onClick={() => store.dismissRun()}>Dismiss</Button>}
          </div>
        </>
      );
    }
  }
}
