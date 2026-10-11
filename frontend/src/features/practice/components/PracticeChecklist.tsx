"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { audioSourceFor } from "@/features/general/coaching";
import { BackendNotice } from "@/features/general/components/BackendNotice";
import { CalibrationPanel } from "@/features/general/components/CalibrationPanel";
import { MUTED, Notice } from "@/features/general/components/parts";
import { formatDateTime, formatSpan } from "@/features/general/format";
import type { Monologue } from "@/features/general/types";
import {
  generalApi,
  useBackendHealth,
  useFeedback,
  useGeneralStore,
  useRecorder,
} from "@/features/general/useGeneralPractice";
import { CorrectTools } from "@/features/monologue/components/CorrectTools";
import { ListenTools } from "@/features/monologue/components/ListenTools";
import { RecordTools } from "@/features/monologue/components/RecordTools";
import { ScriptView } from "@/features/monologue/components/ScriptView";
import { MONOLOGUES_HREF, practiceHref } from "@/features/monologue/links";

import { PRACTICE_ROUTINE } from "../config";
import { formatDayLabel, totalMinutes } from "../format";
import {
  getActiveStep,
  isPristine,
  isRoundFinished,
  isRoundUntouched,
  summarize,
} from "../practiceState";
import type { StorageWarning } from "../practiceStore";
import type { PracticeMonologue } from "../types";
import { usePracticeChecklist } from "../usePracticeChecklist";
import { PracticeHistory } from "./PracticeHistory";
import { stepElementId, StepList } from "./StepList";
import { TimerPanel } from "./TimerPanel";

const ROUTINE_MINUTES = totalMinutes(PRACTICE_ROUTINE.steps.map((step) => step.durationSeconds));

const WARNING_TEXT: Record<StorageWarning, string> = {
  unavailable:
    "This browser is blocking local storage, so your progress will be lost when this page is closed or refreshed.",
  corrupt:
    "Saved checklist data on this device could not be read, so a fresh checklist was started.",
  partially_invalid: "Some saved practice days could not be read and have been left out.",
  write_failed: "Your latest progress could not be saved on this device. Storage may be full.",
};

const CONFIRMATIONS = {
  reset_today: {
    title: "Reset today's checklist?",
    description:
      "This clears today's completed and skipped steps, in every round, and stops the timer. Your takes, their analyses and previous days in your history are not affected.",
    confirmLabel: "Reset today",
  },
  clear_history: {
    title: "Clear practice history?",
    description:
      "This deletes the saved checklist records for previous days from this device. Today's checklist, your monologues and your takes are not affected. This cannot be undone.",
    confirmLabel: "Clear history",
  },
  switch_monologue: {
    title: "Switch to the other monologue?",
    description:
      "The steps completed and skipped in this round are cleared and the timer stops, and the round starts again on the monologue you asked for. Rounds finished earlier today, your takes and previous days are not affected.",
    confirmLabel: "Switch monologue",
  },
} as const;

type Confirmation = keyof typeof CONFIRMATIONS;

const LINK =
  "rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:text-indigo-300 dark:focus-visible:outline-indigo-400";

function takesLine(monologue: Monologue): string {
  if (monologue.takeCount === 0 || monologue.lastTakeAt === null) return "no takes yet";
  const count = monologue.takeCount === 1 ? "1 take" : `${monologue.takeCount} takes`;
  return `${count}, the last on ${formatDateTime(monologue.lastTakeAt)}`;
}

/**
 * Daily Speaking Practice: the timed five-step routine, done on one monologue. Each step
 * carries what it is done with: the original to listen to, its script, the recorder and
 * the comparison of the take with the original.
 */
export function PracticeChecklist() {
  const { snapshot, dispatch } = usePracticeChecklist();
  const requestedId = useSearchParams().get("monologue");
  const router = useRouter();
  const { state, store } = useGeneralStore();
  const { state: recorderState } = useRecorder();
  const { health, refresh: refreshHealth } = useBackendHealth();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  // Keeps the dialog's text in place while it closes.
  const [lastConfirmation, setLastConfirmation] = useState<Confirmation>("reset_today");
  // Tools the user has opened or closed by hand. Otherwise a step's tools show while it is
  // the current step, and while something of its own is going on.
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const record = snapshot?.record ?? null;
  const list = state.monologues;
  // The monologue the round on screen is on, and the one the address asks for.
  const active = record?.monologue ?? null;
  const requested = requestedId
    ? (list.items.find((item) => item.monologueId === requestedId) ?? null)
    : null;
  const listedActive = active
    ? (list.items.find((item) => item.monologueId === active.id) ?? null)
    : null;
  // A round that is under way stays on its monologue; anything else follows the address.
  const followsRequest =
    record !== null &&
    requested !== null &&
    (active === null || active.id === requested.monologueId || isRoundUntouched(record));
  const current: PracticeMonologue | null =
    followsRequest && requested ? { id: requested.monologueId, title: requested.title } : active;
  const currentId = current?.id ?? null;
  const conflict = record !== null && requested !== null && !followsRequest;

  // Tells the checklist which monologue the round is on, and keeps the saved title in
  // step with the list. The checklist's own rules ignore it while a round is under way
  // on another monologue.
  const target = requested ?? listedActive;
  const targetId = target?.monologueId ?? null;
  const targetTitle = target?.title ?? null;
  const localDate = record?.localDate ?? null;
  const activeId = active?.id ?? null;
  useEffect(() => {
    if (localDate === null || targetId === null || targetTitle === null) return;
    dispatch({ type: "set_monologue", monologue: { id: targetId, title: targetTitle } });
  }, [dispatch, targetId, targetTitle, localDate, activeId]);

  // The store loads this monologue's takes and chooses its original recording.
  useEffect(() => {
    store.watchMonologue(currentId);
  }, [store, currentId]);

  const monologue = currentId
    ? (list.items.find((item) => item.monologueId === currentId) ?? null)
    : null;
  const reference =
    state.monologueId === currentId && state.referenceDetail.status === "ready"
      ? state.referenceDetail.analysis
      : null;
  const take =
    state.viewed.status === "ready" &&
    state.viewed.analysis.role === "take" &&
    currentId !== null &&
    state.viewed.analysis.monologueId === currentId
      ? state.viewed.analysis
      : null;
  // On this page feedback is about the original recording being studied. Feedback on a
  // take is given on the take's own page, where its coaching is.
  const feedback = useFeedback(reference?.analysisId ?? null);
  const coach =
    health.status === "reachable"
      ? { status: health.health.coach, model: health.health.coachModel }
      : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);

  const header = (
    <header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Daily Speaking Practice</h1>
        <span className="rounded-full border border-zinc-300 px-3 py-1 text-sm font-medium dark:border-zinc-700">
          {ROUTINE_MINUTES}-minute routine
        </span>
      </div>
      <p className="mt-2 text-zinc-700 dark:text-zinc-300">
        {PRACTICE_ROUTINE.steps.length} timed steps on one monologue: listen to the original,
        mark it, perform it, record your take and compare the two.
      </p>
    </header>
  );

  if (!snapshot || !record) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        <p role="status" className="text-zinc-600 dark:text-zinc-400">
          Loading your checklist…
        </p>
      </div>
    );
  }

  const { remainingMs, todayKey, warning } = snapshot;
  const summary = summarize(record);
  const activeStep = getActiveStep(record);
  const activeStepNumber = activeStep ? record.steps.indexOf(activeStep) + 1 : null;
  const finishingYesterday = record.localDate !== todayKey;
  const roundNumber = record.earlierRounds.length + 1;

  const ask = (kind: Confirmation) => {
    setLastConfirmation(kind);
    setConfirmation(kind);
  };
  const confirm = () => {
    if (confirmation === "switch_monologue") {
      if (requested) {
        dispatch({
          type: "switch_monologue",
          monologue: { id: requested.monologueId, title: requested.title },
        });
        setToggled({});
      }
    } else if (confirmation) {
      dispatch({ type: confirmation });
    }
    setConfirmation(null);
  };
  const startRound = (on: PracticeMonologue | null) => {
    dispatch({ type: "start_round", monologue: on });
    setToggled({});
  };

  const warnings = (
    <>
      {warning && (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
        >
          <p>{WARNING_TEXT[warning]}</p>
          <Button onClick={() => dispatch({ type: "dismiss_warning" })}>Dismiss</Button>
        </div>
      )}
      <BackendNotice health={health} onCheckAgain={refreshHealth} />
      {state.notice && (
        <Notice
          kind={state.notice.kind}
          action={<Button onClick={() => store.dismissNotice()}>Dismiss</Button>}
        >
          {state.notice.text}
        </Notice>
      )}
    </>
  );

  const history = (
    <>
      <PracticeHistory snapshot={snapshot} onClearHistory={() => ask("clear_history")} />
      <p className="text-sm text-zinc-600 dark:text-zinc-400">
        The checklist and its history are saved only in this browser on this device. Your
        monologues, your takes and their analyses are saved by the app&rsquo;s backend on this
        computer. Nothing syncs anywhere.
      </p>
    </>
  );

  const dialog = (
    <ConfirmDialog
      open={confirmation !== null}
      {...CONFIRMATIONS[confirmation ?? lastConfirmation]}
      onConfirm={confirm}
      onCancel={() => setConfirmation(null)}
    />
  );

  // --- No monologue yet: choose one first ------------------------------------------------
  if (!current) {
    return (
      <div className="flex flex-col gap-6">
        {header}
        {warnings}
        <MonologueChooser
          list={list}
          missing={requestedId !== null && list.status === "ready"}
          onRetry={() => store.refreshMonologues()}
        />
        {history}
        {dialog}
      </div>
    );
  }

  // --- The tools of each step ------------------------------------------------------------
  const referenceAudioSrc = reference ? audioSourceFor(reference, state.localAudio, generalApi) : null;
  const takeAudioSrc = take ? audioSourceFor(take, state.localAudio, generalApi) : null;
  const script: ReactNode = reference ? (
    <ScriptView reference={reference} audioSrc={referenceAudioSrc} />
  ) : state.referenceDetail.status === "error" ? (
    <Notice kind="error">
      The original recording could not be opened. {state.referenceDetail.message}
    </Notice>
  ) : (
    <p className={`text-sm ${MUTED}`}>Loading the original recording…</p>
  );

  const showStep = (stepId: string) => {
    setToggled((before) => ({ ...before, [stepId]: true }));
    document.getElementById(stepElementId(stepId))?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const tools: Record<string, ReactNode> = monologue
    ? {
        listen: <ListenTools state={state} store={store} feedback={feedback} busy={busy} />,
        mark: script,
        perform: script,
        compare: (
          <RecordTools
            // A fresh form for each monologue: its language, and no file chosen for another.
            key={current.id}
            state={state}
            store={store}
            monologue={current}
            language={monologue.language}
            take={take}
            reference={reference}
          />
        ),
        correct: (
          <CorrectTools
            comparison={take ? state.comparison : { status: "none" }}
            hasTake={take !== null}
            takeAudioSrc={takeAudioSrc}
            referenceAudioSrc={referenceAudioSrc}
            onRecordAgain={() => showStep("compare")}
          />
        ),
      }
    : {};

  // Tools stay open while something of theirs is going on, even after the step's timer
  // has run out and the next step has become the current one.
  const takeRun = state.runRole === "take" && state.run.phase !== "idle";
  const inUse: Record<string, boolean> = {
    listen: state.runRole === "reference" && state.run.phase !== "idle",
    compare: take !== null || takeRun || recorderState.status !== "idle",
  };
  const isOpen = (stepId: string) =>
    toggled[stepId] ?? (stepId === record.activeStepId || inUse[stepId] === true);

  return (
    <div className="flex flex-col gap-6">
      {header}
      {warnings}

      <section
        aria-labelledby="monologue-heading"
        className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      >
        <h2 id="monologue-heading" className={`text-sm font-medium ${MUTED}`}>
          Practising
        </h2>
        <p className="mt-1 text-lg font-semibold break-words">{current.title}</p>
        {monologue && (
          <p className={`mt-1 text-sm ${MUTED}`}>
            The original is {formatSpan(monologue.durationSeconds)} long. You have{" "}
            {takesLine(monologue)}.
          </p>
        )}
        <p className="mt-2 text-sm">
          <Link href={MONOLOGUES_HREF} className={LINK}>
            Choose another monologue
          </Link>
        </p>
      </section>

      {!monologue && list.status === "ready" && (
        <Notice kind="warning">
          “{current.title}” is no longer among your monologues, so its original recording and
          its takes cannot be shown. The timer still works.{" "}
          <Link href={MONOLOGUES_HREF} className={LINK}>
            Choose another monologue
          </Link>{" "}
          to practise with the tools.
        </Notice>
      )}
      {list.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.refreshMonologues()}>Try again</Button>}>
          Your monologues could not be loaded. {list.message}
        </Notice>
      )}

      {conflict && requested && active && (
        <Notice
          kind="warning"
          action={
            isRoundFinished(record) ? (
              <Button
                variant="primary"
                onClick={() =>
                  startRound({ id: requested.monologueId, title: requested.title })
                }
              >
                Start a new round on it
              </Button>
            ) : (
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => router.replace(practiceHref(active.id))}>
                  Carry on with this one
                </Button>
                <Button variant="danger" onClick={() => ask("switch_monologue")}>
                  Switch to the other
                </Button>
              </div>
            )
          }
        >
          {isRoundFinished(record) ? (
            <>
              Today&rsquo;s round on “{active.title}” is finished. You opened “{requested.title}
              ”: a new round can be started on it.
            </>
          ) : (
            <>
              Today&rsquo;s round is under way on “{active.title}”, and you opened “
              {requested.title}”. A round stays on one monologue. Finish this one first, or
              switch, which clears the steps done in this round.
            </>
          )}
        </Notice>
      )}

      {finishingYesterday && (
        <p className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800">
          This timer started before midnight, so it counts towards{" "}
          {formatDayLabel(record.localDate, todayKey).toLowerCase()}. A fresh checklist for today
          appears when it stops.
        </p>
      )}

      <section aria-labelledby="progress-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <h2 id="progress-heading" className="text-lg font-semibold">
            {roundNumber > 1 && `Round ${roundNumber}: `}
            {summary.completed} of {summary.total} steps completed
          </h2>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {summary.percent}%{summary.skipped > 0 && ` · ${summary.skipped} skipped`}
          </p>
        </div>
        <div
          role="progressbar"
          aria-labelledby="progress-heading"
          aria-valuemin={0}
          aria-valuemax={summary.total}
          aria-valuenow={summary.completed}
          aria-valuetext={`${summary.completed} of ${summary.total} steps completed`}
          className="mt-2 h-3 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800"
        >
          <div
            className="h-full rounded-full bg-emerald-600 transition-[width] dark:bg-emerald-500"
            style={{ width: `${summary.percent}%` }}
          />
        </div>
        {roundNumber > 1 && (
          <p className={`mt-2 text-sm ${MUTED}`}>
            {record.earlierRounds.length === 1
              ? "1 round was finished earlier today"
              : `${record.earlierRounds.length} rounds were finished earlier today`}
            {record.earlierRounds.some((round) => round.completed === round.total)
              ? ", so today's routine is done. This round is extra."
              : "."}
          </p>
        )}
      </section>

      <TimerPanel
        activeStep={activeStep}
        activeStepNumber={activeStepNumber}
        timer={record.timer}
        remainingMs={remainingMs}
        summary={summary}
        dispatch={dispatch}
        onPractiseAgain={() => startRound(current)}
      />

      {/* Announces step changes to screen readers without reading out the countdown. */}
      <p aria-live="polite" className="sr-only">
        {summary.completed} of {summary.total} steps completed.{" "}
        {activeStep ? `Current step: ${activeStep.title}.` : "No current step."}
      </p>

      <section aria-labelledby="steps-heading" className="flex flex-col gap-3">
        <h2 id="steps-heading" className="text-lg font-semibold">
          Steps
        </h2>
        <p className={`text-sm ${MUTED}`}>
          Each step has what it is done with underneath it. The tools of the current step are
          open; any other step&rsquo;s can be opened too, whether or not its timer is running.
        </p>
        <StepList
          record={record}
          remainingMs={remainingMs}
          dispatch={dispatch}
          tools={tools}
          isOpen={isOpen}
          onToggle={(stepId, open) => setToggled((before) => ({ ...before, [stepId]: open }))}
        />
        <div>
          <Button
            variant="danger"
            disabled={isPristine(record)}
            onClick={() => ask("reset_today")}
          >
            Reset today&apos;s checklist
          </Button>
        </div>
      </section>

      {history}

      <CalibrationPanel state={feedback.state} store={feedback.store} coach={coach} />

      {dialog}
    </div>
  );
}

type MonologueChooserProps = {
  list: { status: "loading" | "ready" | "error"; items: Monologue[]; message: string | null };
  /** True when the address asked for a monologue that does not exist. */
  missing: boolean;
  onRetry: () => void;
};

/** Shown until a monologue is chosen: the routine is always done on one. */
function MonologueChooser({ list, missing, onRetry }: MonologueChooserProps) {
  return (
    <section aria-labelledby="choose-heading" className="flex flex-col gap-3">
      <h2 id="choose-heading" className="text-lg font-semibold">
        Choose the monologue to practise today
      </h2>
      {missing && (
        <Notice kind="warning">
          The monologue this address points to no longer exists. Choose another below.
        </Notice>
      )}
      {list.status === "loading" && <p className={MUTED}>Loading your monologues…</p>}
      {list.status === "error" && (
        <Notice kind="error" action={<Button onClick={onRetry}>Try again</Button>}>
          Your monologues could not be loaded. {list.message}
        </Notice>
      )}
      {list.status === "ready" && list.items.length === 0 && (
        <p className="text-sm">
          You have no monologue yet.{" "}
          <Link href={MONOLOGUES_HREF} className={LINK}>
            Add the original recording of one in Monologues
          </Link>
          , then come back to practise it.
        </p>
      )}
      {list.items.length > 0 && (
        <>
          <ul className="flex flex-col gap-2">
            {list.items.map((item) => (
              <li key={item.monologueId}>
                <Link
                  href={practiceHref(item.monologueId)}
                  className="block rounded-lg border border-zinc-200 p-4 hover:bg-zinc-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:border-zinc-800 dark:hover:bg-zinc-900 dark:focus-visible:outline-indigo-400"
                >
                  <span className="font-semibold break-words">{item.title}</span>
                  <span className={`mt-1 block text-sm ${MUTED}`}>
                    {formatSpan(item.durationSeconds)} · {takesLine(item)}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <p className="text-sm">
            <Link href={MONOLOGUES_HREF} className={LINK}>
              Add or delete monologues
            </Link>
          </p>
        </>
      )}
    </section>
  );
}
