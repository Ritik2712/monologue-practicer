"use client";

import type { ReactNode } from "react";

import { Button } from "@/components/Button";

import {
  canRegenerate,
  COACH_STATUS_TEXT,
  coachHelp,
  findingById,
  playRange,
  practiseLine,
} from "../coaching";
import type { FeedbackStore } from "../feedbackStore";
import { formatDateTime, formatSpan, formatTimecode } from "../format";
import type {
  CoachStatus,
  Coaching as CoachingData,
  DeliveryProfile,
  Evidence,
  FeedbackItem,
  SpeechSegment,
} from "../types";
import { CorrectionRating } from "./FeedbackControls";
import { Command, MUTED, Notice, Section } from "./parts";

export type Regeneration =
  | { status: "idle" }
  | { status: "running" }
  | { status: "done" }
  | { status: "failed"; message: string };

type CoachingProps = {
  coaching: CoachingData | null;
  segments: SpeechSegment[];
  /** The chosen delivery profile's description, when the options have loaded. */
  profile: DeliveryProfile | undefined;
  /** Whether the local AI model is available, as the worker last reported. Null if unknown. */
  coach: { status: CoachStatus; model: string | null } | null;
  /** True while an analysis or a coaching job is in progress. */
  busy: boolean;
  /** How the latest request to write this analysis's coaching again is going. */
  regeneration: Regeneration;
  onRegenerate: () => void;
  playButton: (label: string, start: number, end?: number) => ReactNode;
  /** True when pauses have been labelled since this coaching was written. */
  labelsChanged?: boolean;
  /** Lets each correction be rated. Left out when feedback is not available. */
  rating?: {
    store: FeedbackStore;
    saving: boolean;
    find: (findingId: string, findingKind: string | undefined) => FeedbackItem | undefined;
  };
};

/** What to change, what to keep, and what to aim for, built on the measurements above it. */
export function Coaching({
  coaching,
  segments,
  profile,
  coach,
  busy,
  regeneration,
  onRegenerate,
  playButton,
  labelsChanged = false,
  rating,
}: CoachingProps) {
  const listen = (evidence: Evidence, label: string) => {
    const range = playRange(evidence);
    return range ? playButton(label, range.start, range.end) : null;
  };

  return (
    <Section
      id="coaching-heading"
      title="Coaching"
      description="Every figure below comes from the measurements. The advice built on them is a suggestion: you decide what suits the performance."
    >
      {profile && profile.focus.length > 0 && (
        <p className="text-sm">
          Coached against the <span className="font-medium">{profile.name}</span> profile, which
          leans on: {profile.focus.map((item) => item.label.toLowerCase()).join(", ")}. A profile is
          a target described in words, not a measurement of any actor&rsquo;s voice.
        </p>
      )}

      {coaching === null ? (
        <Notice kind="info">No coaching is stored for this analysis. The measurements are complete.</Notice>
      ) : (
        <>
          <Source coaching={coaching} />

          {coaching.summary.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Delivery summary</h4>
              <dl className="mt-1 flex flex-col gap-1.5 text-sm">
                {coaching.summary.map((line) => (
                  <div key={line.label} className="sm:grid sm:grid-cols-[5rem_minmax(0,1fr)] sm:gap-3">
                    <dt className={MUTED}>{line.label}</dt>
                    <dd>{line.text}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {coaching.corrections.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">
                {coaching.corrections.length === 1
                  ? "The one thing to work on"
                  : `Top ${coaching.corrections.length} corrections, most important first`}
              </h4>
              <ol className="mt-2 flex flex-col gap-3">
                {coaching.corrections.map((correction, index) => {
                  const finding = findingById(coaching, correction.findingId);
                  const line = practiseLine(correction.practise, segments);
                  const others = (finding?.evidence ?? []).filter(
                    (item) => item.kind !== "metric" && item.id !== correction.practise?.id,
                  );
                  return (
                    <li
                      key={correction.findingId}
                      className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
                    >
                      <p className="font-semibold">
                        <span className={MUTED}>{index + 1}.</span> {correction.title}
                      </p>
                      <dl className="mt-2 flex flex-col gap-2 text-sm">
                        {finding && (
                          <div>
                            <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>
                              Measured
                            </dt>
                            <dd>{finding.statement}</dd>
                          </div>
                        )}
                        <div>
                          <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>
                            Why it matters
                          </dt>
                          <dd>{correction.why}</dd>
                        </div>
                        <div>
                          <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>
                            Drill
                          </dt>
                          <dd>{correction.drill}</dd>
                        </div>
                        {correction.practise && (
                          <div>
                            <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>
                              Practise on
                            </dt>
                            <dd className="flex flex-wrap items-center gap-x-2">
                              <span>
                                {correction.practise.label},{" "}
                                <span className="tabular-nums">
                                  {formatTimecode(correction.practise.startSeconds ?? 0)}–
                                  {formatTimecode(correction.practise.endSeconds ?? 0)}
                                </span>
                                {line && <span>: “{line}”</span>}
                              </span>
                              {listen(correction.practise, `Play ${correction.practise.label.toLowerCase()}`)}
                            </dd>
                          </div>
                        )}
                        {others.length > 0 && (
                          <div>
                            <dt className={`text-xs font-medium uppercase tracking-wide ${MUTED}`}>
                              Also listen to
                            </dt>
                            <dd className="flex flex-wrap items-center gap-x-3">
                              {others.map((item) => (
                                <span key={item.id} className="flex items-center gap-x-1">
                                  {item.label}
                                  {listen(item, `Play ${item.label.toLowerCase()}`)}
                                </span>
                              ))}
                            </dd>
                          </div>
                        )}
                        {rating && (
                          <CorrectionRating
                            findingId={correction.findingId}
                            title={correction.title}
                            item={rating.find(correction.findingId, finding?.kind)}
                            disabled={rating.saving}
                            store={rating.store}
                          />
                        )}
                      </dl>
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {coaching.working.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">What is already working</h4>
              <ul className="mt-1 flex flex-col gap-2 text-sm">
                {coaching.working.map((strength) => (
                  <li key={strength.findingId}>
                    {strength.note}
                    <span className={`block text-xs ${MUTED}`}>
                      Measured: {findingById(coaching, strength.findingId)?.statement}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {coaching.nextTake.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Targets for the next take</h4>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">
                {coaching.nextTake.map((target) => (
                  <li key={target}>{target}</li>
                ))}
              </ul>
              <p className={`mt-1 text-xs ${MUTED}`}>
                The figures in these targets are this app&rsquo;s own rough bands for words such as
                “fast” or “even”. They are not taken from any actor&rsquo;s recording.
              </p>
            </div>
          )}

          {coaching.caveats.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold">Uncertain or not measured</h4>
              <ul className={`mt-1 list-disc space-y-0.5 pl-5 text-sm ${MUTED}`}>
                {coaching.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {(canRegenerate(coaching) || labelsChanged) && (
        <Regenerate
          coaching={coaching}
          coach={coach}
          busy={busy}
          regeneration={regeneration}
          onRegenerate={onRegenerate}
          labelsChanged={labelsChanged}
        />
      )}
    </Section>
  );
}

/** Says who worded the coaching, and why if it was not the AI model. */
function Source({ coaching }: { coaching: CoachingData }) {
  const when = formatDateTime(coaching.generatedAt);
  if (coaching.source === "ai") {
    return (
      <>
        <p className={`text-sm ${MUTED}`}>
          Worded by the AI model <span className="font-medium">{coaching.model}</span>, running on
          this computer. It was given the transcript and the measurements, never the audio, and
          its answer was checked against the measurements. Written {when}
          {coaching.modelSeconds !== null && ` in ${formatSpan(coaching.modelSeconds)}`}.
        </p>
        {coaching.notice && <Notice kind="warning">{coaching.notice.message}</Notice>}
      </>
    );
  }
  if (coaching.source === "none") {
    return <Notice kind="info">{coaching.notice?.message ?? "There was too little to coach on."}</Notice>;
  }
  const help = coaching.notice ? coachHelp(coaching.notice.code, null) : null;
  const nothingToCorrect = coaching.notice?.code === "nothing_to_correct";
  return (
    <Notice kind="info">
      {nothingToCorrect ? (
        <p>{coaching.notice?.message}</p>
      ) : (
        <p>
          <span className="font-medium">Written from fixed rules, not by the AI model.</span>{" "}
          {coaching.notice?.message} The measurements are complete either way.
        </p>
      )}
      {help && (
        <p className="mt-1">
          {help.text}
          {help.command && <Command>{help.command}</Command>}
        </p>
      )}
    </Notice>
  );
}

function Regenerate({
  coaching,
  coach,
  busy,
  regeneration,
  onRegenerate,
  labelsChanged,
}: Pick<
  CoachingProps,
  "coaching" | "coach" | "busy" | "regeneration" | "onRegenerate" | "labelsChanged"
>) {
  const unavailable =
    coach && coach.status !== "ready" && coach.status !== "unknown" ? coach.status : null;
  // With new pause labels to take in, coaching written from the fixed rules is already an
  // improvement, so the rewrite can go ahead without the AI model.
  const blocked = unavailable !== null && !labelsChanged;
  // Said here as well as in the progress panel, which may be off screen above.
  const hint =
    regeneration.status === "running"
      ? "The AI model is writing new coaching. This takes about half a minute."
      : busy
        ? "Wait for the run in progress to finish."
        : blocked && unavailable
          ? `The AI model is not available right now: ${COACH_STATUS_TEXT[unavailable]}.`
          : regeneration.status === "done" && !labelsChanged
            ? "New coaching written. It replaced the earlier coaching above."
            : labelsChanged && unavailable
              ? `The AI model is not available (${COACH_STATUS_TEXT[unavailable]}), so the coaching will be rewritten from the fixed rules, with your labels taken in.`
              : "Uses the same measurements; nothing is re-recorded or re-measured. Takes about half a minute. If the model cannot answer, the coaching above stays as it is.";
  return (
    <div className="flex flex-col gap-2">
      {labelsChanged && (
        <Notice kind="info">
          You have changed your pause labels since this coaching was written, so it does not
          take them into account yet. Write it again to bring them in. The measurements are not
          affected either way.
        </Notice>
      )}
      {regeneration.status === "failed" && (
        <Notice kind="error">
          New coaching could not be written. {regeneration.message} The coaching above was left
          as it was.
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={busy || blocked} onClick={onRegenerate}>
          {regeneration.status === "failed"
            ? "Try again"
            : labelsChanged
              ? "Write the coaching again with my labels"
              : coaching?.source === "ai"
                ? "Write the coaching again"
                : "Ask the AI model for coaching"}
        </Button>
        <p role="status" className={`min-w-0 flex-1 text-sm ${MUTED}`}>
          {hint}
        </p>
      </div>
    </div>
  );
}
