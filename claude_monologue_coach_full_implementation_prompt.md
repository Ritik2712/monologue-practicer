# Claude Code Prompt — Local Monologue Coach Checklist

You are working inside my existing local monologue-coaching app repository. Implement the **five-step daily speaking-practice checklist** below as a real, integrated feature. Do not merely describe the solution or provide snippets: inspect the repository, make the code changes, run the relevant checks, and report exactly what you changed and tested.

## Non-negotiable requirements

1. **100% free to run locally.**
   - Do not add paid APIs, cloud services, hosted databases, subscriptions, analytics, telemetry, or mandatory accounts.
   - Do not send checklist, timer, or session data off-device.
   - Use the project's existing stack and dependencies where possible. Avoid adding dependencies unless necessary; explain any new dependency.
   - Persist data locally. Prefer the project's existing local persistence approach; otherwise use browser `localStorage` for this checklist feature. If the project already has a local SQLite/backend persistence layer, integrate with it instead of creating an unnecessary second store.
2. **Integrate into the existing app.** Do not create a disconnected demo or replace the app's architecture. Inspect the repository first and follow its existing conventions, routes, styling, component patterns, and test setup.
3. **Actually working behavior.** The timer, pause/resume/reset controls, step completion, daily progress, and saved history must work—not be static UI.
4. **Preserve existing functionality.** Do not break or rewrite the audio-upload, original-vs-user recording, acoustic-analysis, or Ollama workflows. Do not invent backend endpoints.
5. **No memory/cloud dependency.** All checklist state and history must stay local to the device/browser unless the existing app already has a strictly local persistence layer.

## The daily five-step routine

The default routine is 15 minutes total:

1. **Listen and observe — 3 minutes**
   - Study the original actor's pauses, emphasis, pace, breathing, pitch, and vocal intensity.
2. **Mark the delivery — 3 minutes**
   - Mark the words to emphasise, where to pause, and where the voice changes.
3. **Perform the monologue — 4 minutes**
   - Practise the delivery, rhythm, and emotional progression—not just the words.
4. **Record and compare — 3 minutes**
   - Compare my recording with the original using the app's audio-analysis screen, when available.
5. **Correct and repeat — 2 minutes**
   - Choose the two biggest delivery mistakes and perform the passage again.

Use these durations as defaults (180, 180, 240, 180, 120 seconds). Keep them easy to change in one clearly defined configuration object, and show the duration for each step.

## UX requirements

Build a polished, responsive checklist view consistent with the existing application. It should include:

- A clear heading such as **Daily Speaking Practice** and a visible **15-minute** total.
- Five checklist items in the order above, each with:
  - checkbox/completion state;
  - step title, short instruction, and planned duration;
  - an obvious current/active step indicator;
  - a timer display in `MM:SS` (or `HH:MM:SS` when needed).
- Overall progress: completed steps out of five and a progress bar.
- Controls: **Start**, **Pause/Resume**, **Reset step**, **Skip step**, and **Reset today's checklist**. Disable controls when their action is invalid.
- A sensible completed state when all five steps are done.
- Accessible labels, keyboard-friendly controls, visible focus, and good contrast.
- Mobile-friendly layout. Avoid unnecessary visual clutter.
- A concise local-only/privacy note, e.g. “Your checklist and progress are saved on this device.”

## Timer behavior — must be robust

Implement a real countdown timer with the following behavior:

- Start begins countdown for the active step's configured duration.
- Pause freezes remaining time; Resume continues from that remaining time.
- Reset step restores that step's full duration and stops its timer.
- Skip step marks the current step skipped (do not falsely mark it completed) and moves to the next unfinished step.
- When a timer reaches zero, stop it and mark that step completed, then move focus/current selection to the next unfinished step. Do not automatically start the next timer unless the app already has a clear, established convention for this.
- The user can manually check/uncheck steps. Manual completion must stop a running timer for that step.
- Prevent duplicate intervals and timer drift. Do not rely on decrementing state once per tick as the source of truth. Store a target end timestamp while running and derive remaining time from it; update the display on an interval. Clean up intervals on unmount and when changing steps.
- Handle background tabs and page refresh sensibly. Recalculate from the target end timestamp on resume/visibility change rather than assuming every interval tick fired.
- Do not allow a completed or skipped step to be accidentally auto-completed by a stale timer.
- Resetting today's checklist must ask for confirmation if there is existing progress, then clear only today's checklist state; it must not delete previous days' history.
- If a timer completes while the page is backgrounded, reconcile its state when the app becomes visible again.

## Local daily progress and history

Persist locally and reliably:

- Each calendar day's completion status for all five steps.
- Completed, skipped, and not-started states distinctly.
- The current step, remaining time, and running/paused status where feasible. On refresh, restore safely; never create duplicate timers. If the stored timer's end timestamp has passed, reconcile the expired timer rather than restarting its full duration.
- The day's completion percentage and whether the full routine was completed.
- A simple history view or section showing recent days (at least the last 7 days) with date, completed steps, and completion percentage.
- Starting a new local calendar day should load a fresh checklist without overwriting the prior day's record. Use the device's local date, not a hard-coded timezone or UTC date slice that can shift the day.
- Handle invalid/corrupt local storage gracefully by falling back to a safe default and showing a useful non-blocking message if appropriate.
- Provide a way to clear checklist history, with explicit confirmation. This must not clear audio files or unrelated app data.

Do not claim persistence is guaranteed across browsers/devices: browser `localStorage` is per browser/profile/device and can be cleared by the user.

## Integration with the monologue-coaching app

- Find the existing navigation and place the checklist somewhere natural, such as a **Practice** or **Daily Routine** tab/section.
- If the app has an audio analysis route, the “Record and compare” step should provide a link/button to that existing route. Inspect the app and use the real route; do not guess a path or invent a new API.
- If there is no suitable route yet, keep the checklist usable and show a disabled/clearly labelled placeholder or a small note that audio comparison can be opened from the app's existing analysis area. Do not fake a working integration.
- Keep the routine language neutral and useful for both Hindi and English monologues.

## Engineering requirements

1. Inspect the repository and identify framework, existing routes, state management, persistence, styling system, and tests before coding.
2. Reuse existing conventions and avoid duplicating shared UI or persistence utilities.
3. Keep the checklist state model typed if the project uses TypeScript.
4. Separate timer logic from presentation where practical; keep it understandable and testable.
5. Use local time correctly to identify a daily record.
6. Add tests for the most important logic using the project's existing test framework. At minimum cover:
   - countdown start, pause/resume, reset, and expiry;
   - step completion and skip semantics;
   - progress calculation;
   - day rollover/history preservation;
   - recovery from persisted state, including expired end timestamps.
7. Run lint, type-check, tests, and build commands that are available in the repository. Fix errors introduced by your changes. If a command cannot be run, state why—do not claim it passed.
8. Do not silently delete unrelated files or modify unrelated features.
9. Do not use mock values to imply that real audio analysis has run. The checklist is independent from the acoustic-analysis engine.

## Suggested data model

Adapt to the project instead of blindly copying this schema:

```ts
type StepStatus = "not_started" | "completed" | "skipped";

type PracticeStep = {
  id: string;
  title: string;
  instruction: string;
  durationSeconds: number;
  status: StepStatus;
};

type DailyPracticeRecord = {
  localDate: string; // local calendar date, e.g. YYYY-MM-DD
  steps: PracticeStep[];
  activeStepId: string | null;
  timerStatus: "idle" | "running" | "paused";
  remainingSeconds: number;
  endsAtEpochMs: number | null;
  startedAtEpochMs?: number;
  updatedAtEpochMs: number;
  routineCompletedAtEpochMs?: number;
};
```

The running timer should use `endsAtEpochMs` as its source of truth. You may change this model if another design is safer or better suited to the existing app.

## Definition of done

The feature is complete only when:

- I can open the checklist inside the existing app.
- I can start, pause, resume, reset, and skip a step.
- A completed timer marks the correct step complete exactly once.
- I can manually complete steps and see progress update immediately.
- Refreshing the page restores today's progress and does not duplicate timers.
- Yesterday's history remains available after the local date changes.
- The app works without paid services or network calls for checklist/timer/history functionality.
- The existing monologue/audio workflows still work.
- Relevant tests, lint, type-check, and build have been run, with truthful results.

## Final response format

After implementing, report:
1. What changed and which files were created/modified.
2. How to access the checklist in the app.
3. How local persistence works and its limitations.
4. Commands/tests run and their actual results.
5. Any remaining limitations or next steps.

Start by inspecting the repository. Then implement the feature fully.


---

# Additional feature: General Practice — Character-style speaking coach

Implement this as a second, separate tab/section inside the existing app, alongside the five-step Daily Speaking Practice checklist. The checklist remains intact. Do not build a disconnected demo: inspect the existing app and integrate this into its real navigation, recording flow, local analysis pipeline, and Ollama feedback workflow.

## Goal

Add a **General Practice** workspace where I can choose a speaking-style reference/preset, record my own performance directly in the app or upload an audio file, analyse it locally, and receive concrete corrections. Support Hindi and English, including Hinglish where the transcription model can handle it.

Provide these three initial fictional-character-inspired presets:

- **Walter White** — controlled, deliberate delivery; measured pace; clear consonants; restrained intensity; intentional pauses.
- **Joker** — expressive, unpredictable rhythm; wider changes in pace, pitch, and intensity; purposeful contrast between calm and energetic sections.
- **Thomas Shelby** — composed, economical delivery; measured pace; low-key intensity; crisp phrasing; deliberate silence.

Treat these as **high-level delivery profiles**, not as a claim that the app can identify or reproduce an actor's exact voice. Do not clone a voice or generate a character's voice. The user records their own voice. Let users choose a preset and optionally select **Custom / neutral analysis**. Explain that the preset is a coaching target, not a rigid rule: a good performance can intentionally depart from it.

## General Practice UX

Add a clearly labelled **General Practice** tab. It should include:

1. **Choose a delivery profile:** Walter White, Joker, Thomas Shelby, and Custom / neutral. Show a short description of the target delivery and the metrics the profile prioritises.
2. **Record in the app:** Start recording, stop, replay, and discard/record again. Show recording duration and microphone permission/error states. Use the browser's supported recording APIs and inspect the current stack before choosing an implementation. Never imply recording succeeded if permission was denied or no audio was captured.
3. **Upload audio:** accept common browser-supported audio formats and validate file type/size with a clear error. Keep the uploaded file local; do not upload audio to a remote service.
4. **Analyse audio:** show a real progress/loading state, handle cancellation or failure, and prevent duplicate analysis submissions.
5. **Results:** show an overall summary, segment-by-segment table/timeline, pause analysis, pace analysis, vocal delivery metrics, and prioritised corrections.
6. **Compare / retry:** let me replay my recording, revisit the exact segments needing work, record/upload another attempt, and compare the new measured metrics with the previous attempt where practical.
7. **Local session history:** keep a small, useful history of prior analyses and selected profile on this device. Reuse the app's existing local database/storage approach; don't introduce a second persistence system without a clear reason. Include delete/clear-history controls with confirmation. Avoid storing raw audio indefinitely by default; if retaining audio is supported, make it explicit and user-controlled.

The UI must work on mobile and desktop, be keyboard-accessible, and match existing styling. Include a local-only privacy note.

## Crucial WPM and pause rules

**Do not calculate speaking WPM by dividing the entire clip's word count by total clip duration without also accounting for pauses.** Long silences can make that number misleading. Display distinct metrics with explicit labels and formulas:

- **Segment WPM (primary):** for each detected speech segment, count aligned spoken words and divide by that segment's actual speech-active duration in minutes. Exclude pauses between segments. Example: 12 words spoken over 4.0 seconds = 180 WPM for that segment.
- **Articulation rate / speech-active WPM:** total spoken words divided by total speech-active time, excluding detected pauses. Label this clearly; it is not the same as whole-clip average.
- **Whole-clip WPM (optional secondary):** total spoken words divided by the full clip duration, including pauses. If shown, label it **including pauses** and never use it alone to judge speaking speed.
- **Pause-aware segmentation:** detect speech regions with a real voice activity detection (VAD) or equivalent local signal-based method. Segment around silence/pause boundaries, with configurable thresholds where practical. Do not treat every tiny gap between words as a dramatic pause. Make thresholds visible/configurable if exposed in the UI.
- **Word timestamps:** use the existing local transcription/alignment stack if available; otherwise inspect and add an appropriate free, locally runnable method. Do not invent word timestamps. If precise word alignment is unavailable, report the limitation and use clearly labelled approximate segment-level estimates instead.
- **Robust edge cases:** handle clips with no speech, very short segments, overlapping/noisy speech, clipping, and uncertain transcription. Avoid division by zero. Mark unreliable estimates rather than displaying false precision.
- Display the formulas or a small tooltip/help text so the user understands what each WPM number means.

## Required metrics

Include at least the following real, measured outputs when the local pipeline supports them:

### Pace and segmentation
- WPM for each speech segment, with start/end timestamps and word count.
- Overall speech-active WPM (pauses excluded).
- Optional whole-clip WPM (pauses included), clearly distinguished.
- Pace variation across segments (e.g. range and/or standard deviation), with a simple explanation.
- Segment durations and any segments that are unusually rushed or slow relative to the selected profile or the user's own session baseline.

### Pauses and breathing
- Average pause duration, median pause duration, longest pause, and number of detected pauses.
- Pause ratio: total detected pause time divided by clip duration.
- A timestamped list of significant pauses, with replay/jump-to-segment controls if supported.
- Breathing: only report actual detected breath events if the signal-processing approach can reasonably identify them. Otherwise show a cautious **possible breath / inhale-like sound** estimate or explicitly say breath detection is unavailable; never pretend silence alone proves breathing.

### Voice and expression
- Relative loudness/energy trend over time, and peaks/valleys. Use a suitable signal measure such as RMS energy and explain that it is not calibrated real-world loudness.
- Pitch range/variation only when voiced frames are reliable; handle Hindi/English and gender-independent voice pitch without assuming a target pitch based on character.
- Emphasis candidates based on measurable changes such as local energy, pitch, duration, or stressed-word timing. Label them as candidates, not objective truth.
- Optional filler-word counts (e.g. “um”, “uh”, “like” and supported Hindi fillers) only when transcription is confident.
- A short delivery summary describing pace consistency, pause placement, vocal variation, and clarity, grounded in computed values.

Do not overload the screen with dozens of charts. Prioritise a readable summary, a segment table/timeline, and a small number of useful visualisations.

## Profile-aware evaluation

Use the selected profile to generate coaching criteria, not fake reference measurements. If no reference audio is provided, the app must **not** claim to compare the user's voice against a measured canonical recording of Walter White, Joker, or Thomas Shelby. Instead, compare the user's measured performance with qualitative targets associated with that profile.

If the user later supplies a reference recording they have rights to use, the app may compare measured timing and acoustic features between the two clips using the same local pipeline. Keep these separate:
- **Measured self metrics** from the user's recording.
- **Qualitative profile targets** for the selected character-inspired preset.
- **Measured reference comparison** only when an actual reference file was supplied and analysed.

Make the comparison honest and transparent. Don't infer emotion as fact from audio alone. Emotion labels, if included, must be presented as tentative interpretations, not objective measurements.

## AI feedback requirements

Use the app's existing local Ollama setup (prefer the configured local model, such as Llama 3.1 8B if that is what the project already uses) to interpret a structured analysis result and produce useful corrections. Do not send audio to the LLM unless the existing architecture explicitly requires a local-only method and the model truly supports it. Prefer sending:
- transcript, if available;
- timestamps and speech-segment boundaries;
- computed WPM and pause metrics;
- measured energy/pitch trends and confidence values;
- selected profile and its qualitative coaching criteria.

The AI feedback must include:
1. **Top 3 corrections**, ordered by expected impact.
2. **Exact timestamps/segments** to practise, with a short reason grounded in measured data.
3. **A concrete drill** for each correction (e.g. repeat one segment at a target pace, shorten a specific pause, or make emphasis more deliberate).
4. **What is already working**, supported by measurements rather than generic praise.
5. **Next-take targets** based on this recording and selected profile.
6. A clear note when transcription, word alignment, VAD, pitch, or breath estimates are uncertain/unavailable.

Strict grounding rule: the LLM may interpret supplied measurements but must not invent WPM, timestamps, pause lengths, pitch values, detected breaths, or acoustic observations. Calculate numeric metrics in deterministic code, not in the prompt. Validate the LLM output against the analysis payload where feasible. If the local model is unavailable, still show the measured analysis and a useful local fallback/error message; don't silently switch to a cloud API.

## Local-first technical requirements

- Keep the whole workflow free and locally runnable. No paid API keys, cloud transcription, external analytics, or remote audio uploads.
- Reuse existing local tools where available: for example, faster-whisper for local transcription, a local forced-alignment option when feasible, VAD for speech/pause segmentation, librosa for energy and signal features, Parselmouth/Praat for pitch where appropriate, and Ollama for textual coaching. Inspect the repository and environment before selecting tools; don't blindly add every library.
- Keep audio processing in the existing Python/FastAPI backend if that is the current architecture. Reuse actual existing endpoints and schemas where possible; do not invent routes without implementing them end to end.
- Return a typed, timestamped JSON analysis structure. Include units, confidence/quality flags, and whether each value is measured or estimated.
- Use chunked processing for longer recordings if required. Validate upload size/duration, clean up temporary files on success/failure/cancellation, and avoid leaking microphone recordings to logs.
- Keep raw audio and analysis history local. Document model downloads/storage requirements and the fact that local inference still needs the relevant model installed.
- Gracefully handle missing dependencies/models and unsupported browsers. Give actionable setup instructions rather than crashing.
- Add tests for WPM calculations (especially pause exclusion), segment boundaries, pause statistics, silence/no-speech, edge cases, and the grounding/format of AI feedback. Run the available lint, type-check, tests, and build; report actual outcomes.

## Suggested typed analysis contract

Adapt to the existing project rather than copying this blindly. Keep the data contract explicit and versionable:

```ts
type MetricQuality = "measured" | "estimated" | "unavailable";

type SpeechSegment = {
  id: string;
  startSeconds: number;
  endSeconds: number;
  speechActiveSeconds: number;
  transcript?: string;
  wordCount?: number;
  segmentWpm?: number;
  quality: MetricQuality;
  confidence?: number;
};

type PauseEvent = {
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  significance: "short" | "medium" | "long";
};

type MetricValue = {
  value: number | null;
  unit: string;
  quality: MetricQuality;
  note?: string;
};

type GeneralPracticeAnalysis = {
  schemaVersion: 1;
  sessionId: string;
  createdAt: string;
  language: "en" | "hi" | "hinglish" | "unknown";
  profile: "walter_white" | "joker" | "thomas_shelby" | "custom";
  durationSeconds: number;
  transcript?: string;
  segments: SpeechSegment[];
  pauses: PauseEvent[];
  metrics: {
    speechActiveWpm: MetricValue;
    wholeClipWpm: MetricValue;
    averagePauseSeconds: MetricValue;
    medianPauseSeconds: MetricValue;
    longestPauseSeconds: MetricValue;
    pauseCount: MetricValue;
    pauseRatio: MetricValue;
    paceVariation: MetricValue;
    energyVariation?: MetricValue;
    pitchRangeHz?: MetricValue;
    fillerWordCount?: MetricValue;
  };
  warnings: string[];
};
```

## Additional definition of done

- A working General Practice tab exists alongside, not instead of, Daily Speaking Practice.
- I can select Walter White, Joker, Thomas Shelby, or Custom / neutral.
- I can record in the app, stop, replay, discard, and record again.
- I can upload a local audio file and analyse it without sending audio to a cloud service.
- The results show pause-aware segment WPM and speech-active WPM, plus clearly labelled pause-inclusive whole-clip WPM if available.
- I can see average/median/longest pause, pause count, pause ratio, and useful voice/pace metrics with honest quality labels.
- The app returns specific, timestamped, actionable corrections based on measured results and the selected profile.
- Numeric results are computed by code; the LLM does not fabricate acoustic metrics.
- Analysis can be repeated and compared locally; history and deletion work.
- Existing daily checklist, audio comparison, and other features remain functional.
- Tests cover pause-aware WPM and critical failure cases; final report lists actual test/build outcomes.

Continue by inspecting the existing repository, then implement both the existing Daily Speaking Practice checklist and this General Practice feature in the same app. Do not stop at a plan or mock UI.


---

# Additional feature: Feedback-driven automatic calibration

Add a **Feedback / Calibration** panel to General Practice. The app should learn from the user's corrections and gradually adjust its analysis thresholds locally, so its pause segmentation and coaching become better suited to this user's recordings. This is a real adaptive settings feature, not merely a feedback textbox.

## User feedback after every analysis

Let the user quickly correct the analysis with options such as:

- "This was an intentional dramatic pause."
- "This pause was accidental / I lost my place."
- "You missed a pause."
- "That was not a pause; I was still speaking."
- "This segment was incorrectly split."
- "These two segments should be separate."
- "The WPM estimate looks too high / too low."
- "Transcription is incorrect."
- "This correction was useful / not useful."

Where possible, let the user select the exact timestamp, pause, segment, transcript word, or coaching suggestion being rated. Provide an optional short note, but keep feedback quick and structured. Never require feedback before the user can use the app.

## How calibration should work

1. Save each feedback event locally with the relevant analysis/session ID, affected timestamp or segment ID, feedback category, current configuration version, and the relevant measured signal features.
2. Use feedback to adjust **the relevant setting only**. Examples:
   - Repeated "you missed a pause" reports can cautiously lower the pause-onset/minimum-duration threshold or adjust VAD sensitivity.
   - Repeated "this was not a pause" reports can cautiously increase the pause threshold or reduce over-segmentation.
   - "Intentional dramatic pause" should teach the coaching layer that the pause may be intentional; it should not automatically be deleted from pause statistics or from the measured recording.
   - "Accidental pause / lost my place" should mark the pause as non-deliberate for coaching, but must not change the acoustic measurement itself.
   - "WPM too high/low" should first trigger a review of transcription, word timestamps, and speech-active duration; do not blindly multiply WPM by an arbitrary correction factor.
   - Incorrect transcription feedback should update the corrected transcript only if the user supplies or confirms the correction; rerun word-based metrics from that corrected text where alignment allows.
3. Start with conservative, transparent rules. Use a small bounded adjustment per accepted feedback event; do not let one click radically change the whole model. Prefer a rolling history or confidence-weighted counts to a single global permanent threshold.
4. Only auto-adjust settings when there is enough consistent feedback. Until then, retain defaults and label the system as still calibrating. Show a concise explanation such as: "Pause threshold adjusted from 500 ms to 600 ms after repeated false-pause reports."
5. Keep a visible **Current calibration** section showing the active values, what changed, why it changed, and confidence/sample count. Provide **Undo last adjustment**, **Reset to defaults**, and a way to disable adaptive calibration.
6. Keep separate profiles/settings for different analysis modes or selected delivery presets only if real evidence supports that separation. Do not overfit each character profile to a handful of recordings.
7. Calibration and feedback data must remain on-device. Never transmit recordings or feedback to an external service. The local LLM may summarise feedback, but deterministic code must apply and validate numeric setting changes.

## Initial defaults and safety bounds

Use the following as starting values unless the existing code has a more defensible implementation:

- Minimum pause candidate: 500 ms.
- Long-silence / automatic new-segment boundary: 5,000 ms initially, matching the goal of treating a 5–6 second gap as a likely deliberate or structural break. Do not assume every such gap is intentional; label it as a long silence and let feedback refine its coaching interpretation.
- Minimum segment duration for a reliable WPM display: 2,000 ms.
- Minimum segment word count for a reliable WPM display: 3 words.
- Optional WPM outlier warning: flag values above 180 WPM for review, rather than silently clamping or changing the measured value.

Expose the active threshold values in an advanced/calibration view. Use explicit, validated minimum/maximum bounds for every adaptive setting. Avoid thresholds that can oscillate dramatically or make adjacent recordings incomparable without notice. Record a configuration version with each analysis so the app can explain which settings produced the result.

Important distinction: the **5,000 ms long-silence boundary is not the minimum pause threshold**. Shorter pauses must still be detected and measured. A long-silence boundary is used for segmentation/flagging; pause metrics should retain all valid pauses according to the pause detector's own threshold.

## Evaluation and reliability

- Add tests proving that feedback changes only the intended setting, stays within bounds, and can be undone/reset.
- Add tests for the difference between measured acoustic pauses and the user's label of whether a pause was intentional.
- Add tests confirming that WPM is recalculated from the corrected transcript / alignment rather than patched by an arbitrary multiplier.
- Keep old analysis results reproducible: preserve their original metrics and calibration version. If recalculating an old session with new settings, show it as a new analysis revision rather than silently overwriting historical measurements.
- Do not claim the app has "learned" from one or two noisy feedback events. Show feedback count and calibration confidence.
- Make the final UI explain that user feedback improves heuristics and coaching over time; it does not magically retrain the transcription model or guarantee perfect analysis.

## Additional definition of done

- I can flag false/missed pauses, incorrect segment boundaries, WPM problems, transcription mistakes, and useful/unhelpful coaching.
- The app stores feedback and calibration locally.
- Repeated consistent feedback can automatically adjust relevant bounded settings, with a visible reason and confidence.
- I can undo a calibration change, reset defaults, or disable auto-calibration.
- A long pause remains part of pause statistics even when I label it intentional; the label affects coaching interpretation, not measured audio duration.
- Previous session results remain traceable to the settings version that produced them.


---

# Additional feature: Background analysis jobs + optional waveform overlay comparison

Implement only these two additions for now. Do not add the other future ideas (loop practice, blind comparison, delivery map, etc.) unless already present. Preserve every existing requirement and existing feature.

## Feature A — Background analysis jobs for slow local processing

### Goal
Audio analysis and local LLM feedback can take a while on a user's machine. The UI must remain responsive and users should not have to keep a long HTTP request open while transcription, acoustic analysis, and local Ollama inference run.

### Implementation approach
- Inspect the existing repository, current backend, deployment assumptions, and dependencies before choosing a job system.
- Use a background job queue with Celery only if it is compatible with the existing architecture and worth the extra operational complexity.
- If Celery is selected, use Redis as its broker/result backend where appropriate, with clear local setup instructions and configuration via environment variables. Do not assume Redis or Celery is already installed.
- For a strictly single-user local desktop/local-development workflow, consider a simpler persistent job runner (e.g. FastAPI BackgroundTasks only for lightweight work, or a SQLite-backed job table plus a managed worker process for long-running work). Do not use FastAPI BackgroundTasks as the sole solution if the work must survive backend restarts.
- Avoid adding Celery + Redis merely for fashion. Choose the smallest robust architecture that supports long-running jobs, status polling, cancellation where safely possible, error reporting, and restart recovery.
- Keep the job API end to end; do not build a queue mock or a progress bar with fake percentages.

### Required job lifecycle
1. User submits an analysis. The API validates the audio and creates a job/session record, then returns promptly with a stable `jobId`.
2. A worker processes the local audio pipeline: transcription/alignment if available, VAD/segmentation, deterministic acoustic metrics, and local Ollama feedback.
3. The UI shows real job states such as `queued`, `running`, `succeeded`, `failed`, and `cancelled`, with stage names such as `transcribing`, `measuring_audio`, and `generating_feedback`.
4. The UI polls a lightweight status endpoint or uses an existing suitable push mechanism. Prefer simple, reliable polling if that is enough. Avoid a tight polling loop.
5. On completion, the UI fetches and renders the real analysis result. On failure, show a useful error and a retry action.
6. Allow cancellation before work starts and at safe cancellation points during processing. Do not claim a running subprocess/model inference was cancelled unless it really was stopped or allowed to terminate safely.
7. Persist job state so a backend restart does not leave the UI waiting forever. On startup, recover queued jobs; mark orphaned/incomplete jobs failed or requeue them safely according to the actual job implementation.
8. Prevent duplicate submissions from repeated clicks; use an idempotency/session key if appropriate.
9. Ensure temporary audio files are cleaned up after success, failure, or cancellation, while preserving only user-requested retained audio.
10. Keep logs free of raw audio, transcripts where unnecessary, credentials, and sensitive local paths.

### Performance and reliability
- Do not run multiple memory-heavy transcription or LLM jobs concurrently by default on modest local hardware. Configure a conservative worker concurrency (often one job at a time) and document how to tune it.
- Keep CPU/GPU model workloads bounded. Avoid launching multiple duplicate Ollama calls for the same job.
- Show honest progress by stage, not invented exact percentage completion unless the pipeline exposes measurable progress.
- Keep local-only behaviour: no cloud queue, external APIs, paid services, or remote audio uploads.
- Make setup, start, stop, health-check, and troubleshooting commands explicit in the README or relevant developer docs.
- Add tests for job transitions, duplicate submission, status polling, failure recovery, cancellation semantics, and cleanup.

### Definition of done for Feature A
- Submitting analysis returns a job ID promptly, even if the local model takes a long time.
- UI stays responsive and shows actual queued/running/stage/completed/failed states.
- A failed job has a visible explanation and can be retried.
- Backend restarts do not silently strand jobs.
- The app runs using the documented local setup, without requiring any paid or cloud service.
- The chosen queue/worker approach is justified in the final report; if Celery/Redis is not warranted, document the simpler alternative and why.

## Feature B — Optional visual waveform overlay (for visual comparison only)

### Goal
Let the user optionally view the source/reference audio waveform and their own recorded waveform overlaid or aligned on a common timeline. This is a visual aid only. It must not feed into WPM calculation, pause classification, scoring, or AI conclusions.

### UI
- Add an optional checkbox/toggle, default off, labelled clearly, for example **Show waveform comparison (visual only)**.
- When unchecked, hide the waveform visualisation and avoid expensive waveform rendering/precomputation where practical.
- When checked and a source/reference clip and user clip are both available, display their waveforms with clearly distinct labels and a legend.
- Allow hiding either series independently if practical, while keeping the main toggle.
- Keep the graph responsive for longer audio by downsampling/min-max envelope aggregation or another appropriate approach; do not render every raw audio sample as a DOM node.
- Use a free plotting solution compatible with the current stack, or a lightweight custom Canvas/SVG waveform renderer if that is simpler. Prefer existing dependencies if suitable; do not add a paid charting library.
- Make time units clear (seconds) and align clips sensibly. If the recordings have different lengths, show their real durations and do not stretch one waveform to falsely imply a timing match. If visual alignment is offset-adjustable, make the offset explicit and user-controlled.
- Include accessible labels/legend and a non-graph summary of each clip's duration so the visual feature is not the only way to understand the comparison.
- If only one clip exists, show its waveform alone and explain that a second recording is needed for overlay comparison.
- Handle missing/unsupported audio, empty clips, decode errors, and large files gracefully.

### Strict separation from analysis
- Waveform overlay is strictly for visualisation. It must never be used as evidence for WPM, transcription, speech boundaries, pauses, emotion, pitch, or loudness metrics.
- Analysis metrics must continue to come from the defined local transcription/VAD/acoustic analysis pipeline.
- Do not compare the two waveforms by amplitude as if they were calibrated loudness: recording gain, microphone distance, device hardware, compression, and normalisation may differ.
- Label amplitude as **relative waveform amplitude** and state that it is not calibrated loudness. Do not auto-normalise the two clips in a way that visually implies equal loudness; if normalisation is used only to make shapes visible, make that fact explicit and keep it isolated to the visual layer.
- The waveform must not change any results or adaptive calibration values when toggled on/off.
- Ensure enabling/disabling the visual does not alter job payloads or trigger re-analysis.

### Definition of done for Feature B
- Waveform comparison is optional and default-off.
- Source/reference and user recordings can be displayed with clear labels on a common seconds timeline.
- Different durations remain honestly represented.
- The graph is responsive and accessible enough for the existing app.
- Toggling it has no effect on analysis results, WPM, pause metrics, or feedback calibration.
- All plotting is free and local, with no audio sent to an external charting or analytics service.

## Final implementation order
1. Inspect the existing repository and document the chosen background-job architecture.
2. Implement durable job creation, worker processing, status UI, retry/failure, cancellation semantics, and tests.
3. Implement the optional visual-only waveform overlay and its toggle.
4. Run available tests, lint, type checks, and build; report actual results and any remaining limitations.


---

# Final stack decision — authoritative (overrides conflicting generic stack suggestions above)

Use this stack for the current implementation:

- **Frontend:** React with Next.js, using the repository's existing Next.js setup if present.
- **Backend:** Python with FastAPI.
- **LLM calls for now:** use the existing direct/local model integration (for example, call the configured local Ollama API directly from the backend). Use ordinary direct model calls; **do not add LiteLLM yet**.
- **Later extensibility:** keep the LLM call behind a small backend service/interface so LiteLLM can be introduced later without rewriting the analysis pipeline. This is an architectural seam only; do not install or configure LiteLLM now.
- **Local processing:** transcription, audio feature extraction, analysis jobs, and persistence remain local. Do not introduce paid APIs, cloud inference, remote queues, or external audio uploads.

## Background jobs under this stack

The app must still support durable long-running analysis jobs, but choose the simplest reliable local architecture compatible with the repository:

1. Prefer a **SQLite-backed job table plus a dedicated FastAPI-adjacent worker process** for this single-user local app if no suitable durable queue already exists. Keep the worker separate from request handlers so long-running analysis does not block the API.
2. Do not add Celery + Redis by default. Only choose them if repository inspection reveals a concrete need that the simpler local worker cannot meet; explain the reason and local setup impact before implementing that choice.
3. Do not use in-memory-only FastAPI `BackgroundTasks` as the sole job system for long-running work that must survive backend restarts.
4. Expose job submission, status, retry, and safe cancellation through implemented FastAPI endpoints and connect them to the Next.js UI end to end.
5. Keep worker concurrency conservative by default (typically one heavy local audio/LLM job at a time) and document how to start/stop the API and worker locally.

## Implementation constraints

- Inspect the existing repository first and preserve established conventions. If the current repository already has a compatible React/Next.js frontend, FastAPI backend, or local model client, reuse them rather than scaffolding duplicates.
- Do not replace the stack with Streamlit, Chainlit, or another frontend/backend framework.
- Do not introduce LiteLLM, Celery, Redis, Docker services, or other infrastructure just because it is mentioned as a possible option elsewhere in this prompt. Follow the concrete decisions in this section.
- For LLM feedback, send structured measured analysis to the configured local model and validate its output. Numeric audio metrics must still be calculated deterministically by code.
- If the existing repository differs materially from this stack, report the discrepancy and make the smallest safe migration/integration plan rather than silently rewriting the project.
- Update the README with the chosen stack, local prerequisites, model requirements, environment variables, and exact commands to start the Next.js frontend, FastAPI API, and worker.


---

# User's current local development environment — use these settings

The user has successfully connected to their local PostgreSQL 16 instance through pgAdmin. Use this as the current local PostgreSQL connection configuration if the repository is configured for PostgreSQL.

## Confirmed local environment

- OS: macOS
- PostgreSQL service: Homebrew `postgresql@16` — **started**
- PostgreSQL CLI version observed: `psql (PostgreSQL) 16.12 (Homebrew)`
- Local host: `localhost`
- Port: `5432`
- Maintenance database: `postgres`
- Working login role: `ritikmahajan`
- PostgreSQL 17 Homebrew service currently reports `error 1`; PostgreSQL 16 is the working service. Do not uninstall, reset, or migrate either version automatically. PostgreSQL 17 is not required for this project unless repository inspection proves otherwise.
- Redis is installed and Homebrew reports its service as started, but **do not add Celery/Redis as the job architecture by default**. Follow the authoritative stack decision above: prefer a durable SQLite-backed job table plus a separate local worker unless the repository has a concrete reason to use a different solution.

## Connection settings for local development

Use these values as environment/configuration defaults for PostgreSQL, not as hard-coded credentials:

```dotenv
DB_HOST=localhost
DB_PORT=5432
DB_NAME=monologue_coach
DB_USER=ritikmahajan
DB_PASSWORD=
```

`DB_PASSWORD` must be supplied by the user through a local `.env` file or environment variable if password authentication is enabled. **Never guess, invent, commit, print, or include the user's actual database password in this prompt or repository.** Add `.env` to `.gitignore` and provide a safe `.env.example` with an empty placeholder.

The user has successfully connected to pgAdmin with the local `ritikmahajan` role after addressing the missing `postgres` role issue. Do not assume the role `postgres` exists. Use the actual configured role `ritikmahajan` for local PostgreSQL connection settings unless the user changes it.

## Database choice for the app

The original architecture prefers SQLite for a simple single-user local-first application. The user has now also installed/started local PostgreSQL 16 and connected via pgAdmin. During repository inspection:

1. Check the existing application's configured database and migrations first.
2. If the application already uses PostgreSQL, use the local settings above and create/use a dedicated database named `monologue_coach` only if it does not already exist.
3. If the repository is new or already designed around SQLite, do not migrate to PostgreSQL just because pgAdmin is available. Prefer the simplest consistent option and explain the choice. The app may use PostgreSQL for application data while using a small SQLite job store only if there is a clear architectural reason; avoid two databases without justification.
4. Never drop, recreate, or reset an existing PostgreSQL cluster/database to make the app work. Do not change global authentication configuration or create superuser roles automatically.
5. If the `monologue_coach` database does not exist and PostgreSQL is selected, show the user the exact SQL to create it or create it only through an explicitly documented, safe setup step. Keep the user's existing databases and roles untouched.
6. Use migrations for schema changes; do not rely on manually creating application tables through pgAdmin.
7. Document the selected database, setup commands, and environment variables in the README.

The database password is intentionally not recorded here; ask the user to enter it locally if needed.
