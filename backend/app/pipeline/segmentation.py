"""Turns detected speech into segments and pauses. Pure functions: no audio, no models.

Vocabulary used throughout the pipeline:

- speech region: one run the voice activity detector marked as speech.
- stretch: speech regions joined across gaps that are too short to be a pause. An unbroken
  run of speaking.
- pause: the silence between two stretches. Always at least `min_pause_ms` long.
- segment: stretches joined across pauses shorter than `segment_break_ms`. Roughly one
  line of a speech. A pause shorter than that stays inside its segment: it is detected,
  measured and listed like any other, and it does not end the segment.
- short silence: a gap between speech regions that is shorter than a pause. It stays inside
  a stretch and counts as speaking time, but it is kept on record.
- section: a group of segments. A new section starts after every "long" silence.

Silence before the first stretch and after the last one is not a pause: nothing was
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
class Stretch:
    """An unbroken run of speaking. Numbered through the whole recording."""

    index: int
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Segment:
    """One or more stretches, with the short pauses between them inside it."""

    index: int
    stretches: list[Stretch]
    section_index: int = 0

    @property
    def start(self) -> float:
        return self.stretches[0].start

    @property
    def end(self) -> float:
        return self.stretches[-1].end

    @property
    def words(self) -> list[Word]:
        return [word for stretch in self.stretches for word in stretch.words]

    @property
    def speaking_seconds(self) -> float:
        """Time spent speaking: the stretches, without the pauses between them."""
        return sum(stretch.duration for stretch in self.stretches)

    @property
    def span_seconds(self) -> float:
        """From the first sound to the last, the pauses inside included."""
        return self.end - self.start

    @property
    def pause_seconds(self) -> float:
        return self.span_seconds - self.speaking_seconds

    @property
    def pause_count(self) -> int:
        return len(self.stretches) - 1


@dataclass(frozen=True)
class Pause:
    """The silence between stretch `index` and stretch `index + 1`."""

    index: int
    start: float
    end: float
    significance: PauseSignificance
    # The segments on either side. The same segment twice for a pause inside one.
    after_segment: int = 0
    before_segment: int = 0

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def inside_segment(self) -> bool:
        return self.after_segment == self.before_segment


def stretches_of(segments: list[Segment]) -> list[Stretch]:
    return [stretch for segment in segments for stretch in segment.stretches]


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
    """Joins speech regions into stretches, groups those into segments, and lists the pauses.

    Every gap of `min_pause_ms` or more is a pause. Only one of `segment_break_ms` or more
    ends a segment.
    """
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
        stretch = Stretch(index=index, start=start, end=end)
        if index == 0:
            segments.append(Segment(index=0, stretches=[stretch]))
            continue
        previous_end = spans[index - 1][1]
        gap_ms = _gap_ms(previous_end, start)
        significance = classify_pause(gap_ms, settings)
        if significance == "long":
            section += 1
        after = segments[-1].index
        if gap_ms >= settings.segment_break_ms:
            segments.append(Segment(index=after + 1, stretches=[stretch], section_index=section))
        else:
            segments[-1].stretches.append(stretch)
        pauses.append(
            Pause(len(pauses), previous_end, start, significance, after, segments[-1].index)
        )
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
    """Puts every word into the stretch that contains its midpoint.

    Word times come from the speech recogniser and can drift into a pause. Such a word goes
    to the nearest stretch. Returns how many words had to be moved that way, which is a
    measure of how well the two sources agree.

    Stretches, not segments: a pause inside a segment has words on both sides of it, and
    which side a word is on must not depend on a word time that drifted into the pause.
    """
    stretches = stretches_of(segments)
    for stretch in stretches:
        stretch.words = []
    if not stretches:
        return 0

    moved = 0
    for word in sorted(words, key=lambda w: (w.start, w.end)):
        midpoint = (word.start + word.end) / 2
        best = stretches[0]
        best_distance = float("inf")
        for stretch in stretches:
            if stretch.start <= midpoint <= stretch.end:
                best, best_distance = stretch, 0.0
                break
            distance = (
                stretch.start - midpoint if midpoint < stretch.start else midpoint - stretch.end
            )
            if distance < best_distance:
                best, best_distance = stretch, distance
        if best_distance > 0:
            moved += 1
        best.words.append(word)
    return moved


def is_countable_word(text: str) -> bool:
    """True for anything with a letter or digit in it; False for stray punctuation."""
    return any(character.isalnum() for character in text)


def count_words(words: list[Word]) -> int:
    return sum(1 for word in words if is_countable_word(word.text))
