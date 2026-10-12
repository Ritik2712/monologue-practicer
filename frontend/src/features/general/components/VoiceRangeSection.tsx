"use client";

import type { ReactNode } from "react";

import { formatNumber, formatTimecode, UNAVAILABLE } from "../format";
import type { AnalysisResult, SpeechSegment, VoicePlacement, VoiceRange } from "../types";
import {
  BAND_LABEL,
  edgesOf,
  goalSummary,
  HEARD_AS,
  isOutsideGoal,
  MARKER_LABEL,
  phraseCountsText,
  positionText,
  rangeText,
  scalePosition,
  scaleWidths,
  type Edges,
  type VoiceScale,
} from "../voiceRange";
import { MUTED, Notice, QualityBadge, Section } from "./parts";

type VoiceRangeSectionProps = {
  analysis: AnalysisResult;
  /** True for a monologue's original: someone else is speaking, and there is no goal. */
  reference?: boolean;
  /** A button that plays a stretch of the recording, as the tables above use. */
  playButton: (label: string, start: number, end?: number) => ReactNode;
};

const SCALES: { scale: VoiceScale; title: string; hint: string }[] = [
  {
    scale: "pitch",
    title: "Pitch",
    hint: "The note the voice speaks on: its median, in Hz.",
  },
  {
    scale: "resonance",
    title: "Resonance",
    hint: "How deep or bright the voice sounds, apart from its note: the average spacing of its formants, in Hz. Lower is deeper.",
  },
];

/**
 * Where the voice sat, in pitch and in resonance: for the whole recording and phrase by
 * phrase. Everything here was measured and placed by the backend. It describes a sound and
 * says nothing about who is speaking.
 */
export function VoiceRangeSection({ analysis, reference = false, playButton }: VoiceRangeSectionProps) {
  const voice = analysis.voiceRange;
  const whose = reference ? "the" : "your";

  if (!voice) {
    return (
      <Section id="voice-range-heading" title={`Where ${whose} voice sits`}>
        <p className={`text-sm ${MUTED}`}>
          {analysis.segments.length === 0
            ? "No speech was detected, so there is no voice to place."
            : "This result was made before the app measured where a voice sits. Analysing the recording again adds it, if the recording was kept."}
        </p>
      </Section>
    );
  }

  const summary = goalSummary(voice, analysis.segments);
  const measured = analysis.segments.filter((segment) => segment.voice != null);

  return (
    <Section
      id="voice-range-heading"
      title={`Where ${whose} voice sits`}
      description="Two things decide how a voice is heard: its pitch, and its resonance. Each is placed in one of three ranges. The ranges describe how a voice is typically heard, not who is speaking, and they are this app's own rough ranges."
    >
      {summary && <Notice kind="info">{summary}</Notice>}

      <div className="grid gap-3 sm:grid-cols-2">
        {SCALES.map(({ scale, title, hint }) => (
          <PlacementCard
            key={scale}
            title={title}
            hint={hint}
            placement={voice[scale]}
            edges={edgesOf(voice.bands, scale)}
            missing={
              scale === "resonance"
                ? (voice.resonanceNote ?? "Resonance could not be measured.")
                : "There was too little clearly voiced sound to measure pitch."
            }
            note={scale === "resonance" ? voice.resonanceNote : null}
          />
        ))}
      </div>

      {voice.marker && (
        <p className="text-sm">
          <span className="font-medium">Together: {MARKER_LABEL[voice.marker].toLowerCase()}.</span>{" "}
          {HEARD_AS[voice.marker]}
          {voice.formantsHz && (
            <span className={MUTED}>
              {" "}
              The resonance figure rests on typical formants of{" "}
              {voice.formantsHz.map((hz) => formatNumber(hz, 0)).join(", ")} Hz.
            </span>
          )}
        </p>
      )}

      {measured.length > 0 && (
        <div>
          <p className="text-sm font-medium">
            Phrase by phrase{" "}
            <span className={`font-normal ${MUTED}`}>({phraseCountsText(voice.phrases)})</span>
          </p>
          <div className="mt-1 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <caption className="sr-only">Where the voice sat in each phrase</caption>
              <thead className={MUTED}>
                <tr className="border-b border-zinc-200 dark:border-zinc-800">
                  <th scope="col" className="py-2 pr-3 font-medium">Phrase</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Pitch</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Resonance</th>
                  <th scope="col" className="py-2 pr-3 font-medium">Together</th>
                  <th scope="col" className="py-2 font-medium">Listen</th>
                </tr>
              </thead>
              <tbody>
                {analysis.segments.map((segment) => (
                  <PhraseRow
                    key={segment.id}
                    segment={segment}
                    voice={voice}
                    playButton={playButton}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <details className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800">
        <summary className="cursor-pointer rounded font-medium focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600 dark:focus-visible:outline-indigo-400">
          The ranges, and what the percentage means
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          <RangeTable voice={voice} />
          <p className={MUTED}>
            The percentage is a position inside a range, not a probability. In the lower and
            higher ranges, 0% is the edge next to the neutral range and 100% is the far end. In
            the neutral range, 100% is the middle and 0% is either edge.
          </p>
          <p className={MUTED}>
            Limits: a phrase shorter than about two and a half seconds gives an estimate of
            resonance. In testing, a few such phrases in a hundred landed in the opposite
            range, and about one in seven in the neutral range. Background hiss makes
            resonance read brighter than the voice is, so with a noisy background it is
            labelled an estimate or left out. The resonance ranges were set from synthesised
            voices, not from recordings of people. Acting, a cold or a different microphone
            all move these figures.
          </p>
        </div>
      </details>
    </Section>
  );
}

type PlacementCardProps = {
  title: string;
  hint: string;
  placement: VoicePlacement | null;
  edges: Edges | null;
  /** Said in place of a value when there is none. */
  missing: string;
  /** Why the value is an estimate, when it is. */
  note: string | null;
};

function PlacementCard({ title, hint, placement, edges, missing, note }: PlacementCardProps) {
  return (
    <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className={`text-sm ${MUTED}`}>{title}</p>
        {placement && <QualityBadge quality={placement.quality} />}
        {!placement && <QualityBadge quality="unavailable" />}
      </div>
      {placement ? (
        <>
          <p className="mt-1 text-2xl font-semibold">
            {formatNumber(placement.valueHz, 0)}
            <span className={`ml-1 text-sm font-normal ${MUTED}`}>Hz</span>
          </p>
          <p className="mt-1 text-sm">
            <span className="font-medium">{BAND_LABEL[placement.band]}</span>
            {edges && <span className={MUTED}> ({rangeText(placement.band, edges)})</span>},{" "}
            {positionText(placement)}.
          </p>
          {edges && <ScaleBar valueHz={placement.valueHz} edges={edges} />}
          <p className={`mt-2 text-xs ${MUTED}`}>
            {hint}
            {placement.quality === "estimated" && note ? ` ${note}` : ""}
          </p>
        </>
      ) : (
        <>
          <p className="mt-1 text-2xl font-semibold">{UNAVAILABLE}</p>
          <p className={`mt-1 text-xs ${MUTED}`}>{missing}</p>
        </>
      )}
    </div>
  );
}

/** The three ranges as a bar, with a mark where the value falls. A picture of the sentence above it. */
function ScaleBar({ valueHz, edges }: { valueHz: number; edges: Edges }) {
  const widths = scaleWidths(edges);
  const parts = [
    { band: "lower", label: "Lower", style: "bg-zinc-300 dark:bg-zinc-700" },
    { band: "neutral", label: "Neutral", style: "bg-zinc-200 dark:bg-zinc-800" },
    { band: "higher", label: "Higher", style: "bg-zinc-300 dark:bg-zinc-700" },
  ] as const;
  return (
    <div aria-hidden="true" className="mt-3">
      <div className="relative">
        <div className="flex h-2 gap-px overflow-hidden rounded-full">
          {parts.map((part) => (
            <div key={part.band} className={part.style} style={{ width: `${widths[part.band] * 100}%` }} />
          ))}
        </div>
        <div
          className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-indigo-700 dark:bg-indigo-400"
          style={{ left: `${scalePosition(valueHz, edges) * 100}%` }}
        />
      </div>
      <div className={`mt-1 flex text-[11px] ${MUTED}`}>
        {parts.map((part) => (
          <span key={part.band} className="truncate text-center" style={{ width: `${widths[part.band] * 100}%` }}>
            {part.label}
          </span>
        ))}
      </div>
    </div>
  );
}

function placementCell(placement: VoicePlacement | null | undefined) {
  if (!placement) return <span className={MUTED}>{UNAVAILABLE}</span>;
  return (
    <>
      <span className="tabular-nums">{formatNumber(placement.valueHz, 0)} Hz</span>
      <span className={`block text-xs ${MUTED}`}>
        {BAND_LABEL[placement.band]}, {placement.percent}%
        {placement.quality === "estimated" && " · estimate"}
      </span>
    </>
  );
}

type PhraseRowProps = {
  segment: SpeechSegment;
  voice: VoiceRange;
  playButton: VoiceRangeSectionProps["playButton"];
};

function PhraseRow({ segment, voice, playButton }: PhraseRowProps) {
  const placed = segment.voice;
  const outside = isOutsideGoal(placed?.marker, voice.goal);
  return (
    <tr
      className={`border-b border-zinc-100 align-top dark:border-zinc-900 ${
        outside ? "bg-amber-50 dark:bg-amber-950/40" : ""
      }`}
    >
      <th scope="row" className="py-2 pr-3 font-normal">
        <span className="font-medium">{segment.index + 1}</span>{" "}
        <span className={`text-xs ${MUTED}`}>at {formatTimecode(segment.startSeconds)}</span>
        {segment.transcript && (
          <span className={`block text-xs break-words ${MUTED}`}>{segment.transcript}</span>
        )}
      </th>
      <td className="py-2 pr-3">{placementCell(placed?.pitch)}</td>
      <td className="py-2 pr-3">{placementCell(placed?.resonance)}</td>
      <td className="py-2 pr-3">
        {placed?.marker ? MARKER_LABEL[placed.marker] : <span className={MUTED}>Not measured</span>}
        {outside && (
          <span className="block text-xs font-medium text-amber-900 dark:text-amber-200">
            Outside your goal
          </span>
        )}
      </td>
      <td className="py-2">
        {playButton(`Play phrase ${segment.index + 1}`, segment.startSeconds, segment.endSeconds)}
      </td>
    </tr>
  );
}

function RangeTable({ voice }: { voice: VoiceRange }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">The ranges pitch and resonance are placed in</caption>
        <thead className={MUTED}>
          <tr className="border-b border-zinc-200 dark:border-zinc-800">
            <th scope="col" className="py-2 pr-3 font-medium">Scale</th>
            <th scope="col" className="py-2 pr-3 font-medium">Lower range</th>
            <th scope="col" className="py-2 pr-3 font-medium">Neutral range</th>
            <th scope="col" className="py-2 font-medium">Higher range</th>
          </tr>
        </thead>
        <tbody>
          {SCALES.map(({ scale, title }) => {
            const edges = edgesOf(voice.bands, scale);
            if (!edges) return null;
            return (
              <tr key={scale} className="border-b border-zinc-100 dark:border-zinc-900">
                <th scope="row" className="py-2 pr-3 font-normal">{title}</th>
                <td className="py-2 pr-3">
                  {rangeText("lower", edges)}
                  <span className={`block text-xs ${MUTED}`}>100% at {edges.lowEnd} Hz</span>
                </td>
                <td className="py-2 pr-3">
                  {rangeText("neutral", edges)}
                  <span className={`block text-xs ${MUTED}`}>
                    100% at {(edges.neutralFrom + edges.neutralTo) / 2} Hz
                  </span>
                </td>
                <td className="py-2">
                  {rangeText("higher", edges)}
                  <span className={`block text-xs ${MUTED}`}>100% at {edges.highEnd} Hz</span>
                </td>
              </tr>
            );
          })}
          <tr>
            <th scope="row" className={`py-2 pr-3 font-normal ${MUTED}`}>Typically heard as</th>
            <td className="py-2 pr-3">a masculine voice</td>
            <td className="py-2 pr-3">either</td>
            <td className="py-2">a feminine voice</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
