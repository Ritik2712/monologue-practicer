/**
 * The shapes of the JSON the backend sends. They mirror `backend/app/schemas.py`; when a
 * field changes there, it changes here.
 */

export type Quality = "measured" | "estimated" | "unavailable";
export type Profile = "walter_white" | "joker" | "thomas_shelby" | "custom";
export type LanguageHint = "auto" | "en" | "hi" | "hinglish";
export type JobStatusName = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type JobStage = "preparing_audio" | "detecting_speech" | "transcribing" | "measuring_audio";
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

export type AnalysisResult = {
  schemaVersion: 1;
  analysisId: string;
  jobId: string;
  createdAt: string;
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
};

/** One row of the history list. Carries only the headline metrics. */
export type AnalysisSummary = {
  analysisId: string;
  jobId: string;
  createdAt: string;
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
};
