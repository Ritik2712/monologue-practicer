"use client";

import { useId, useState } from "react";

import { formatSpan, formatTimecode } from "../format";
import type { WaveformState } from "../generalStore";
import { formatTick } from "../timeline";
import { useElementWidth } from "../useGeneralPractice";
import {
  bandPath,
  clampOffset,
  outlineColumns,
  ownTime,
  peakOf,
  sharedSpan,
  spanTicks,
  timeAtPixel,
} from "../waveform";
import { FOCUS_RING, MUTED, Notice } from "./parts";

type WaveformComparisonProps = {
  /** The reference's outline, if there is a reference and its outline has been fetched. */
  reference: WaveformState | undefined;
  /** Your take's outline, if there is a take. */
  take: WaveformState | undefined;
  referenceLabel: string;
};

type Layout = "stacked" | "overlaid";

const LEFT = 8;
const RIGHT = 8;
const TOP = 8;
const LANE_HEIGHT = 84;
const LANE_GAP = 10;
// Room above each lane for its name, so the name never sits on top of the wave.
const LABEL_HEIGHT = 16;
const AXIS_HEIGHT = 26;

/**
 * Two sound waves on one timeline, to look at. Nothing is measured from this picture, and
 * turning it on or off changes no result.
 */
export function WaveformComparison({ reference, take, referenceLabel }: WaveformComparisonProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const summaryId = useId();
  const [showReference, setShowReference] = useState(true);
  const [showTake, setShowTake] = useState(true);
  const [layout, setLayout] = useState<Layout>("stacked");
  const [offset, setOffset] = useState(0);
  const [stretch, setStretch] = useState(false);
  const [pointer, setPointer] = useState<number | null>(null);

  const referenceOutline = reference?.status === "ready" ? reference.data : null;
  const takeOutline = take?.status === "ready" ? take.data : null;
  const loading = reference?.status === "loading" || take?.status === "loading";

  const problems = [
    describeProblem(reference, "the reference"),
    describeProblem(take, "your take"),
  ].filter((text): text is string => text !== null);

  if (!referenceOutline && !takeOutline) {
    return (
      <div className="flex flex-col gap-2">
        {loading && <p className={`text-sm ${MUTED}`}>Loading the waveforms…</p>}
        {problems.map((text) => (
          <Notice key={text} kind="info">
            {text}
          </Notice>
        ))}
        {!loading && problems.length === 0 && (
          <p className={`text-sm ${MUTED}`}>There is no recording to draw yet.</p>
        )}
      </div>
    );
  }

  const both = referenceOutline !== null && takeOutline !== null;
  // A shift only means something when there are two recordings to line up.
  const shift = both ? offset : 0;
  const span = sharedSpan(
    referenceOutline?.durationSeconds ?? null,
    takeOutline?.durationSeconds ?? null,
    shift,
  );
  const plotWidth = Math.max(0, width - LEFT - RIGHT);
  const drawReference = referenceOutline !== null && showReference;
  const drawTake = takeOutline !== null && showTake;
  const overlaid = layout === "overlaid" && both;
  const lanes = overlaid ? 1 : Number(referenceOutline !== null) + Number(takeOutline !== null);
  // Overlaid, the legend alone says which is which; stacked, each lane is named above it.
  const labelHeight = overlaid ? 0 : LABEL_HEIGHT;
  const laneStep = labelHeight + LANE_HEIGHT + LANE_GAP;
  const plotHeight = lanes * laneStep - LANE_GAP;
  const height = TOP + plotHeight + AXIS_HEIGHT;
  const referenceTop = TOP + labelHeight;
  const takeTop = overlaid || referenceOutline === null ? TOP + labelHeight : TOP + laneStep + labelHeight;

  const gain = (outline: NonNullable<typeof referenceOutline>) => {
    const peak = peakOf(outline);
    return stretch && peak > 0 ? 1 / peak : 1;
  };
  const x = (seconds: number) =>
    LEFT + ((seconds - span.fromSeconds) / (span.toSeconds - span.fromSeconds)) * plotWidth;
  const ticks = spanTicks(span, plotWidth < 420 ? 4 : 8);

  const pointerSeconds = pointer === null ? null : timeAtPixel(pointer, span, plotWidth);
  const inReference =
    pointerSeconds !== null && referenceOutline
      ? ownTime(pointerSeconds, referenceOutline.durationSeconds)
      : null;
  const inTake =
    pointerSeconds !== null && takeOutline
      ? ownTime(pointerSeconds, takeOutline.durationSeconds, shift)
      : null;

  const summary = [
    referenceOutline && `${referenceLabel}: ${formatSpan(referenceOutline.durationSeconds)}.`,
    takeOutline && `Your take: ${formatSpan(takeOutline.durationSeconds)}.`,
    both &&
      (shift === 0
        ? "Both start at 0 on the timeline."
        : `Your take is shifted ${Math.abs(shift).toFixed(1)} s ${shift > 0 ? "later" : "earlier"}.`),
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <figure className="viz-root rounded-lg border border-zinc-200 bg-[var(--viz-surface)] p-3 sm:p-4 dark:border-zinc-800">
      <figcaption className="text-sm font-semibold text-[var(--viz-ink)]">
        Waveforms on one timeline
      </figcaption>
      <p className="mt-1 text-xs text-[var(--viz-ink-secondary)]">
        A picture to look at, nothing more. No figure on this page is taken from it. Height is
        relative waveform amplitude, not calibrated loudness: it depends on the microphone and
        the recording, so the two cannot be compared by height. Each recording keeps its real
        length.
      </p>
      <p id={summaryId} className="mt-2 text-sm text-[var(--viz-ink)]">
        {summary}
      </p>

      {/* Legend, which is also how either wave is hidden. */}
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[var(--viz-ink)]">
        {referenceOutline && (
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={showReference}
              onChange={(event) => setShowReference(event.target.checked)}
              className={`h-4 w-4 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
            />
            <span aria-hidden="true" className="h-3 w-3 rounded-sm bg-[var(--viz-series-2)]" />
            {referenceLabel}
          </label>
        )}
        {takeOutline && (
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={showTake}
              onChange={(event) => setShowTake(event.target.checked)}
              className={`h-4 w-4 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
            />
            <span aria-hidden="true" className="h-3 w-3 rounded-sm bg-[var(--viz-series-1)]" />
            Your take
          </label>
        )}
      </div>

      <div ref={ref} className="relative mt-3">
        {plotWidth > 0 && (
          <svg
            width={width}
            height={height}
            role="img"
            aria-label="Waveforms of the recordings on a shared timeline in seconds"
            aria-describedby={summaryId}
            className="block select-none"
          >
            {/* The middle line of each lane is silence. */}
            {Array.from({ length: lanes }, (_, lane) => {
              const middle = TOP + lane * laneStep + labelHeight + LANE_HEIGHT / 2;
              return (
                <line
                  key={lane}
                  x1={LEFT}
                  x2={LEFT + plotWidth}
                  y1={middle}
                  y2={middle}
                  stroke="var(--viz-grid)"
                  strokeWidth={1}
                />
              );
            })}
            {drawReference && (
              <path
                d={bandPath(
                  outlineColumns(referenceOutline, span, plotWidth, 0, gain(referenceOutline)),
                  LEFT,
                  referenceTop,
                  LANE_HEIGHT,
                )}
                fill="var(--viz-series-2)"
                opacity={overlaid ? 0.7 : 1}
              />
            )}
            {drawTake && (
              <path
                d={bandPath(
                  outlineColumns(takeOutline, span, plotWidth, shift, gain(takeOutline)),
                  LEFT,
                  takeTop,
                  LANE_HEIGHT,
                )}
                fill="var(--viz-series-1)"
                opacity={overlaid ? 0.7 : 1}
              />
            )}
            {/* Each lane says which recording it is, so colour is never the only cue. */}
            {!overlaid && drawReference && (
              <text
                x={LEFT}
                y={referenceTop - labelHeight + 2}
                dominantBaseline="hanging"
                className="fill-[var(--viz-ink-secondary)] text-[11px]"
              >
                {referenceLabel}
              </text>
            )}
            {!overlaid && drawTake && (
              <text
                x={LEFT}
                y={takeTop - labelHeight + 2}
                dominantBaseline="hanging"
                className="fill-[var(--viz-ink-secondary)] text-[11px]"
              >
                Your take
              </text>
            )}

            {/* Time axis */}
            <line
              x1={LEFT}
              x2={LEFT + plotWidth}
              y1={TOP + plotHeight + 4}
              y2={TOP + plotHeight + 4}
              stroke="var(--viz-axis)"
              strokeWidth={1}
            />
            {ticks.map((tick) => (
                <text
                  key={tick}
                  x={x(tick)}
                  y={TOP + plotHeight + 10}
                  textAnchor={tick === 0 && span.fromSeconds === 0 ? "start" : "middle"}
                  dominantBaseline="hanging"
                  className="fill-[var(--viz-ink-secondary)] text-[11px] tabular-nums"
                >
                  {tick < 0 ? `−${formatTick(-tick, span.toSeconds)}` : formatTick(tick, span.toSeconds)}
                </text>
            ))}

            {pointer !== null && (
              <line
                x1={LEFT + pointer}
                x2={LEFT + pointer}
                y1={TOP}
                y2={TOP + plotHeight}
                stroke="var(--viz-ink)"
                strokeWidth={1}
                opacity={0.5}
              />
            )}
            <rect
              x={LEFT}
              y={TOP}
              width={plotWidth}
              height={plotHeight}
              fill="transparent"
              onPointerMove={(event) => {
                const bounds = event.currentTarget.getBoundingClientRect();
                setPointer(Math.min(plotWidth, Math.max(0, event.clientX - bounds.left)));
              }}
              onPointerLeave={() => setPointer(null)}
            />
          </svg>
        )}
      </div>
      <p className="mt-1 min-h-5 text-xs text-[var(--viz-ink-secondary)]" aria-hidden="true">
        {pointerSeconds === null
          ? "Time in seconds. Move over the picture to read a moment."
          : [
              referenceOutline &&
                `${referenceLabel}: ${inReference === null ? "not sounding" : formatTimecode(inReference)}`,
              takeOutline && `Your take: ${inTake === null ? "not sounding" : formatTimecode(inTake)}`,
            ]
              .filter(Boolean)
              .join(" · ")}
      </p>

      {/* Controls that change the picture only. */}
      <div className="mt-3 flex flex-col gap-3 border-t border-zinc-200 pt-3 text-sm text-[var(--viz-ink)] dark:border-zinc-800">
        {both ? (
          <>
            <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-1">
              <legend className="sr-only">How the two waveforms are arranged</legend>
              {(["stacked", "overlaid"] as const).map((value) => (
                <label key={value} className="flex cursor-pointer items-center gap-2">
                  <input
                    type="radio"
                    name="waveform-layout"
                    checked={layout === value}
                    onChange={() => setLayout(value)}
                    className={`h-4 w-4 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
                  />
                  {value === "stacked" ? "One above the other" : "Overlaid"}
                </label>
              ))}
            </fieldset>
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="waveform-offset">Shift your take by</label>
              <input
                id="waveform-offset"
                type="number"
                step={0.1}
                value={offset}
                onChange={(event) =>
                  setOffset(
                    clampOffset(
                      Number(event.target.value),
                      referenceOutline.durationSeconds,
                      takeOutline.durationSeconds,
                    ),
                  )
                }
                className={`h-9 w-24 rounded-md border border-zinc-300 bg-white px-2 tabular-nums dark:border-zinc-700 dark:bg-zinc-900 ${FOCUS_RING}`}
              />
              <span>seconds</span>
              <span className="text-xs text-[var(--viz-ink-secondary)]">
                Your choice, for lining up by eye. The app does not line them up for you, and a
                shift changes only this picture.
              </span>
            </div>
          </>
        ) : (
          <p className="text-xs text-[var(--viz-ink-secondary)]">
            Only one recording is drawn. A second one is needed to compare them:{" "}
            {referenceOutline ? "analyse a take." : "choose or add a reference recording."}
          </p>
        )}
        <label className="flex cursor-pointer items-start gap-2">
          <input
            type="checkbox"
            checked={stretch}
            onChange={(event) => setStretch(event.target.checked)}
            className={`mt-0.5 h-4 w-4 shrink-0 accent-indigo-700 dark:accent-indigo-400 ${FOCUS_RING}`}
          />
          <span>
            Stretch each waveform to its own loudest point
            <span className="block text-xs text-[var(--viz-ink-secondary)]">
              Makes the shape of a quiet recording visible. It hides any real difference in
              level between the two, so read shapes only.
            </span>
          </span>
        </label>
      </div>

      {loading && <p className="mt-2 text-xs text-[var(--viz-ink-secondary)]">Loading…</p>}
      {problems.map((text) => (
        <p key={text} className="mt-2 text-xs text-[var(--viz-ink-secondary)]">
          {text}
        </p>
      ))}
    </figure>
  );
}

function describeProblem(waveform: WaveformState | undefined, whose: string): string | null {
  if (waveform?.status === "missing") {
    return `No waveform is stored for ${whose}: it was analysed before waveforms were added. Analysing it again will store one.`;
  }
  if (waveform?.status === "error") {
    return `The waveform of ${whose} could not be loaded. ${waveform.message}`;
  }
  return null;
}
