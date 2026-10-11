"use client";

import { Button } from "@/components/Button";
import { audioSourceFor } from "@/features/general/coaching";
import type { FeedbackTools } from "@/features/general/components/FeedbackControls";
import { MUTED, Notice } from "@/features/general/components/parts";
import { Results } from "@/features/general/components/Results";
import { RunPanel } from "@/features/general/components/RunPanel";
import { madeWithOlderSettings } from "@/features/general/feedback";
import type { GeneralState, GeneralStore } from "@/features/general/generalStore";
import { generalApi } from "@/features/general/useGeneralPractice";

type ListenToolsProps = {
  state: GeneralState;
  store: GeneralStore;
  /** Feedback on the original recording, and the calibration it feeds. */
  feedback: FeedbackTools;
  /** True while an analysis is in progress, when another cannot be started. */
  busy: boolean;
};

/**
 * Step 1: the original recording, to listen to and study. Its pauses, pace, loudness and
 * pitch as measured, and the controls to correct what the app got wrong about it.
 */
export function ListenTools({ state, store, feedback, busy }: ListenToolsProps) {
  const detail = state.referenceDetail;
  const calibration =
    feedback.state.calibration.status === "ready" ? feedback.state.calibration.data : null;

  const run = state.runRole === "reference" && (
    <RunPanel
      run={state.run}
      kind={state.runKind}
      role={state.runRole}
      coachingFor={state.coachingFor}
      again={state.reanalysisFor !== null}
      store={store}
    />
  );

  if (detail.status !== "ready") {
    return (
      <div className="flex flex-col gap-3">
        {run}
        {detail.status === "error" ? (
          <Notice kind="error">The original recording could not be opened. {detail.message}</Notice>
        ) : (
          <p className={`text-sm ${MUTED}`}>Loading the original recording…</p>
        )}
      </div>
    );
  }

  const reference = detail.analysis;
  const outdated = madeWithOlderSettings(reference, calibration);

  return (
    <div className="flex flex-col gap-4">
      {run}
      {outdated && (
        <Notice kind="info">
          <p>
            The original was measured when a silence counted as a pause from {outdated.then} ms.
            Your feedback has since moved that to {outdated.now} ms, so takes analysed now are
            cut differently from it.
          </p>
          {reference.audioRetained ? (
            <div className="mt-2">
              <Button
                disabled={busy}
                onClick={() => store.reanalyse(reference.analysisId, "reference")}
              >
                Measure the original again
              </Button>
              <p className={`mt-1 ${MUTED}`}>
                That stores a new revision of it, measured with the settings as they are now,
                and your takes are then compared with that one. The earlier revision is kept.
              </p>
            </div>
          ) : (
            <p className={`mt-1 ${MUTED}`}>
              Its recording was not kept, so it cannot be measured again. To measure it with
              the settings as they are now, add the monologue again from its file.
            </p>
          )}
        </Notice>
      )}
      <Results
        // A fresh view per revision, so playback and open forms do not carry over.
        key={reference.analysisId}
        mode="reference"
        analysis={reference}
        profile={undefined}
        history={[]}
        audioSrc={audioSourceFor(reference, state.localAudio, generalApi)}
        coach={null}
        busy={busy}
        regeneration={{ status: "idle" }}
        onRegenerateCoaching={() => {}}
        onClose={() => {}}
        onDelete={() => {}}
        onDeleteAudio={() => store.deleteAudio(reference.analysisId)}
        feedback={feedback}
        correction={state.correction}
        onCorrectTranscript={(corrections) =>
          store.correctTranscript(reference.analysisId, corrections)
        }
        // Opening another revision means studying, and comparing with, that one.
        onOpenRevision={(analysisId) => store.selectReference(analysisId)}
      />
    </div>
  );
}
