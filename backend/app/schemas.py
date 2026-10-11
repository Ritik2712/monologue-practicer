"""The shapes of everything the API sends and receives.

Field names are snake_case in Python and camelCase in JSON (`start_seconds` is sent as
`startSeconds`), which is what the TypeScript frontend expects.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

Quality = Literal["measured", "estimated", "unavailable"]
Profile = Literal["walter_white", "joker", "thomas_shelby", "custom"]
LanguageHint = Literal["auto", "en", "hi", "hinglish"]
JobStatusName = Literal["queued", "running", "succeeded", "failed", "cancelled"]
JobStage = Literal[
    "preparing_audio",
    "detecting_speech",
    "transcribing",
    "measuring_audio",
    "generating_feedback",
]
# "analysis" measures a recording. "coaching" only rewrites the coaching of a stored analysis.
JobKind = Literal["analysis", "coaching"]
# What a recording is for. A "take" is the user's own attempt. A "reference" is a recording
# they supply to compare their takes against, such as the original performance.
Role = Literal["take", "reference"]
PauseSignificance = Literal["short", "medium", "long"]

# Bumped when the shape of AnalysisResult changes in a way older readers cannot handle.
ANALYSIS_SCHEMA_VERSION = 1


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# --- Analysis result ---------------------------------------------------------------------


class MetricValue(ApiModel):
    # None whenever quality is "unavailable": a missing number is never shown as zero.
    value: float | None
    unit: str
    quality: Quality
    note: str | None = None


class SpeechSegment(ApiModel):
    id: str
    index: int
    # Segments in the same section are separated only by ordinary pauses, not long silences.
    section_index: int
    start_seconds: float
    end_seconds: float
    speech_active_seconds: float
    transcript: str | None
    word_count: int | None
    segment_wpm: float | None
    # Against the speaker's own typical pace in this recording, not against any target.
    # None when the segment is too short to judge or there is no typical pace to compare with.
    pace_vs_typical: Literal["typical", "faster", "slower"] | None = None
    quality: Quality
    reliable: bool
    flags: list[str]
    confidence: float | None
    mean_energy_db: float | None
    # Compared with this recording's typical segment. Positive means louder / higher.
    energy_delta_db: float | None
    median_pitch_hz: float | None
    pitch_delta_semitones: float | None


class PauseEvent(ApiModel):
    id: str
    index: int
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    significance: PauseSignificance
    after_segment_id: str
    before_segment_id: str
    starts_new_section: bool


class WordTiming(ApiModel):
    text: str
    start_seconds: float
    end_seconds: float
    confidence: float | None
    segment_id: str | None


class EmphasisCandidate(ApiModel):
    text: str
    start_seconds: float
    end_seconds: float
    segment_id: str | None
    reasons: list[Literal["louder", "higher_pitch"]]
    energy_delta_db: float | None
    pitch_delta_semitones: float | None


class Hesitation(ApiModel):
    text: str
    start_seconds: float


class EnergyTimeline(ApiModel):
    seconds_per_point: float
    unit: str
    values: list[float]


class AnalysisWarning(ApiModel):
    code: str
    message: str


class LanguageInfo(ApiModel):
    # "en", "hi", "hinglish", another ISO code the recogniser detected, or "unknown".
    code: str
    source: Literal["declared", "detected", "none"]
    confidence: float | None


class PipelineInfo(ApiModel):
    speech_model: str | None
    voice_activity_detector: str
    pitch_tracker: str


class Metrics(ApiModel):
    total_word_count: MetricValue
    speech_active_seconds: MetricValue
    speech_active_wpm: MetricValue
    whole_clip_wpm: MetricValue
    pace_variation: MetricValue
    pace_min_wpm: MetricValue
    pace_max_wpm: MetricValue
    typical_segment_wpm: MetricValue
    pause_count: MetricValue
    total_pause_seconds: MetricValue
    average_pause_seconds: MetricValue
    median_pause_seconds: MetricValue
    longest_pause_seconds: MetricValue
    pause_ratio: MetricValue
    leading_silence_seconds: MetricValue
    trailing_silence_seconds: MetricValue
    energy_variation: MetricValue
    signal_to_noise: MetricValue
    pitch_median_hz: MetricValue
    pitch_range_hz: MetricValue
    pitch_range_semitones: MetricValue
    pitch_variation_semitones: MetricValue
    filler_word_count: MetricValue
    breath_count: MetricValue
    clipping_ratio: MetricValue


class AnalysisBody(ApiModel):
    """Everything the audio pipeline measures. The worker adds the identity fields below."""

    profile: Profile
    language: LanguageInfo
    duration_seconds: float
    transcript: str | None
    segments: list[SpeechSegment]
    pauses: list[PauseEvent]
    words: list[WordTiming]
    metrics: Metrics
    energy_timeline: EnergyTimeline
    emphasis_candidates: list[EmphasisCandidate]
    hesitations: list[Hesitation]
    # The thresholds that produced this result, including their version number.
    settings: dict[str, float | int]
    pipeline: PipelineInfo
    warnings: list[AnalysisWarning]


# --- Coaching ----------------------------------------------------------------------------


class Evidence(ApiModel):
    """A pointer from a finding back to the measurement it rests on."""

    kind: Literal["segment", "pause", "metric"]
    # "seg-3", "pause-2", or the JSON name of a metric such as "paceVariation".
    id: str
    label: str
    # Where to listen. None for a metric, which belongs to the whole recording.
    start_seconds: float | None = None
    end_seconds: float | None = None


class Finding(ApiModel):
    """One fact about the delivery, written by code from the measurements."""

    id: str
    # What was looked at, e.g. "pace", "pause_length", "fast_segment".
    kind: str
    # Where the value falls in this app's rough bands. None for findings without a band.
    level: Literal["low", "moderate", "high"] | None = None
    # Against the chosen profile: something to work on, something to keep, or neither.
    role: Literal["issue", "strength", "context"]
    statement: str
    evidence: list[Evidence]


class Correction(ApiModel):
    # The finding this correction is about. Its statement holds the measured figures.
    finding_id: str
    title: str
    why: str
    drill: str
    # The phrase to practise on.
    practise: Evidence | None = None


class Strength(ApiModel):
    finding_id: str
    note: str


class SummaryLine(ApiModel):
    label: str
    text: str


class CoachingNotice(ApiModel):
    code: str
    message: str


class Coaching(ApiModel):
    # "ai": worded by the local language model. "rules": worded by fixed templates.
    # "none": there was too little to coach on.
    source: Literal["ai", "rules", "none"]
    # The language model's name when source is "ai".
    model: str | None = None
    # Why the language model was not used, or what was removed from its answer.
    notice: CoachingNotice | None = None
    summary: list[SummaryLine]
    findings: list[Finding]
    # Most important first. At most three.
    corrections: list[Correction]
    working: list[Strength]
    next_take: list[str]
    # What is uncertain or was not measured at all.
    caveats: list[str]
    # The bands that produced the wording, including their version number.
    settings: dict[str, float | int]
    generated_at: datetime
    # How long the language model took, when it was used.
    model_seconds: float | None = None


class AnalysisResult(AnalysisBody):
    schema_version: Literal[1] = ANALYSIS_SCHEMA_VERSION
    analysis_id: str
    job_id: str
    created_at: datetime
    role: Role = "take"
    # The name the user gave a reference. None for a take.
    title: str | None = None
    # 1 for the original analysis. Re-analysing later adds a new revision, never overwrites.
    revision: int
    audio_retained: bool
    # Kept apart from the measurements: it can be written again without touching them.
    # None for results stored before coaching existed.
    coaching: Coaching | None = None


class AnalysisSummary(ApiModel):
    """One row of the history list: enough to recognise an attempt and compare two of them."""

    analysis_id: str
    job_id: str
    created_at: datetime
    role: Role = "take"
    title: str | None = None
    profile: Profile
    language: str
    duration_seconds: float
    revision: int
    audio_retained: bool
    original_filename: str | None
    # Keyed by the metric's JSON name, e.g. "speechActiveWpm".
    metrics: dict[str, MetricValue]
    warning_codes: list[str]


class AnalysisList(ApiModel):
    items: list[AnalysisSummary]
    # How many analyses exist in total, which can be more than this page holds.
    total: int


class HistoryCleared(ApiModel):
    deleted_analyses: int
    deleted_jobs: int


# --- Waveform ----------------------------------------------------------------------------


class Waveform(ApiModel):
    """The outline of a recording's sound wave, for drawing only.

    Each point covers `seconds_per_point` of audio and holds the lowest and highest sample
    in it, on a scale where 1.0 is the loudest a recording can be. Nothing is measured
    from this, and it says nothing about real-world loudness.
    """

    duration_seconds: float
    seconds_per_point: float
    minimum: list[float]
    maximum: list[float]


# --- Comparison with a reference recording -----------------------------------------------


class PlayRange(ApiModel):
    """A stretch of one recording to listen to."""

    start_seconds: float
    end_seconds: float


class AlignmentSummary(ApiModel):
    # "matched": the same passage. "partial": partly. "unmatched": different words.
    # "no_words": one of the two has no recognised words to line up.
    status: Literal["matched", "partial", "unmatched", "no_words"]
    matched_words: int
    reference_words: int
    take_words: int
    # Share of the reference's words found in the take, in the same order. 0 to 1.
    coverage: float
    note: str


class ComparedMetric(ApiModel):
    # The JSON name of the measurement, e.g. "speechActiveWpm".
    metric: str
    label: str
    unit: str
    # How many decimal places the values are rounded to.
    digits: int
    take: float | None
    reference: float | None
    # Take minus reference, from the rounded values. None if either is missing.
    difference: float | None
    # True when either value is an estimate, so the difference is one too.
    estimated: bool
    note: str | None = None


class PauseSide(ApiModel):
    pause_id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float


class ComparedPause(ApiModel):
    # "both": each recording pauses here. "reference_only": the reference pauses and the
    # take does not. "take_only": the other way round. "unplaced": the reference pauses,
    # but the spot could not be found in the take.
    status: Literal["both", "reference_only", "take_only", "unplaced"]
    # The words just before the pause, from the recording that has it.
    after_words: str
    reference: PauseSide | None
    take: PauseSide | None
    # Take minus reference, when both pause here.
    difference_seconds: float | None
    # What to play to hear this spot in each recording. None where it could not be found.
    reference_play: PlayRange | None
    take_play: PlayRange | None


class ComparedPhrase(ApiModel):
    reference_segment_id: str
    # The phrase as the reference says it.
    text: str
    # Share of the phrase's words that were matched in the take. 0 to 1.
    coverage: float
    # False when too little of the phrase was matched, or it is too short, to compare pace.
    comparable: bool
    reference_wpm: float | None
    take_wpm: float | None
    # Take minus reference.
    difference_wpm: float | None
    # The same as a share of the reference's pace: 0.25 means the take is 25% faster.
    difference_ratio: float | None
    reference_play: PlayRange
    take_play: PlayRange | None


class Difference(ApiModel):
    """One of the biggest differences between the take and the reference, in words."""

    kind: Literal[
        "pause_missing",
        "pause_extra",
        "pause_shorter",
        "pause_longer",
        "phrase_faster",
        "phrase_slower",
        "overall_faster",
        "overall_slower",
    ]
    statement: str
    reference_play: PlayRange | None
    take_play: PlayRange | None


class Comparison(ApiModel):
    """A take set against a reference recording. Computed from the two stored results."""

    take_id: str
    reference_id: str
    reference_title: str | None
    alignment: AlignmentSummary
    # The recordings as wholes.
    metrics: list[ComparedMetric]
    # Pause by pause and phrase by phrase. Empty when the words could not be lined up.
    pauses: list[ComparedPause]
    phrases: list[ComparedPhrase]
    # The biggest differences, largest first.
    differences: list[Difference]
    caveats: list[str]
    # The thresholds that produced this comparison, including their version number.
    settings: dict[str, float | int]


# --- What the submission form offers -----------------------------------------------------


class FocusMetric(ApiModel):
    # The key of a metric in AnalysisResult.metrics, e.g. "paceVariation".
    metric: str
    label: str
    looks_for: str


class DeliveryProfile(ApiModel):
    id: Profile
    name: str
    summary: str
    targets: list[str]
    focus: list[FocusMetric]
    # Parts of the style the app cannot measure, so the screen can be upfront about it.
    not_measured: list[str]


class LanguageOption(ApiModel):
    id: LanguageHint
    label: str
    note: str | None


class UploadLimits(ApiModel):
    max_upload_bytes: int
    max_audio_seconds: float
    accepted_extensions: list[str]


class AnalysisOptions(ApiModel):
    profiles: list[DeliveryProfile]
    profile_note: str
    languages: list[LanguageOption]
    limits: UploadLimits


# --- Jobs --------------------------------------------------------------------------------


class JobError(ApiModel):
    code: str
    message: str
    # True when the same job could succeed if tried again.
    retryable: bool


class JobStatus(ApiModel):
    job_id: str
    kind: JobKind
    # Whether the recording being analysed is a take or a reference.
    role: Role
    status: JobStatusName
    # What the worker is doing right now. Only set while the job is running.
    stage: JobStage | None
    # True from the moment cancellation is requested until the worker has actually stopped.
    cancel_requested: bool
    error: JobError | None
    # Fetch the result from /api/analyses/{analysisId}. An analysis job has it once it has
    # succeeded; a coaching job has it from the start.
    analysis_id: str | None
    can_retry: bool
    can_cancel: bool
    # Jobs ahead of this one in the queue. Only set while queued.
    queue_position: int | None
    # False when no worker process has reported in recently, so nothing will be processed.
    worker_alive: bool
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ErrorDetail(ApiModel):
    code: str
    message: str


class Health(ApiModel):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "error"]
    worker: Literal["running", "not_running"]
    # As last reported by the worker. "unknown" until a worker has started at least once.
    speech_model: Literal["ready", "missing", "unknown"]
    # Whether the local language model could write coaching right now, as last reported by
    # the worker. "off" when AI coaching is switched off in the settings.
    coach: Literal["ready", "not_running", "model_missing", "not_local", "off", "unknown"]
    coach_model: str | None = None
