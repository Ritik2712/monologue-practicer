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
JobStage = Literal["preparing_audio", "detecting_speech", "transcribing", "measuring_audio"]
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


class AnalysisResult(AnalysisBody):
    schema_version: Literal[1] = ANALYSIS_SCHEMA_VERSION
    analysis_id: str
    job_id: str
    created_at: datetime
    # 1 for the original analysis. Re-analysing later adds a new revision, never overwrites.
    revision: int
    audio_retained: bool


class AnalysisSummary(ApiModel):
    """One row of the history list: enough to recognise an attempt and compare two of them."""

    analysis_id: str
    job_id: str
    created_at: datetime
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
    status: JobStatusName
    # What the worker is doing right now. Only set while the job is running.
    stage: JobStage | None
    # True from the moment cancellation is requested until the worker has actually stopped.
    cancel_requested: bool
    error: JobError | None
    # Set once the job has succeeded: fetch the result from /api/analyses/{analysisId}.
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
