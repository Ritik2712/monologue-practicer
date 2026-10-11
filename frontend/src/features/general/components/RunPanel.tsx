"use client";

import { Button } from "@/components/Button";

import { STAGE_LABELS } from "../format";
import type { GeneralStore, RunState } from "../generalStore";
import type { JobStage } from "../types";
import { Command, MUTED, Notice } from "./parts";

const STAGES = Object.keys(STAGE_LABELS) as JobStage[];

type RunPanelProps = { run: RunState; store: GeneralStore };

/** What is happening to the recording that was just submitted. */
export function RunPanel({ run, store }: RunPanelProps) {
  if (run.phase === "idle") return null;

  return (
    <section
      aria-labelledby="run-heading"
      aria-live="polite"
      className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
    >
      <h2 id="run-heading" className="text-lg font-semibold">
        {HEADINGS[run.phase](run)}
      </h2>
      <div className="mt-2 flex flex-col gap-3">
        <RunBody run={run} store={store} />
      </div>
    </section>
  );
}

const HEADINGS: { [Phase in RunState["phase"]]: (run: RunState) => string } = {
  idle: () => "",
  submitting: () => "Sending the recording to the local backend",
  tracking: (run) => {
    if (run.phase !== "tracking") return "";
    if (run.job.cancelRequested) return "Cancelling";
    return run.job.status === "queued" ? "Waiting in the queue" : "Analysing your recording";
  },
  loading_result: () => "Loading the result",
  done: () => "Analysis finished",
  cancelled: () => "Analysis cancelled",
  failed: () => "The analysis did not finish",
};

function RunBody({ run, store }: RunPanelProps) {
  switch (run.phase) {
    case "idle":
      return null;
    case "submitting":
    case "loading_result":
      return <p className={MUTED}>One moment.</p>;

    case "tracking": {
      const { job } = run;
      const currentIndex = job.stage ? STAGES.indexOf(job.stage) : -1;
      return (
        <>
          {job.status === "queued" && (
            <p>
              {job.queuePosition
                ? `${job.queuePosition} ${job.queuePosition === 1 ? "analysis is" : "analyses are"} ahead of this one.`
                : "It starts as soon as the worker picks it up."}
            </p>
          )}
          {/* Stages, not a percentage: the app cannot honestly say it is "40% done". */}
          <ol className="flex flex-col gap-1.5">
            {STAGES.map((stage, index) => {
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
              The worker is not running, so this recording will wait. In a terminal, run:
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
              Cancel analysis
            </Button>
          </div>
        </>
      );
    }

    case "done":
      return (
        <>
          <p>The results are below and have been added to your history.</p>
          <div>
            <Button onClick={() => store.dismissRun()}>Dismiss</Button>
          </div>
        </>
      );

    case "cancelled":
      return (
        <>
          <p>Nothing was saved, and the uploaded audio was deleted from the backend.</p>
          <div>
            <Button onClick={() => store.dismissRun()}>Dismiss</Button>
          </div>
        </>
      );

    case "failed": {
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
