/**
 * The shapes of the JSON the backend sends. They mirror `backend/app/schemas.py`; when a
 * field changes there, it changes here.
 */

export type Quality = "measured" | "estimated" | "unavailable";
export type Profile = "walter_white" | "joker" | "thomas_shelby" | "custom";
export type LanguageHint = "auto" | "en" | "hi" | "hinglish";
export type JobStatusName = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobStage =
  | "preparing_audio"
  | "detecting_speech"
  | "transcribing"
  | "measuring_audio"
  | "generating_feedback";
/** "analysis" measures a recording. "coaching" only rewrites the coaching of a stored one. */
export type JobKind = "analysis" | "coaching";
/**
 * What a recording is for. A "take" is your own attempt. A "reference" is a recording you
 * supply to compare takes against, such as the original performance.
 */
export type Role = "take" | "reference";
export type PauseSignificance = "short" | "medium" | "long";
export type PaceVsTypical = "typical" | "faster" | "slower";

export type MetricValue = {
  /** Null whenever quality is "unavailable". A missing number is never shown as zero. */
  value: number | null;
  unit: string;
  quality: Quality;
  note: string | null;
};

export type SpeechSegment = {
  id: string;
  index: number;
  sectionIndex: number;
  startSeconds: number;
  endSeconds: number;
  speechActiveSeconds: number;
  transcript: string | null;
  wordCount: number | null;
  segmentWpm: number | null;
  paceVsTypical: PaceVsTypical | null;
  quality: Quality;
  reliable: boolean;
  flags: string[];
  confidence: number | null;
  meanEnergyDb: number | null;
  energyDeltaDb: number | null;
  medianPitchHz: number | null;
  pitchDeltaSemitones: number | null;
};

export type PauseEvent = {
  id: string;
  index: number;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  significance: PauseSignificance;
  afterSegmentId: string;
  beforeSegmentId: string;
  startsNewSection: boolean;
};

export type WordTiming = {
  text: string;
  startSeconds: number;
  endSeconds: number;
  confidence: number | null;
  segmentId: string | null;
};

export type EmphasisCandidate = {
  text: string;
  startSeconds: number;
  endSeconds: number;
  segmentId: string | null;
  reasons: ("louder" | "higher_pitch")[];
  energyDeltaDb: number | null;
  pitchDeltaSemitones: number | null;
};

export type Hesitation = { text: string; startSeconds: number };

export type EnergyTimeline = { secondsPerPoint: number; unit: string; values: number[] };

export type AnalysisWarning = { code: string; message: string };

export type LanguageInfo = {
  code: string;
  source: "declared" | "detected" | "none";
  confidence: number | null;
};

export type MetricName =
  | "totalWordCount"
  | "speechActiveSeconds"
  | "speechActiveWpm"
  | "wholeClipWpm"
  | "paceVariation"
  | "paceMinWpm"
  | "paceMaxWpm"
  | "typicalSegmentWpm"
  | "pauseCount"
  | "totalPauseSeconds"
  | "averagePauseSeconds"
  | "medianPauseSeconds"
  | "longestPauseSeconds"
  | "pauseRatio"
  | "leadingSilenceSeconds"
  | "trailingSilenceSeconds"
  | "energyVariation"
  | "signalToNoise"
  | "pitchMedianHz"
  | "pitchRangeHz"
  | "pitchRangeSemitones"
  | "pitchVariationSemitones"
  | "fillerWordCount"
  | "breathCount"
  | "clippingRatio";

export type Metrics = Record<MetricName, MetricValue>;

/** A pointer from a finding back to the measurement it rests on. */
export type Evidence = {
  kind: "segment" | "pause" | "metric";
  /** "seg-3", "pause-2", or a metric's name such as "paceVariation". */
  id: string;
  label: string;
  /** Where to listen. Null for a metric, which belongs to the whole recording. */
  startSeconds: number | null;
  endSeconds: number | null;
};

/** One fact about the delivery, written by the backend's code from the measurements. */
export type Finding = {
  id: string;
  kind: string;
  level: "low" | "moderate" | "high" | null;
  role: "issue" | "strength" | "context";
  statement: string;
  evidence: Evidence[];
};

export type Correction = {
  findingId: string;
  title: string;
  why: string;
  drill: string;
  /** The phrase to practise on. */
  practise: Evidence | null;
};

export type Strength = { findingId: string; note: string };

export type CoachingSource = "ai" | "rules" | "none";

export type Coaching = {
  /** "ai": worded by the local language model. "rules": by fixed templates. "none": too little to coach on. */
  source: CoachingSource;
  model: string | null;
  /** Why the language model was not used, or what was removed from its answer. */
  notice: { code: string; message: string } | null;
  summary: { label: string; text: string }[];
  findings: Finding[];
  corrections: Correction[];
  working: Strength[];
  nextTake: string[];
  caveats: string[];
  settings: Record<string, number>;
  generatedAt: string;
  modelSeconds: number | null;
};

export type AnalysisResult = {
  schemaVersion: 1;
  analysisId: string;
  jobId: string;
  createdAt: string;
  role: Role;
  /** The name given to a reference. Null for a take. */
  title: string | null;
  revision: number;
  audioRetained: boolean;
  profile: Profile;
  language: LanguageInfo;
  durationSeconds: number;
  transcript: string | null;
  segments: SpeechSegment[];
  pauses: PauseEvent[];
  words: WordTiming[];
  metrics: Metrics;
  energyTimeline: EnergyTimeline;
  emphasisCandidates: EmphasisCandidate[];
  hesitations: Hesitation[];
  settings: Record<string, number>;
  pipeline: {
    speechModel: string | null;
    voiceActivityDetector: string;
    pitchTracker: string;
  };
  warnings: AnalysisWarning[];
  /** Null for results stored before coaching existed, or when the coaching step broke. */
  coaching: Coaching | null;
};

/** One row of the history list. Carries only the headline metrics. */
export type AnalysisSummary = {
  analysisId: string;
  jobId: string;
  createdAt: string;
  role: Role;
  title: string | null;
  profile: Profile;
  language: string;
  durationSeconds: number;
  revision: number;
  audioRetained: boolean;
  originalFilename: string | null;
  metrics: Partial<Record<MetricName, MetricValue>>;
  warningCodes: string[];
};

export type AnalysisList = { items: AnalysisSummary[]; total: number };

export type JobError = { code: string; message: string; retryable: boolean };

export type JobStatus = {
  jobId: string;
  kind: JobKind;
  /** Whether the recording being analysed is a take or a reference. */
  role: Role;
  status: JobStatusName;
  stage: JobStage | null;
  cancelRequested: boolean;
  error: JobError | null;
  analysisId: string | null;
  canRetry: boolean;
  canCancel: boolean;
  queuePosition: number | null;
  workerAlive: boolean;
  attempt: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
};

export type FocusMetric = { metric: MetricName; label: string; looksFor: string };

export type DeliveryProfile = {
  id: Profile;
  name: string;
  summary: string;
  targets: string[];
  focus: FocusMetric[];
  notMeasured: string[];
};

export type LanguageOption = { id: LanguageHint; label: string; note: string | null };

export type UploadLimits = {
  maxUploadBytes: number;
  maxAudioSeconds: number;
  acceptedExtensions: string[];
};

export type AnalysisOptions = {
  profiles: DeliveryProfile[];
  profileNote: string;
  languages: LanguageOption[];
  limits: UploadLimits;
};

export type Health = {
  status: "ok" | "degraded";
  database: "ok" | "error";
  worker: "running" | "not_running";
  speechModel: "ready" | "missing" | "unknown";
  /** Whether the local language model could write coaching, as the worker last saw it. */
  coach: CoachStatus;
  coachModel: string | null;
};

export type CoachStatus =
  | "ready"
  | "not_running"
  | "model_missing"
  | "not_local"
  | "off"
  | "unknown";

// --- Waveform ----------------------------------------------------------------------------

/**
 * The outline of a recording's sound wave, for drawing only. Each point covers
 * `secondsPerPoint` of audio and holds its lowest and highest sample, where 1.0 is the
 * loudest a recording can be. Nothing is measured from this.
 */
export type Waveform = {
  durationSeconds: number;
  secondsPerPoint: number;
  minimum: number[];
  maximum: number[];
};

// --- Comparison with a reference recording -----------------------------------------------

/** A stretch of one recording to listen to. */
export type PlayRange = { startSeconds: number; endSeconds: number };

export type AlignmentStatus = "matched" | "partial" | "unmatched" | "no_words";

export type ComparedMetric = {
  metric: string;
  label: string;
  unit: string;
  digits: number;
  take: number | null;
  reference: number | null;
  /** Take minus reference. Null if either is missing. */
  difference: number | null;
  estimated: boolean;
  note: string | null;
};

export type PauseSide = {
  pauseId: string;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
};

export type ComparedPause = {
  /**
   * "both": each recording pauses here. "reference_only" / "take_only": only one does.
   * "unplaced": the reference pauses, but the spot could not be found in the take.
   */
  status: "both" | "reference_only" | "take_only" | "unplaced";
  /** The words just before the pause. */
  afterWords: string;
  reference: PauseSide | null;
  take: PauseSide | null;
  differenceSeconds: number | null;
  referencePlay: PlayRange | null;
  takePlay: PlayRange | null;
};

export type ComparedPhrase = {
  referenceSegmentId: string;
  text: string;
  coverage: number;
  comparable: boolean;
  referenceWpm: number | null;
  takeWpm: number | null;
  differenceWpm: number | null;
  /** 0.25 means the take is 25% faster than the reference here. */
  differenceRatio: number | null;
  referencePlay: PlayRange;
  takePlay: PlayRange | null;
};

export type Difference = {
  kind: string;
  statement: string;
  referencePlay: PlayRange | null;
  takePlay: PlayRange | null;
};

/** A take set against a reference recording, worked out by the backend from both results. */
export type Comparison = {
  takeId: string;
  referenceId: string;
  referenceTitle: string | null;
  alignment: {
    status: AlignmentStatus;
    matchedWords: number;
    referenceWords: number;
    takeWords: number;
    coverage: number;
    note: string;
  };
  metrics: ComparedMetric[];
  pauses: ComparedPause[];
  phrases: ComparedPhrase[];
  differences: Difference[];
  caveats: string[];
  settings: Record<string, number>;
};
