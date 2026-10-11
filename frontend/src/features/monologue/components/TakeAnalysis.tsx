"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { audioSourceFor, regenerationState } from "@/features/general/coaching";
import { BackendNotice } from "@/features/general/components/BackendNotice";
import { CalibrationPanel } from "@/features/general/components/CalibrationPanel";
import { FOCUS_RING, MUTED, Notice, Section } from "@/features/general/components/parts";
import { ReferenceComparison } from "@/features/general/components/ReferenceComparison";
import { Results } from "@/features/general/components/Results";
import { RunPanel } from "@/features/general/components/RunPanel";
import {
  generalApi,
  useBackendHealth,
  useFeedback,
  useGeneralStore,
} from "@/features/general/useGeneralPractice";

import { MONOLOGUES_HREF, practiceHref } from "../links";

type Confirmation = "delete_analysis" | "delete_audio";

const CONFIRM_TEXT: Record<Confirmation, { title: string; description: string; confirmLabel: string }> = {
  delete_analysis: {
    title: "Delete this take?",
    description:
      "Its measurements, its coaching, your feedback on it and, if it was kept, its recording are deleted from this device. This cannot be undone.",
    confirmLabel: "Delete take",
  },
  delete_audio: {
    title: "Delete this recording?",
    description:
      "Only the audio is deleted. The measurements stay under this monologue, but the recording can no longer be played back. This cannot be undone.",
    confirmLabel: "Delete recording",
  },
};

const LINK = `rounded font-medium text-indigo-800 underline underline-offset-4 hover:no-underline dark:text-indigo-300 ${FOCUS_RING}`;

/**
 * Everything measured about one take of a monologue: the comparison with the original,
 * the coaching, the tables behind both, and the controls for saying where the analysis
 * got it wrong. Reached from Daily Practice, where the take was recorded.
 */
export function TakeAnalysis() {
  const analysisId = useSearchParams().get("analysis");
  const router = useRouter();
  const { state, store } = useGeneralStore();
  const { health, refresh: refreshHealth } = useBackendHealth();
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [lastConfirmation, setLastConfirmation] = useState<Confirmation>("delete_analysis");

  // The address says which take to show. It is opened when the address changes and not
  // again after that, so a new revision of the take (a corrected transcript, a fresh
  // analysis) can take its place on screen.
  useEffect(() => {
    if (!analysisId) return;
    const { viewed } = store.getSnapshot();
    const shown =
      viewed.status === "ready"
        ? viewed.analysis.analysisId
        : viewed.status === "none"
          ? null
          : viewed.analysisId;
    if (shown !== analysisId) store.openAnalysis(analysisId);
  }, [analysisId, store]);

  const viewed = state.viewed;
  const analysis = viewed.status === "ready" ? viewed.analysis : null;
  // This page is for a take recorded for a monologue. Anything else has its own screen.
  const take = analysis?.role === "take" && analysis.monologueId ? analysis : null;
  const monologueId = take?.monologueId ?? null;

  // The take's monologue is the one this page is about: its reference is what the take is
  // compared with, and its other takes are the "earlier attempts".
  useEffect(() => {
    if (monologueId) store.watchMonologue(monologueId);
  }, [monologueId, store]);

  const feedback = useFeedback(take?.analysisId ?? null);
  const coach =
    health.status === "reachable"
      ? { status: health.health.coach, model: health.health.coachModel }
      : null;
  const busy = ["submitting", "tracking", "loading_result"].includes(state.run.phase);
  const options = state.options.status === "ready" ? state.options.data : null;
  const monologue = state.monologues.items.find((item) => item.monologueId === monologueId);
  const reference =
    state.monologueId === monologueId && state.referenceDetail.status === "ready"
      ? state.referenceDetail.analysis
      : null;
  const takes = state.takes.monologueId === monologueId ? state.takes.items : [];
  const backHref = monologueId ? practiceHref(monologueId) : MONOLOGUES_HREF;
  const audioSrc = take ? audioSourceFor(take, state.localAudio, generalApi) : null;

  const ask = (kind: Confirmation) => {
    setLastConfirmation(kind);
    setConfirmation(kind);
  };
  const confirm = () => {
    if (take && confirmation === "delete_audio") store.deleteAudio(take.analysisId);
    if (take && confirmation === "delete_analysis") {
      store.deleteAnalysis(take.analysisId);
      router.push(backHref);
    }
    setConfirmation(null);
  };

  return (
    <div className="flex flex-col gap-8">
      <header>
        <p className="text-sm">
          <Link href={backHref} className={LINK}>
            {monologue ? `← Back to practising “${monologue.title}”` : "← Back to your monologues"}
          </Link>
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          {monologue ? `Your take of “${monologue.title}”` : "Your take"}
        </h1>
        <p className="mt-2 text-zinc-700 dark:text-zinc-300">
          The full analysis of one take: where it differs from the original, then every
          measurement, the coaching, and the controls for telling the app what it got wrong.
        </p>
      </header>

      <BackendNotice health={health} onCheckAgain={refreshHealth} />

      {state.notice && (
        <Notice
          kind={state.notice.kind}
          action={<Button onClick={() => store.dismissNotice()}>Dismiss</Button>}
        >
          {state.notice.text}
        </Notice>
      )}

      <RunPanel
        run={state.run}
        kind={state.runKind}
        role={state.runRole}
        coachingFor={state.coachingFor}
        again={state.reanalysisFor !== null}
        store={store}
      />

      {!analysisId && viewed.status === "none" && (
        <p className="text-sm">
          No take is chosen. Open one from the list of takes under{" "}
          <Link href={MONOLOGUES_HREF} className={LINK}>
            a monologue
          </Link>
          .
        </p>
      )}
      {viewed.status === "loading" && <p className={MUTED}>Loading that take…</p>}
      {viewed.status === "error" && (
        <Notice kind="error">That take could not be opened. {viewed.message}</Notice>
      )}
      {analysis && !take && (
        <Notice kind="info">
          {analysis.role === "reference" ? (
            <>This is the original recording of a monologue, not a take. It is studied in step 1 of Daily Practice.</>
          ) : (
            <>
              This recording was not made for a monologue.{" "}
              <Link
                href={`/general?analysis=${encodeURIComponent(analysis.analysisId)}`}
                className={LINK}
              >
                Open it in General Practice
              </Link>
              .
            </>
          )}
        </Notice>
      )}

      {take && (
        <Results
          // A fresh component per analysis, so playback and choices do not carry over.
          key={take.analysisId}
          analysis={take}
          profile={options?.profiles.find((item) => item.id === take.profile)}
          // Earlier attempts to compare with are the other takes of the same monologue.
          history={takes}
          audioSrc={audioSrc}
          referenceSection={
            <Section
              id="reference-heading"
              title="Against the original"
              description="This take set against the original recording of the monologue: where each of you pauses, and how fast each phrase is said. A measured comparison of two real recordings, separate from the coaching above."
            >
              {reference ? (
                <ReferenceComparison
                  // Fresh players and a closed waveform for each pair of recordings.
                  key={`${take.analysisId}-${reference.analysisId}`}
                  comparison={state.comparison}
                  reference={reference}
                  takeId={take.analysisId}
                  takeAudioSrc={audioSrc}
                  referenceAudioSrc={audioSourceFor(reference, state.localAudio, generalApi)}
                  waveforms={state.waveforms}
                  onLoadWaveform={(id) => store.loadWaveform(id)}
                />
              ) : state.referenceDetail.status === "error" ? (
                <Notice kind="error">
                  The original recording could not be opened. {state.referenceDetail.message}
                </Notice>
              ) : (
                <p className={`text-sm ${MUTED}`}>Loading the original recording…</p>
              )}
            </Section>
          }
          coach={coach}
          busy={busy}
          regeneration={regenerationState(state, take.analysisId)}
          onRegenerateCoaching={() => store.regenerateCoaching(take.analysisId)}
          onClose={() => router.push(backHref)}
          onDelete={() => ask("delete_analysis")}
          onDeleteAudio={() => ask("delete_audio")}
          feedback={feedback}
          correction={state.correction}
          onCorrectTranscript={(corrections) => store.correctTranscript(take.analysisId, corrections)}
          onReanalyse={() => store.reanalyse(take.analysisId)}
          onOpenRevision={(id) => store.openAnalysis(id)}
        />
      )}

      <CalibrationPanel state={feedback.state} store={feedback.store} coach={coach} />

      <ConfirmDialog
        open={confirmation !== null}
        {...CONFIRM_TEXT[confirmation ?? lastConfirmation]}
        onConfirm={confirm}
        onCancel={() => setConfirmation(null)}
      />
    </div>
  );
}
