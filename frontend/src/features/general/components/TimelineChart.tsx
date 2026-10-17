"use client";

import { useId, useState, type KeyboardEvent } from "react";

import { formatNumber, formatSpan, formatTimecode, PAUSE_LABELS } from "../format";
import { deliveryWpmOf } from "../pace";
import {
  formatTick,
  labelFits,
  loudnessScale,
  momentAt,
  nearestPoint,
  pointTimes,
  timeTicks,
  unit,
  type Moment,
} from "../timeline";
import type { AnalysisResult } from "../types";
import { useElementWidth } from "../useGeneralPractice";

type TimelineChartProps = {
  analysis: AnalysisResult;
  /** Where playback is, if a recording is available to play. */
  playheadSeconds: number | null;
  /** Called when a moment is chosen. Omitted when there is no recording to play. */
  onSeek?: (seconds: number) => void;
};

// Layout, in pixels. The loudness panel sits above the speech strip on one shared time axis.
const LEFT = 44;
const RIGHT = 12;
const TOP = 18;
const LOUDNESS_HEIGHT = 120;
const STRIP_TOP = TOP + LOUDNESS_HEIGHT + 34;
const STRIP_HEIGHT = 16;
const AXIS_TOP = STRIP_TOP + STRIP_HEIGHT + 10;
const HEIGHT = AXIS_TOP + 22;
const TOOLTIP_WIDTH = 220;

function describeMoment(moment: Moment): { title: string; detail: string } {
  switch (moment.kind) {
    case "segment": {
      const { segment } = moment;
      const wpm = deliveryWpmOf(segment);
      const pace =
        wpm === null
          ? "no words recognised"
          : `${formatNumber(wpm)} WPM${segment.reliable ? "" : " (estimate)"}`;
      return {
        title: `Segment ${segment.index + 1}`,
        detail: `${pace} · ${formatSpan(segment.endSeconds - segment.startSeconds)}`,
      };
    }
    case "pause":
      return {
        title: "Pause",
        detail: `${formatSpan(moment.pause.durationSeconds)} · ${PAUSE_LABELS[moment.pause.significance].toLowerCase()}`,
      };
    case "silence":
      return {
        title: "Silence",
        detail: moment.position === "before" ? "before the first word" : "after the last word",
      };
    case "empty":
      return { title: "No speech", detail: "none was detected" };
  }
}

export function TimelineChart({ analysis, playheadSeconds, onSeek }: TimelineChartProps) {
  const { ref, width } = useElementWidth<HTMLDivElement>();
  const descriptionId = useId();
  const [cursor, setCursor] = useState<number | null>(null);

  const duration = analysis.durationSeconds;
  const { values, secondsPerPoint } = analysis.energyTimeline;
  const plotWidth = Math.max(0, width - LEFT - RIGHT);
  const ready = plotWidth > 0 && duration > 0;

  const scale = loudnessScale(values);
  const times = pointTimes(analysis);
  const x = (seconds: number) => LEFT + (seconds / duration) * plotWidth;
  const y = (db: number) => TOP + (1 - unit(db, scale.minDb, scale.maxDb)) * LOUDNESS_HEIGHT;
  const floorY = TOP + LOUDNESS_HEIGHT;

  const line = values.map((db, index) => `${index === 0 ? "M" : "L"}${x(times[index]).toFixed(1)},${y(db).toFixed(1)}`).join(" ");
  const area = values.length
    ? `${line} L${x(times[times.length - 1]).toFixed(1)},${floorY} L${x(times[0]).toFixed(1)},${floorY} Z`
    : "";

  const cursorSeconds = cursor === null ? null : times[cursor];
  const cursorMoment = cursorSeconds === null ? null : momentAt(cursorSeconds, analysis);
  const described = cursorMoment ? describeMoment(cursorMoment) : null;
  const hoveredSegmentId = cursorMoment?.kind === "segment" ? cursorMoment.segment.id : null;

  const pointFromEvent = (event: { clientX: number; currentTarget: SVGRectElement }) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const seconds = ((event.clientX - bounds.left) / bounds.width) * duration;
    return nearestPoint(seconds, secondsPerPoint, values.length);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (values.length === 0) return;
    const last = values.length - 1;
    const current = cursor ?? 0;
    const step = event.shiftKey ? 10 : 1;
    let next: number | null = null;
    if (event.key === "ArrowRight") next = Math.min(last, current + step);
    else if (event.key === "ArrowLeft") next = Math.max(0, current - step);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    else if ((event.key === "Enter" || event.key === " ") && cursor !== null && onSeek) {
      event.preventDefault();
      onSeek(times[cursor]);
      return;
    }
    if (next !== null) {
      event.preventDefault();
      setCursor(next);
    }
  };

  const readout =
    cursorSeconds !== null && described
      ? `${formatTimecode(cursorSeconds)}, loudness ${formatNumber(values[cursor as number])} dB, ${described.title}, ${described.detail}`
      : "No moment selected";

  return (
    <figure className="viz-root rounded-lg border border-zinc-200 bg-[var(--viz-surface)] p-3 sm:p-4 dark:border-zinc-800">
      <figcaption className="text-sm font-semibold text-[var(--viz-ink)]">
        Loudness and speech over time
      </figcaption>
      <p id={descriptionId} className="mt-1 text-xs text-[var(--viz-ink-secondary)]">
        Top: loudness in dB relative to this recording&apos;s own scale, not calibrated loudness.
        Bottom: where you were speaking; the gaps are pauses. ▲ and ▼ mark phrases faster or
        slower than your typical pace.{" "}
        {onSeek ? "Click, or press Enter, to play from a moment. " : ""}
        Every value here is also in the tables below.
      </p>

      <div
        ref={ref}
        role="slider"
        tabIndex={0}
        aria-label="Timeline of the recording. Use the left and right arrow keys to move through it."
        aria-describedby={descriptionId}
        aria-valuemin={0}
        aria-valuemax={Number(duration.toFixed(1))}
        aria-valuenow={Number((cursorSeconds ?? 0).toFixed(1))}
        aria-valuetext={readout}
        onKeyDown={onKeyDown}
        onBlur={() => setCursor(null)}
        className="relative mt-3 rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400"
      >
        {ready && (
          <svg width={width} height={HEIGHT} role="presentation" className="block select-none">
            {/* Loudness panel */}
            <text
              x={LEFT - 6}
              y={0}
              textAnchor="end"
              dominantBaseline="hanging"
              className="fill-[var(--viz-ink-secondary)] text-[11px]"
            >
              dB
            </text>
            {scale.ticks.map((tick) => (
              <g key={tick}>
                <line
                  x1={LEFT}
                  x2={LEFT + plotWidth}
                  y1={y(tick)}
                  y2={y(tick)}
                  stroke={tick === scale.minDb ? "var(--viz-axis)" : "var(--viz-grid)"}
                  strokeWidth={1}
                />
                <text
                  x={LEFT - 6}
                  y={y(tick)}
                  textAnchor="end"
                  dominantBaseline="middle"
                  className="fill-[var(--viz-ink-secondary)] text-[11px] tabular-nums"
                >
                  {tick}
                </text>
              </g>
            ))}
            <path d={area} fill="var(--viz-series-1)" opacity={0.1} />
            <path
              d={line}
              fill="none"
              stroke="var(--viz-series-1)"
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {/* Speech strip */}
            <text
              x={LEFT}
              y={STRIP_TOP - 20}
              dominantBaseline="middle"
              className="fill-[var(--viz-ink-secondary)] text-[11px]"
            >
              Speech
            </text>
            {analysis.segments.map((segment) => {
              const left = x(segment.startSeconds);
              const segmentWidth = Math.max(1, x(segment.endSeconds) - left);
              const marker =
                segment.paceVsTypical === "faster" ? "▲" : segment.paceVsTypical === "slower" ? "▼" : null;
              const opacity = hoveredSegmentId === null || hoveredSegmentId === segment.id ? 1 : 0.55;
              // A phrase that holds pauses is drawn as its runs of speaking, joined by a
              // thin line, so the pauses inside it show as gaps and it still reads as one.
              const runs = (analysis.stretches ?? []).filter((run) => run.segmentId === segment.id);
              const pieces = runs.length > 1 ? runs : [segment];
              return (
                <g key={segment.id}>
                  {runs.length > 1 && (
                    <rect
                      x={left}
                      y={STRIP_TOP + STRIP_HEIGHT / 2 - 1.5}
                      width={segmentWidth}
                      height={3}
                      fill="var(--viz-series-1)"
                      opacity={opacity * 0.6}
                    />
                  )}
                  {pieces.map((piece) => {
                    const pieceLeft = x(piece.startSeconds);
                    const pieceWidth = Math.max(1, x(piece.endSeconds) - pieceLeft);
                    return (
                      <rect
                        key={piece.startSeconds}
                        x={pieceLeft}
                        y={STRIP_TOP}
                        width={pieceWidth}
                        height={STRIP_HEIGHT}
                        rx={Math.min(4, pieceWidth / 2)}
                        fill="var(--viz-series-1)"
                        opacity={opacity}
                      />
                    );
                  })}
                  {marker && segmentWidth >= 10 && (
                    <text
                      x={left + segmentWidth / 2}
                      y={STRIP_TOP - 6}
                      textAnchor="middle"
                      className="fill-[var(--viz-ink)] text-[10px]"
                    >
                      {marker}
                    </text>
                  )}
                </g>
              );
            })}
            {analysis.pauses
              .filter((pause) => pause.significance !== "short")
              .map((pause) => {
                const left = x(pause.startSeconds);
                const gap = x(pause.endSeconds) - left;
                const label = formatSpan(pause.durationSeconds);
                // A label that does not fit is left out; the tooltip and the table carry it.
                if (!labelFits(label, gap)) return null;
                return (
                  <text
                    key={pause.id}
                    x={left + gap / 2}
                    y={STRIP_TOP + STRIP_HEIGHT / 2}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className="fill-[var(--viz-ink-secondary)] text-[11px] tabular-nums"
                  >
                    {label}
                  </text>
                );
              })}

            {/* Shared time axis */}
            <line x1={LEFT} x2={LEFT + plotWidth} y1={AXIS_TOP} y2={AXIS_TOP} stroke="var(--viz-axis)" strokeWidth={1} />
            {timeTicks(duration, Math.max(2, Math.floor(plotWidth / 70))).map((tick) => (
              <g key={tick}>
                <line x1={x(tick)} x2={x(tick)} y1={AXIS_TOP} y2={AXIS_TOP + 4} stroke="var(--viz-axis)" strokeWidth={1} />
                <text
                  x={x(tick)}
                  y={AXIS_TOP + 8}
                  textAnchor="middle"
                  dominantBaseline="hanging"
                  className="fill-[var(--viz-ink-secondary)] text-[11px] tabular-nums"
                >
                  {formatTick(tick, duration)}
                </text>
              </g>
            ))}

            {playheadSeconds !== null && playheadSeconds > 0 && playheadSeconds <= duration && (
              <line
                x1={x(playheadSeconds)}
                x2={x(playheadSeconds)}
                y1={TOP}
                y2={AXIS_TOP}
                stroke="var(--viz-ink)"
                strokeWidth={1}
              />
            )}
            {cursorSeconds !== null && (
              <g>
                <line
                  x1={x(cursorSeconds)}
                  x2={x(cursorSeconds)}
                  y1={TOP}
                  y2={AXIS_TOP}
                  stroke="var(--viz-ink-secondary)"
                  strokeWidth={1}
                />
                {/* The ring in the surface colour keeps the dot legible on top of the line. */}
                <circle
                  cx={x(cursorSeconds)}
                  cy={y(values[cursor as number])}
                  r={4}
                  fill="var(--viz-series-1)"
                  stroke="var(--viz-surface)"
                  strokeWidth={2}
                />
              </g>
            )}

            {/* One hit area over the whole plot: the pointer only has to be near a moment. */}
            <rect
              x={LEFT}
              y={TOP}
              width={plotWidth}
              height={AXIS_TOP - TOP}
              fill="transparent"
              className={onSeek ? "cursor-pointer" : "cursor-crosshair"}
              onPointerMove={(event) => setCursor(pointFromEvent(event))}
              onPointerDown={(event) => setCursor(pointFromEvent(event))}
              onPointerLeave={() => setCursor(null)}
              onClick={(event) => {
                const index = pointFromEvent(event);
                if (index >= 0) onSeek?.(times[index]);
              }}
            />
          </svg>
        )}

        {ready && cursorSeconds !== null && described && (
          <div
            className="pointer-events-none absolute top-1 rounded-md border border-zinc-200 bg-white px-2.5 py-1.5 text-xs shadow-md dark:border-zinc-700 dark:bg-zinc-900"
            style={{
              width: TOOLTIP_WIDTH,
              // To the right of the crosshair, or to its left when there is no room.
              left: Math.max(
                0,
                x(cursorSeconds) + 10 + TOOLTIP_WIDTH <= width
                  ? x(cursorSeconds) + 10
                  : x(cursorSeconds) - 10 - TOOLTIP_WIDTH,
              ),
            }}
          >
            <p className="font-semibold tabular-nums text-zinc-950 dark:text-white">
              {formatTimecode(cursorSeconds)}
            </p>
            <p className="mt-0.5 flex items-center gap-1.5 text-zinc-700 dark:text-zinc-300">
              <span aria-hidden="true" className="inline-block h-0.5 w-3 rounded bg-[var(--viz-series-1)]" />
              <span className="font-semibold tabular-nums text-zinc-950 dark:text-white">
                {formatNumber(values[cursor as number])} dB
              </span>
              loudness
            </p>
            <p className="mt-0.5 text-zinc-700 dark:text-zinc-300">
              <span className="font-semibold text-zinc-950 dark:text-white">{described.title}</span>{" "}
              · {described.detail}
            </p>
          </div>
        )}
      </div>
    </figure>
  );
}
