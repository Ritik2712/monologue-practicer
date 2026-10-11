"""Turns detected speech into segments and pauses. Pure functions: no audio, no models.

Vocabulary used throughout the pipeline:

- speech region: one stretch the voice activity detector marked as speech.
- segment: speech regions joined across gaps that are too short to be a pause.
- pause: the silence between two segments. Always at least `min_pause_ms` long.
- short silence: a gap between speech regions that is shorter than that. It stays inside a
  segment and counts as speaking time, but it is kept on record.
- section: a group of segments. A new section starts after every "long" silence.

Silence before the first segment and after the last one is not a pause: nothing was
interrupted, the recording simply had not started or had already finished.
"""

from dataclasses import dataclass, field
from typing import Literal

from app.pipeline.settings import AnalysisSettings

PauseSignificance = Literal["short", "medium", "long"]


@dataclass(frozen=True)
class SpeechRegion:
    start: float
    end: float


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float
    probability: float | None = None


@dataclass
class Segment:
    index: int
    start: float
    end: float
    section_index: int = 0
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class Pause:
    index: int
    start: float
    end: float
    significance: PauseSignificance

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class ShortSilence:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def _gap_ms(earlier_end: float, later_start: float) -> int:
    # Whole milliseconds, so a 0.5 s gap is never 499.9999 ms because of float rounding.
    return round((later_start - earlier_end) * 1000)


def classify_pause(duration_ms: int, settings: AnalysisSettings) -> PauseSignificance:
    if duration_ms >= settings.long_silence_ms:
        return "long"
    if duration_ms >= settings.medium_pause_ms:
        return "medium"
    return "short"


def build_segments(
    regions: list[SpeechRegion], settings: AnalysisSettings
) -> tuple[list[Segment], list[Pause]]:
    """Joins speech regions into segments and lists the pauses between them."""
    ordered = sorted((r for r in regions if r.end > r.start), key=lambda r: r.start)
    if not ordered:
        return [], []

    spans: list[list[float]] = [[ordered[0].start, ordered[0].end]]
    for region in ordered[1:]:
        current = spans[-1]
        if _gap_ms(current[1], region.start) < settings.min_pause_ms:
            # Too short to be a pause (or overlapping): still the same segment.
            current[1] = max(current[1], region.end)
        else:
            spans.append([region.start, region.end])

    segments: list[Segment] = []
    pauses: list[Pause] = []
    section = 0
    for index, (start, end) in enumerate(spans):
        if index > 0:
            previous_end = spans[index - 1][1]
            significance = classify_pause(_gap_ms(previous_end, start), settings)
            if significance == "long":
                section += 1
            pauses.append(Pause(len(pauses), previous_end, start, significance))
        segments.append(Segment(index=index, start=start, end=end, section_index=section))
    return segments, pauses


def find_short_silences(
    regions: list[SpeechRegion], settings: AnalysisSettings
) -> list[ShortSilence]:
    """The silences that were too short to be pauses, so `build_segments` joined across them.

    Nothing is measured from these. They are kept so that a report of "a pause was missed
    here" can be checked against what the detector actually heard at that spot.
    """
    ordered = sorted((r for r in regions if r.end > r.start), key=lambda r: r.start)
    silences: list[ShortSilence] = []
    if not ordered:
        return silences
    speech_end = ordered[0].end
    for region in ordered[1:]:
        if 0 < _gap_ms(speech_end, region.start) < settings.min_pause_ms:
            silences.append(ShortSilence(speech_end, region.start))
        speech_end = max(speech_end, region.end)
    return silences


def assign_words(segments: list[Segment], words: list[Word]) -> int:
    """Puts every word into the segment that contains its midpoint.

    Word times come from the speech recogniser and can drift into a pause. Such a word goes
    to the nearest segment. Returns how many words had to be moved that way, which is a
    measure of how well the two sources agree.
    """
    for segment in segments:
        segment.words = []
    if not segments:
        return 0

    moved = 0
    for word in sorted(words, key=lambda w: (w.start, w.end)):
        midpoint = (word.start + word.end) / 2
        best = segments[0]
        best_distance = float("inf")
        for segment in segments:
            if segment.start <= midpoint <= segment.end:
                best, best_distance = segment, 0.0
                break
            distance = (
                segment.start - midpoint if midpoint < segment.start else midpoint - segment.end
            )
            if distance < best_distance:
                best, best_distance = segment, distance
        if best_distance > 0:
            moved += 1
        best.words.append(word)
    return moved


def is_countable_word(text: str) -> bool:
    """True for anything with a letter or digit in it; False for stray punctuation."""
    return any(character.isalnum() for character in text)


def count_words(words: list[Word]) -> int:
    return sum(1 for word in words if is_countable_word(word.text))
