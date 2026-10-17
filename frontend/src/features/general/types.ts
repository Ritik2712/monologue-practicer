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
  | "generating_feedback"
  | "summarising_feedback";
/**
 * "analysis" measures a recording. "coaching" only rewrites the coaching of a stored one.
 * "summary" asks the AI model to pick out the most telling of your notes.
 */
export type JobKind = "analysis" | "coaching" | "summary";
/**
 * What a recording is for. A "take" is your own attempt. A "reference" is a recording you
 * supply to compare takes against, such as the original performance.
 */
export type Role = "take" | "reference";
export type PauseSignificance = "short" | "medium" | "long";
/**
 * Where a voice sits. "lower" is typically heard as a masculine voice and "higher" as a
 * feminine one; "neutral" could be heard either way. A description of sound, not of a person.
 */
export type VoiceBand = "lower" | "neutral" | "higher";
/** Pitch and resonance together. "mixed": one is in the lower range and the other in the higher. */
export type VoiceMarker = VoiceBand | "mixed";
/** What the speaker asked to work towards, if anything. */
export type VoiceGoal = "none" | "lower" | "higher";
export type PaceVsTypical = "typical" | "faster" | "slower";

export type MetricValue = {
  /** Null whenever quality is "unavailable". A missing number is never shown as zero. */
  value: number | null;
  unit: string;
  quality: Quality;
  note: string | null;
};

/** One measured value of a voice, and the range it falls in. */
export type VoicePlacement = {
  valueHz: number;
  band: VoiceBand;
  /**
   * How far into its range the value lies, 0 to 100. A position, not a probability: in the
   * lower and higher ranges 0 is the edge of the neutral range and 100 the far end; in the
   * neutral range 100 is the middle.
   */
  percent: number;
  quality: Quality;
};

export type SegmentVoice = {
  pitch: VoicePlacement | null;
  resonance: VoicePlacement | null;
  marker: VoiceMarker | null;
};

/** Where the voice sat over the whole recording, and the ranges it was placed in. */
export type VoiceRange = {
  goal: VoiceGoal;
  pitch: VoicePlacement | null;
  resonance: VoicePlacement | null;
  marker: VoiceMarker | null;
  /** The typical first three formants, in Hz, behind the resonance figure. */
  formantsHz: number[] | null;
  phrases: { lower: number; neutral: number; higher: number; mixed: number; unmeasured: number };
  /** The ranges that were in force: `pitch_neutral_from_hz` and so on. */
  bands: Record<string, number>;
  /** Why the resonance is an estimate or is missing, when it is. */
  resonanceNote: string | null;
};

export type SpeechSegment = {
  id: string;
  index: number;
  sectionIndex: number;
  startSeconds: number;
  endSeconds: number;
  /** Time spent speaking: the segment's length without the pauses inside it. */
  speechActiveSeconds: number;
  /** The pauses inside the segment. Missing on results made before a segment could hold one. */
  pauseCount?: number;
  pauseSeconds?: number;
  transcript: string | null;
  wordCount: number | null;
  /** Speaking speed: words ÷ time spent speaking, the pauses inside left out. */
  segmentWpm: number | null;
  /**
   * Delivery pace: words ÷ the segment's whole length, the pauses inside counted. Missing
   * on results made before it existed, where it would equal `segmentWpm`.
   */
  deliveryWpm?: number | null;
  paceVsTypical: PaceVsTypical | null;
  quality: Quality;
  reliable: boolean;
  flags: string[];
  confidence: number | null;
  meanEnergyDb: number | null;
  energyDeltaDb: number | null;
  medianPitchHz: number | null;
  pitchDeltaSemitones: number | null;
  /** Where the voice sat in this phrase. Missing on results made before it was measured. */
  voice?: SegmentVoice | null;
};

export type PauseEvent = {
  id: string;
  index: number;
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  significance: PauseSignificance;
  /** The segments on either side. The same one twice for a pause inside a segment. */
  afterSegmentId: string;
  beforeSegmentId: string;
  insideSegment?: boolean;
  startsNewSection: boolean;
};

/** An unbroken run of speaking. Pause `n` lies between stretch `n` and stretch `n + 1`. */
export type SpeechStretch = {
  index: number;
  startSeconds: number;
  endSeconds: number;
  segmentId: string;
};

/** A silence too short to count as a pause. It stays inside a segment as speaking time. */
export type ShortSilence = {
  startSeconds: number;
  endSeconds: number;
  durationSeconds: number;
  segmentId: string | null;
};

export type WordTiming = {
  text: string;
  startSeconds: number;
  endSeconds: number;
  confidence: number | null;
  segmentId: string | null;
  /** The stretch the word was spoken in, which says which side of a pause it is on. */
  stretchIndex?: number | null;
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
  | "deliveryWpm"
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

/**
 * `deliveryWpm` is missing on results made before it existed. There it would equal
 * `speechActiveWpm`: no segment of such a result holds a pause.
 */
export type Metrics = Record<Exclude<MetricName, "deliveryWpm">, MetricValue> & {
  deliveryWpm?: MetricValue | null;
};

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
  /** Your own labels on pauses that this coaching took into account, by pause ID. */
  labelsUsed?: Record<string, PauseLabel>;
  generatedAt: string;
  modelSeconds: number | null;
};

export type PauseLabel = "intentional" | "accidental";

export type RevisionReason = "transcript_corrected" | "reanalysed";

/** One result in the family of results made from the same recording. */
export type RevisionInfo = {
  analysisId: string;
  revision: number;
  /** Null for the first analysis of the recording. */
  reason: RevisionReason | null;
  createdAt: string;
  calibrationVersion: number;
};

export type AnalysisResult = {
  schemaVersion: 1;
  analysisId: string;
  jobId: string;
  createdAt: string;
  role: Role;
  /** The name given to a reference. Null for a take. */
  title: string | null;
  /** 1 for the first analysis. A corrected transcript or a fresh analysis adds a revision. */
  revision: number;
  revisionReason?: RevisionReason | null;
  /** Every result made from this recording, oldest first. */
  revisions?: RevisionInfo[];
  /** The monologue this take was recorded for. Null for a reference and for a free take. */
  monologueId?: string | null;
  audioRetained: boolean;
  profile: Profile;
  language: LanguageInfo;
  durationSeconds: number;
  transcript: string | null;
  segments: SpeechSegment[];
  /**
   * Null or missing for results made before a segment could hold a pause. In those, every
   * pause ended a segment, so each segment is one stretch.
   */
  stretches?: SpeechStretch[] | null;
  pauses: PauseEvent[];
  /** Null or missing for results stored before these were recorded. */
  shortSilences?: ShortSilence[] | null;
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
  /** Where the voice sat. Null with no speech, and on results made before it was measured. */
  voiceRange?: VoiceRange | null;
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
  revisionReason?: RevisionReason | null;
  /** The monologue a take was recorded for, if any. */
  monologueId?: string | null;
  audioRetained: boolean;
  originalFilename: string | null;
  metrics: Partial<Record<MetricName, MetricValue>>;
  warningCodes: string[];
  /** The thresholds that produced the numbers. */
  settings?: Record<string, number>;
};

export type AnalysisList = { items: AnalysisSummary[]; total: number };

/**
 * One monologue being practised: a reference recording, in its newest revision, and a count
 * of the takes recorded for it. `monologueId` stays the same when the reference is corrected
 * or measured again; `referenceId` then points at the new revision.
 */
export type Monologue = {
  monologueId: string;
  /** The reference recording that takes are compared with. */
  referenceId: string;
  title: string;
  /** When the reference was first added. */
  createdAt: string;
  language: string;
  durationSeconds: number;
  audioRetained: boolean;
  revision: number;
  revisionCount: number;
  takeCount: number;
  lastTakeAt: string | null;
  /** The thresholds the reference was measured with. */
  settings?: Record<string, number>;
};

export type MonologueList = { items: Monologue[] };

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
  /** Set when this job analyses the kept recording of an earlier analysis again. */
  sourceAnalysisId?: string | null;
  /** The monologue the take being analysed was recorded for, if any. */
  monologueId?: string | null;
  voiceGoal?: VoiceGoal;
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

export type VoiceGoalOption = { id: VoiceGoal; label: string; note: string | null };

export type AnalysisOptions = {
  profiles: DeliveryProfile[];
  profileNote: string;
  languages: LanguageOption[];
  limits: UploadLimits;
  /** What the speaker can ask to work towards with their voice. */
  voiceGoals?: VoiceGoalOption[];
  voiceGoalNote?: string;
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
  /** Set when the two were analysed with different settings. */
  settingsNote?: string | null;
  caveats: string[];
  settings: Record<string, number>;
};

// --- Feedback and calibration ------------------------------------------------------------

export type FeedbackCategory =
  | "pause_intentional"
  | "pause_accidental"
  | "pause_false"
  | "split_wrong"
  | "pause_missed"
  | "wpm_too_high"
  | "wpm_too_low"
  | "transcript_wrong"
  | "coaching_useful"
  | "coaching_not_useful";

export type FeedbackRequest = {
  category: FeedbackCategory;
  /** "pause-2", "seg-3", a finding such as "f4", or nothing for the whole recording. */
  targetId?: string | null;
  /** Where in the recording, for a missed pause. */
  atSeconds?: number | null;
  /** Leaving this out keeps the note that is there; an empty string clears it. */
  note?: string | null;
};

export type WpmCheck = {
  label: string;
  text: string;
  action: "correct_transcript" | "report_missed_pause" | "report_false_pause" | null;
};

/** How a WPM figure was arrived at, shown when you say it looks wrong. */
export type WpmReview = {
  target: string;
  words: number | null;
  speakingSeconds: number | null;
  wpm: number | null;
  formula: string;
  checks: WpmCheck[];
};

export type FeedbackItem = {
  id: string;
  analysisId: string;
  category: FeedbackCategory;
  targetKind: "pause" | "segment" | "correction" | "recording";
  targetId: string | null;
  atSeconds: number | null;
  note: string | null;
  createdAt: string;
  calibrationVersion: number;
  /** What was measured at the spot the feedback is about. */
  features: Record<string, number | string | boolean | null>;
  /**
   * "label": changes how the coaching reads a pause. "report": counts towards adjusting a
   * setting. "used": already counted. "recorded": saved, and changes nothing by itself.
   */
  effect: "label" | "report" | "used" | "recorded";
  setting: string | null;
  direction: number;
  /** One sentence saying what this feedback does. */
  message: string;
  review: WpmReview | null;
};

export type Confidence = "low" | "medium" | "high";

export type CalibrationChange = {
  version: number;
  createdAt: string;
  cause: "defaults" | "auto" | "undo" | "reset";
  setting: string | null;
  label: string | null;
  unit: string | null;
  oldValue: number | null;
  newValue: number | null;
  reason: string;
  reportCount: number;
  agreeingCount: number;
  recordingCount: number;
  confidence: Confidence | null;
  /** True once this adjustment has been undone or reset away. */
  undone: boolean;
};

export type CalibratedSetting = {
  name: string;
  group: "analysis" | "coaching";
  label: string;
  description: string;
  unit: string;
  digits: number;
  value: number;
  default: number;
  minimum: number;
  maximum: number;
  step: number;
  changed: boolean;
  pending: {
    raiseCount: number;
    lowerCount: number;
    recordings: number;
    needed: number;
    /** How many reports on the larger side are about your own takes, not a reference. */
    takeReports: number;
  };
  supportingReports: number;
  confidence: Confidence | "none";
  status: string;
};

export type Calibration = {
  /** The version new analyses are made with. */
  version: number;
  /** False when automatic adjustment is switched off. */
  adaptive: boolean;
  /** "calibrating" while every setting is still at its default. */
  state: "calibrating" | "adjusted";
  summary: string;
  feedbackCount: number;
  pendingReportCount: number;
  settings: CalibratedSetting[];
  fixed: { name: string; label: string; value: number; unit: string }[];
  /** Newest first. */
  changes: CalibrationChange[];
  canUndo: boolean;
  rules: {
    minReports: number;
    minRecordings: number;
    /** Reports about your own takes that an adjustment needs among those that agree. */
    minTakeReports: number;
    minAgreement: number;
    window: number;
    reversalReports: number;
  };
};

/** What the screen needs after any change to feedback or calibration. */
export type FeedbackUpdate = {
  items: FeedbackItem[];
  /** Settings that changed because of this request. Usually empty. */
  adjustments: CalibrationChange[];
  calibration: Calibration;
};

export type SegmentCorrection = { segmentId: string; text: string };

// --- What the feedback adds up to ---------------------------------------------------------

/** One thing your stored feedback adds up to, counted and written by the app's own code. */
export type SummaryFact = { id: string; text: string };

/** A note you wrote with a piece of feedback, and what that feedback was about. */
export type SummaryNote = { about: string; text: string };

/** The notes the AI model picked out as the most telling, shown word for word. */
export type NotePick = {
  /** As they read when they were picked, the most telling first. */
  notes: SummaryNote[];
  model: string;
  modelSeconds: number | null;
  generatedAt: string;
  /** How many notes it picked from. */
  noteCount: number;
  /** True when your notes have changed since. */
  stale: boolean;
};

export type FeedbackSummary = {
  feedbackCount: number;
  /** Counted by the app each time this is asked for, so always current. */
  facts: SummaryFact[];
  /** Your most recent notes, newest last: what the AI model is given, and nothing else. */
  notes: SummaryNote[];
  /** Every note there is, including any too old to be listed. */
  noteCount: number;
  /** The listed notes long enough to say something: the ones the AI model is offered. */
  pickableNotes: number;
  /** The AI model is only asked once it can be offered at least this many. */
  minNotes: number;
  picked: NotePick | null;
  /** The request to the AI model: while it waits or runs, or after it failed. */
  job: JobStatus | null;
};
