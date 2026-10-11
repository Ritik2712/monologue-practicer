"use client";

import { useId, useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";

import { formatSetting } from "../feedback";
import type { FeedbackState, FeedbackStore } from "../feedbackStore";
import { formatDateTime } from "../format";
import type { CalibratedSetting, Calibration, CalibrationChange } from "../types";
import { FOCUS_RING, MUTED, Notice } from "./parts";

const CAUSE_LABELS: Record<CalibrationChange["cause"], string> = {
  defaults: "Starting point",
  auto: "Adjusted from feedback",
  undo: "Undone by you",
  reset: "Reset by you",
};

const CONFIDENCE_TEXT: Record<CalibratedSetting["confidence"], string> = {
  none: "Not adjusted",
  low: "Low: adjusted on few reports",
  medium: "Medium",
  high: "High",
};

function Badge({ children, tone }: { children: string; tone: "neutral" | "changed" | "off" }) {
  const styles = {
    neutral: "border-zinc-300 text-zinc-700 dark:border-zinc-700 dark:text-zinc-300",
    changed: "border-indigo-400 text-indigo-900 dark:border-indigo-600 dark:text-indigo-200",
    off: "border-amber-400 text-amber-900 dark:border-amber-700 dark:text-amber-200",
  }[tone];
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${styles}`}>{children}</span>
  );
}

function SettingRow({ setting }: { setting: CalibratedSetting }) {
  const show = (value: number) => formatSetting(value, setting.digits, setting.unit);
  return (
    <tr className="border-b border-zinc-100 align-top dark:border-zinc-900">
      <th scope="row" className="py-2 pr-3 font-normal">
        <span className="font-medium">{setting.label}</span>
        <span className={`block text-xs ${MUTED}`}>{setting.description}</span>
      </th>
      <td className="py-2 pr-3 font-medium tabular-nums whitespace-nowrap">
        {show(setting.value)}
        {setting.changed && <span className={`block text-xs font-normal ${MUTED}`}>changed</span>}
      </td>
      <td className="py-2 pr-3 tabular-nums whitespace-nowrap">{show(setting.default)}</td>
      <td className="py-2 pr-3 tabular-nums whitespace-nowrap">
        {show(setting.minimum)} to {show(setting.maximum)}
      </td>
      <td className="py-2">
        {setting.status}
        <span className={`block text-xs ${MUTED}`}>
          Confidence: {CONFIDENCE_TEXT[setting.confidence]}
          {setting.supportingReports > 0 &&
            ` (${setting.supportingReports} ${setting.supportingReports === 1 ? "report" : "reports"} behind the current value)`}
        </span>
      </td>
    </tr>
  );
}

function CalibrationBody({ data, state, store }: { data: Calibration; state: FeedbackState; store: FeedbackStore }) {
  const adaptiveId = useId();
  const [confirming, setConfirming] = useState(false);

  const analysis = data.settings.filter((setting) => setting.group === "analysis");
  const priorities = data.settings.filter((setting) => setting.group === "coaching");
  // Twelve kinds of correction each have a priority. Only the ones something has
  // happened to are worth a row of their own.
  const active = priorities.filter(
    (setting) => setting.changed || setting.pending.raiseCount + setting.pending.lowerCount > 0,
  );
  const quiet = priorities.length - active.length;
  const canReset = data.state === "adjusted" || data.pendingReportCount > 0 || data.canUndo;

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {!data.adaptive ? (
          <Badge tone="off">Automatic adjustment off</Badge>
        ) : data.state === "calibrating" ? (
          <Badge tone="neutral">Still calibrating</Badge>
        ) : (
          <Badge tone="changed">Adjusted from your feedback</Badge>
        )}
        <span className={`text-sm ${MUTED}`}>
          Settings version {data.version} · {data.feedbackCount}{" "}
          {data.feedbackCount === 1 ? "piece" : "pieces"} of feedback stored ·{" "}
          {data.pendingReportCount} {data.pendingReportCount === 1 ? "report" : "reports"} waiting
          to count
        </span>
      </div>
      <p className="text-sm">{data.summary}</p>

      {state.error && (
        <Notice kind="error" action={<Button onClick={() => store.dismissError()}>Dismiss</Button>}>
          {state.error}
        </Notice>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[44rem] text-left text-sm">
          <caption className="sr-only">Settings that feedback can adjust</caption>
          <thead className={MUTED}>
            <tr className="border-b border-zinc-200 dark:border-zinc-800">
              <th scope="col" className="py-2 pr-3 font-medium">Setting</th>
              <th scope="col" className="py-2 pr-3 font-medium">Now</th>
              <th scope="col" className="py-2 pr-3 font-medium">Default</th>
              <th scope="col" className="py-2 pr-3 font-medium">Allowed range</th>
              <th scope="col" className="py-2 font-medium">Where it stands</th>
            </tr>
          </thead>
          <tbody>
            {[...analysis, ...active].map((setting) => (
              <SettingRow key={setting.name} setting={setting} />
            ))}
          </tbody>
        </table>
      </div>
      {quiet > 0 && (
        <p className={`text-sm ${MUTED}`}>
          {active.length === 0 ? "All" : "The other"} {quiet} kinds of coaching correction are at
          normal priority (1.0, allowed range 0.4 to 1.0) with no ratings waiting. Rating a
          correction “not useful” several times moves that kind of correction down the list; it
          never hides the measurement behind it.
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!data.canUndo || state.saving} onClick={() => store.undo()}>
          Undo last adjustment
        </Button>
        <Button variant="danger" disabled={!canReset || state.saving} onClick={() => setConfirming(true)}>
          Reset to defaults
        </Button>
        <label htmlFor={adaptiveId} className="flex cursor-pointer items-center gap-2 text-sm">
          <input
            id={adaptiveId}
            type="checkbox"
            checked={data.adaptive}
            disabled={state.saving}
            onChange={(event) => store.setAdaptive(event.target.checked)}
            className={`h-4 w-4 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
          />
          Adjust settings automatically from my feedback
        </label>
      </div>
      <p className={`text-xs ${MUTED}`}>
        {data.canUndo
          ? "Undo puts back the value the most recent adjustment replaced. The reports behind it are not counted again."
          : "There is no adjustment to undo."}{" "}
        With automatic adjustment off, feedback is still saved and pause labels still shape the
        coaching, but no setting moves.
      </p>

      <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
          What changed, and why ({data.changes.length} {data.changes.length === 1 ? "version" : "versions"})
        </summary>
        <ol className="mt-2 flex flex-col gap-2 text-sm">
          {data.changes.map((change) => (
            <li key={change.version} className="border-b border-zinc-100 pb-2 last:border-0 dark:border-zinc-900">
              <p>
                <span className="font-medium">Version {change.version}</span> ·{" "}
                {CAUSE_LABELS[change.cause]} · {formatDateTime(change.createdAt)}
                {change.undone && <span className={MUTED}> · no longer in effect</span>}
              </p>
              <p>{change.reason}</p>
              {change.cause === "auto" && (
                <p className={`text-xs ${MUTED}`}>
                  {change.agreeingCount} of {change.reportCount} reports agreed, from{" "}
                  {change.recordingCount} recordings. Confidence: {change.confidence}.
                </p>
              )}
            </li>
          ))}
        </ol>
        <p className={`mt-2 text-xs ${MUTED}`}>
          Every result records the version it was made with, under “Settings that produced these
          numbers”, so an older result can always be traced to the values in force at the time.
        </p>
      </details>

      <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
          How a setting gets adjusted
        </summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
          <li>
            One report changes nothing. A setting moves only after {data.rules.minReports} reports
            that agree, from at least {data.rules.minRecordings} different recordings, making up at
            least {Math.round(data.rules.minAgreement * 100)}% of the last {data.rules.window}{" "}
            reports about it.
          </li>
          <li>
            One adjustment is small: the minimum pause moves by 50 or 100 ms towards the silences
            you reported, and never outside its allowed range.
          </li>
          <li>
            The reports behind an adjustment are used up. The next adjustment needs new reports,
            made on recordings analysed with the new value.
          </li>
          <li>
            Moving a setting back the way it just came needs {data.rules.reversalReports} reports
            rather than {data.rules.minReports}, so it cannot flip back and forth.
          </li>
          <li>
            Marking a pause intentional or accidental never counts towards a setting, and never
            changes a measured pause. The same goes for saying a WPM looks wrong.
          </li>
          <li>
            The numbers are changed by the app&rsquo;s own fixed rules. The AI model has no part in
            it.
          </li>
        </ul>
      </details>

      <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
        <summary className={`cursor-pointer rounded font-medium ${FOCUS_RING}`}>
          Thresholds that feedback never changes
        </summary>
        <table className="mt-2 w-full text-left text-sm">
          <caption className="sr-only">Fixed thresholds</caption>
          <tbody>
            {data.fixed.map((item) => (
              <tr key={item.name} className="border-b border-zinc-100 dark:border-zinc-900">
                <th scope="row" className="py-1.5 pr-4 font-normal">{item.label}</th>
                <td className="py-1.5 text-right tabular-nums whitespace-nowrap">
                  {item.value} {item.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={`mt-2 text-xs ${MUTED}`}>
          A long silence (5 seconds or more) is not the minimum pause: shorter pauses are still
          detected and measured. It only marks where a new section of the recording begins.
        </p>
      </details>

      <ConfirmDialog
        open={confirming}
        title="Reset to the default settings?"
        description="Every setting goes back to its default, and reports that were waiting to count are set aside. Your feedback and your results are kept, and results already made still say which settings produced them. This cannot be undone."
        confirmLabel="Reset to defaults"
        onConfirm={() => {
          store.reset();
          setConfirming(false);
        }}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}

/** The settings in force, what feedback has changed, and the controls to take it back. */
export function CalibrationPanel({ state, store }: { state: FeedbackState; store: FeedbackStore }) {
  const { calibration } = state;
  return (
    <section aria-labelledby="calibration-heading" className="flex flex-col gap-3">
      <div>
        <h2 id="calibration-heading" className="scroll-mt-4 text-lg font-semibold">
          Feedback and calibration
        </h2>
        <p className={`mt-1 text-sm ${MUTED}`}>
          The feedback you give on results gradually tunes a few of the app&rsquo;s settings to
          your recordings: when a silence counts as a pause, and which kinds of correction come
          first. It improves rules of thumb. It does not retrain the speech recogniser, and it
          does not guarantee a perfect analysis. Everything here stays on this device.
        </p>
      </div>
      {calibration.status === "loading" && <p className={`text-sm ${MUTED}`}>Loading the calibration…</p>}
      {calibration.status === "error" && (
        <Notice kind="error" action={<Button onClick={() => store.loadCalibration()}>Try again</Button>}>
          The calibration could not be loaded. {calibration.message}
        </Notice>
      )}
      {calibration.status === "ready" && (
        <CalibrationBody data={calibration.data} state={state} store={store} />
      )}
    </section>
  );
}
