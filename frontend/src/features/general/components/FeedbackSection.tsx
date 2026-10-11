"use client";

import { Button } from "@/components/Button";

import { formatSetting } from "../feedback";
import type { AnalysisResult, CalibrationChange } from "../types";
import { FeedbackEntry, type FeedbackTools } from "./FeedbackControls";
import { FOCUS_RING, MUTED, Notice, Section } from "./parts";

/** Tells the user that their feedback has just moved a setting, and how to take it back. */
export function AdjustmentNotice({
  adjustments,
  onDismiss,
}: {
  adjustments: CalibrationChange[];
  onDismiss: () => void;
}) {
  if (adjustments.length === 0) return null;
  return (
    <Notice kind="warning">
      <p className="font-medium">
        Your feedback has just changed {adjustments.length === 1 ? "a setting" : "settings"}
      </p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5">
        {adjustments.map((change) => (
          <li key={change.version}>
            {change.reason}
            {change.confidence && (
              <span>
                {" "}
                Confidence: {change.confidence} ({change.agreeingCount} of {change.reportCount}{" "}
                reports agreed).
              </span>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-1">
        This applies to recordings analysed from now on. Results already made keep the settings
        they were made with. It can be undone under{" "}
        <a href="#calibration-heading" className={`rounded font-medium underline underline-offset-4 ${FOCUS_RING}`}>
          Feedback and calibration
        </a>
        .
      </p>
      <div className="mt-2">
        <Button onClick={onDismiss}>Dismiss</Button>
      </div>
    </Notice>
  );
}

type FeedbackSectionProps = {
  analysis: AnalysisResult;
  tools: FeedbackTools;
};

/**
 * Everything the user has said about this result, in one place, with what each piece does.
 * The controls for saying it sit next to the pauses, phrases and corrections themselves.
 */
export function FeedbackSection({ analysis, tools }: FeedbackSectionProps) {
  const { state, store } = tools;
  const overall = state.items.find((item) => item.targetKind === "recording");
  const calibration = state.calibration.status === "ready" ? state.calibration.data : null;
  const minPause = calibration?.settings.find((setting) => setting.name === "min_pause_ms");

  return (
    <Section
      id="feedback-heading"
      title="Your feedback on this result"
      description="Tell the app where it got this recording wrong. Use the feedback lists beside each pause, phrase and correction above; what you have said is gathered here. It is stored on this device only and never sent anywhere."
    >
      <AdjustmentNotice adjustments={state.adjustments} onDismiss={() => store.dismissAdjustments()} />

      {state.error && (
        <Notice kind="error" action={<Button onClick={() => store.dismissError()}>Dismiss</Button>}>
          That was not saved. {state.error}
        </Notice>
      )}
      {state.status === "error" && (
        <Notice kind="error">The feedback on this result could not be loaded. {state.message}</Notice>
      )}

      <div>
        <p className="text-sm font-medium">The overall WPM</p>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Button
            disabled={state.saving || overall?.category === "wpm_too_high"}
            onClick={() => store.give({ category: "wpm_too_high" })}
          >
            It looks too high
          </Button>
          <Button
            disabled={state.saving || overall?.category === "wpm_too_low"}
            onClick={() => store.give({ category: "wpm_too_low" })}
          >
            It looks too low
          </Button>
          <p className={`text-sm ${MUTED}`}>
            No figure is changed by this: you are shown what went into it.
          </p>
        </div>
      </div>

      {state.status === "loading" && <p className={`text-sm ${MUTED}`}>Loading your feedback…</p>}
      {state.status === "ready" && state.items.length === 0 && (
        <p className={`text-sm ${MUTED}`}>
          Nothing yet. Feedback is optional: the results above are complete without it.
        </p>
      )}
      {state.items.length > 0 && (
        <ul aria-label="Feedback saved on this result" className="flex flex-col gap-2">
          {state.items.map((item) => (
            <FeedbackEntry
              key={item.id}
              item={item}
              analysis={analysis}
              disabled={state.saving}
              store={store}
            />
          ))}
        </ul>
      )}

      <p className={`text-xs ${MUTED}`}>
        What feedback does: a label on a pause changes how the coaching reads that pause, and
        never the pause itself. A report of a mistake counts towards adjusting one setting, which
        moves only after several reports agree
        {minPause
          ? ` (the minimum pause is ${formatSetting(minPause.value, minPause.digits, minPause.unit)} at the moment)`
          : ""}
        . It improves this app&rsquo;s rules of thumb for your recordings. It does not retrain the
        speech recogniser, and it cannot make the analysis perfect.{" "}
        <a
          href="#calibration-heading"
          className={`rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS_RING}`}
        >
          See the current calibration
        </a>
      </p>
    </Section>
  );
}
