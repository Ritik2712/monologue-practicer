"""Speaking-rate and pause numbers. Pure arithmetic on segments and pauses.

Several "words per minute" figures are produced, and they must never be confused.

For one segment:

- delivery pace  = its words / its whole length, the short pauses inside it included.
                   How fast the line went by. The figure to practise against.
- speaking speed = its words / the time spent speaking in it, those pauses left out.
                   How fast the words themselves were said.

For the recording:

- delivery pace     = all words / the length of all segments   (pauses inside segments
                      included; the longer pauses between segments are not)
- speech-active WPM = all words / total speaking time          (every pause excluded)
- whole-clip WPM    = all words / full clip length             (everything included)

"Speaking time" is the length of the stretches. Gaps shorter than the minimum pause sit
inside a stretch and count as speaking; detected pauses and the silence before and after
the speech do not.

A segment with no pause inside it has one pace: the two figures are the same number.
"""

import statistics
from dataclasses import dataclass
from typing import Literal

from app.pipeline.segmentation import Pause, Segment, count_words
from app.pipeline.settings import AnalysisSettings

Quality = Literal["measured", "estimated", "unavailable"]


@dataclass(frozen=True)
class Metric:
    value: float | None
    unit: str
    quality: Quality
    note: str | None = None


def unavailable(unit: str, note: str) -> Metric:
    return Metric(None, unit, "unavailable", note)


def words_per_minute(word_count: int, seconds: float) -> float | None:
    """None rather than a division by zero when there is no speaking time."""
    if seconds <= 0:
        return None
    return word_count / (seconds / 60)


def mean_confidence(segment: Segment) -> float | None:
    values = [word.probability for word in segment.words if word.probability is not None]
    return sum(values) / len(values) if values else None


@dataclass(frozen=True)
class SegmentPace:
    word_count: int
    # Delivery pace: over the segment's whole length, its pauses included. This is the
    # figure that is compared with the speaker's typical pace.
    wpm: float | None
    # Speaking speed: over the time spent speaking only.
    speaking_wpm: float | None
    confidence: float | None
    quality: Quality
    # False when the number should not be relied on; `flags` says why.
    reliable: bool
    flags: tuple[str, ...]


def segment_pace(
    segment: Segment, settings: AnalysisSettings, *, has_transcript: bool
) -> SegmentPace:
    if not has_transcript:
        return SegmentPace(0, None, None, None, "unavailable", False, ("no_transcript",))

    word_count = count_words(segment.words)
    confidence = mean_confidence(segment)
    wpm = words_per_minute(word_count, segment.span_seconds)
    speaking_wpm = words_per_minute(word_count, segment.speaking_seconds)
    if word_count == 0 or wpm is None or speaking_wpm is None:
        return SegmentPace(word_count, None, None, confidence, "unavailable", False, ("no_words",))

    flags: list[str] = []
    if round(segment.speaking_seconds * 1000) < settings.min_segment_ms:
        flags.append("short_segment")
    if word_count < settings.min_segment_words:
        flags.append("few_words")
    if confidence is not None and confidence < settings.low_confidence:
        flags.append("low_confidence")
    reliable = not flags
    # An outlier is a prompt to double-check, not proof of a mistake, so it is flagged
    # separately and the measured value is left exactly as it is. It is judged on the
    # speaking speed: too many words for the time spent speaking is what a misheard
    # transcript looks like, whatever pauses the line had.
    if speaking_wpm > settings.wpm_outlier:
        flags.append("wpm_outlier")
    return SegmentPace(
        word_count,
        wpm,
        speaking_wpm,
        confidence,
        "measured" if reliable else "estimated",
        reliable,
        tuple(flags),
    )


PaceVsTypical = Literal["typical", "faster", "slower"]


def typical_wpm(paces: list[SegmentPace], settings: AnalysisSettings) -> float | None:
    """The speaker's own usual pace in this recording: the median of the reliable segments.

    A median, so one rushed or one drawn-out phrase does not move it. None when there are
    too few reliable segments to call anything "typical".
    """
    reliable = [pace.wpm for pace in paces if pace.reliable and pace.wpm is not None]
    if len(reliable) < settings.min_segments_for_typical_pace:
        return None
    return statistics.median(reliable)


def pace_vs_typical(
    pace: SegmentPace, typical: float | None, settings: AnalysisSettings
) -> PaceVsTypical | None:
    """Whether a segment is notably faster or slower than the speaker's typical pace.

    Only reliable segments are judged: a short phrase's WPM swings too widely to compare.
    """
    if typical is None or typical <= 0 or not pace.reliable or pace.wpm is None:
        return None
    ratio = pace.wpm / typical
    if ratio >= 1 + settings.pace_deviation_ratio:
        return "faster"
    if ratio <= 1 - settings.pace_deviation_ratio:
        return "slower"
    return "typical"


@dataclass(frozen=True)
class PaceSummary:
    total_words: int
    speech_active_seconds: float
    delivery_wpm: Metric
    speech_active_wpm: Metric
    whole_clip_wpm: Metric
    pace_variation: Metric
    pace_min_wpm: Metric
    pace_max_wpm: Metric


def summarize_pace(
    segments: list[Segment],
    paces: list[SegmentPace],
    duration_seconds: float,
    *,
    has_transcript: bool,
    word_quality: Quality,
) -> PaceSummary:
    speech_seconds = sum(segment.speaking_seconds for segment in segments)
    delivery_seconds = sum(segment.span_seconds for segment in segments)
    total_words = sum(pace.word_count for pace in paces)

    if not segments:
        reason = "No speech was detected."
    elif not has_transcript:
        reason = "No transcript is available, so words could not be counted."
    elif total_words == 0:
        reason = "No words were recognised."
    else:
        reason = None

    if reason:
        missing = unavailable("words/minute", reason)
        return PaceSummary(
            total_words, speech_seconds, missing, missing, missing, missing, missing, missing
        )

    delivery_wpm = Metric(
        words_per_minute(total_words, delivery_seconds),
        "words/minute",
        word_quality,
        "Total words / the length of all segments. The short pauses inside a segment are "
        "counted; the longer pauses between segments are not.",
    )
    active = words_per_minute(total_words, speech_seconds)
    whole = words_per_minute(total_words, duration_seconds)
    speech_active_wpm = Metric(
        active,
        "words/minute",
        word_quality,
        "Total words / speaking time. Every pause is excluded.",
    )
    whole_clip_wpm = Metric(
        whole,
        "words/minute",
        word_quality,
        "Total words / full clip length, including pauses. Not a measure of speaking speed.",
    )

    reliable_wpms = [pace.wpm for pace in paces if pace.reliable and pace.wpm is not None]
    if len(reliable_wpms) < 2:
        too_few = unavailable(
            "words/minute", "Needs at least two segments long enough to measure reliably."
        )
        return PaceSummary(
            total_words,
            speech_seconds,
            delivery_wpm,
            speech_active_wpm,
            whole_clip_wpm,
            too_few,
            too_few,
            too_few,
        )

    note = f"Across the {len(reliable_wpms)} segments long enough to measure reliably."
    return PaceSummary(
        total_words,
        speech_seconds,
        delivery_wpm,
        speech_active_wpm,
        whole_clip_wpm,
        Metric(
            statistics.pstdev(reliable_wpms),
            "words/minute",
            word_quality,
            f"Standard deviation of the segments' delivery pace. {note}",
        ),
        Metric(min(reliable_wpms), "words/minute", word_quality, f"Slowest segment. {note}"),
        Metric(max(reliable_wpms), "words/minute", word_quality, f"Fastest segment. {note}"),
    )


@dataclass(frozen=True)
class PauseSummary:
    count: Metric
    total_seconds: Metric
    average_seconds: Metric
    median_seconds: Metric
    longest_seconds: Metric
    ratio: Metric


def summarize_pauses(
    pauses: list[Pause], duration_seconds: float, *, speech_detected: bool
) -> PauseSummary:
    if not speech_detected:
        none = unavailable("seconds", "No speech was detected, so there are no pauses to measure.")
        count = unavailable("count", none.note or "")
        ratio = unavailable("ratio", none.note or "")
        return PauseSummary(count, none, none, none, none, ratio)

    durations = [pause.duration for pause in pauses]
    total = sum(durations)
    count = Metric(float(len(durations)), "count", "measured")
    total_seconds = Metric(total, "seconds", "measured")
    ratio = (
        Metric(total / duration_seconds, "ratio", "measured", "Total pause time / clip length.")
        if duration_seconds > 0
        else unavailable("ratio", "The clip has no length.")
    )
    if not durations:
        none = unavailable("seconds", "No pauses were detected.")
        return PauseSummary(count, total_seconds, none, none, none, ratio)

    return PauseSummary(
        count,
        total_seconds,
        Metric(total / len(durations), "seconds", "measured"),
        Metric(statistics.median(durations), "seconds", "measured"),
        Metric(max(durations), "seconds", "measured"),
        ratio,
    )
