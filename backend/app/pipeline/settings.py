"""The thresholds that turn raw measurements into pauses, segments and reliability labels.

Every analysis stores a copy of the settings that produced it, so an old result can always be
explained by the values that were active at the time.
"""

from dataclasses import asdict, dataclass, fields

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class AnalysisSettings:
    # Bumped whenever a default below changes, so results stay traceable.
    # 2: `pitch_voiced_probability` added, at 0.3. Results of version 1 used 0.5.
    # 3: `segment_break_ms` added, at 1000. In results of versions 1 and 2 every pause ended
    #    a segment, which is the same as a segment break equal to the minimum pause.
    version: int = 3
    # Which version of the user's calibration supplied the values that feedback can adjust
    # (the minimum pause and the speech detection threshold). 1 means the defaults.
    calibration_version: int = 1

    # A silence at least this long is a pause. It is measured, listed and counted.
    min_pause_ms: int = 500
    # A pause at least this long also ends a segment. A shorter one stays inside its
    # segment, so a line spoken with brief stops in it is still one line.
    segment_break_ms: int = 1000
    # Pauses from here up to the long-silence boundary are "medium"; shorter ones are "short".
    medium_pause_ms: int = 1000
    # A pause at least this long is a "long" silence and starts a new section of the clip.
    # This is NOT the minimum pause: shorter pauses are still detected and counted.
    long_silence_ms: int = 5000

    # A segment needs at least this much speech and this many words for its WPM to be trusted.
    min_segment_ms: int = 2000
    min_segment_words: int = 3
    # Faster than this is flagged for review. The measured value is never changed or capped.
    wpm_outlier: float = 180.0
    # Average word confidence below this marks word-based numbers as uncertain.
    low_confidence: float = 0.5
    # A segment this far (as a share) from the speaker's own typical pace in this recording
    # is labelled faster or slower. 0.25 means 25% above or below.
    pace_deviation_ratio: float = 0.25
    # A "typical pace" needs at least this many reliably measured segments.
    min_segments_for_typical_pace: int = 3

    # Voice activity detection (Silero). Padding is kept small so pause lengths stay accurate.
    vad_threshold: float = 0.5
    vad_min_speech_ms: int = 100
    vad_min_silence_ms: int = 100
    vad_speech_pad_ms: int = 30

    # The pitch tracker says how sure it is that a moment is voiced. Moments it is less sure
    # of than this are left out. At the 0.5 used at first, a deeper voice kept only 6 to 20%
    # of its moments and a short recording of one often had no pitch at all, while a higher
    # voice kept 40 to 55%. At 0.3 a deeper voice keeps about three times as many and its
    # median pitch moves by 2 Hz or less. See DOCUMENTATION_SCIENCE.md.
    pitch_voiced_probability: float = 0.3

    def __post_init__(self) -> None:
        if not 0 < self.min_pause_ms <= self.medium_pause_ms <= self.long_silence_ms:
            raise ValueError("pause thresholds must satisfy min <= medium <= long")
        if not self.min_pause_ms <= self.segment_break_ms <= self.long_silence_ms:
            raise ValueError("segment_break_ms must lie between min_pause_ms and long_silence_ms")
        if self.vad_min_silence_ms >= self.min_pause_ms:
            raise ValueError("vad_min_silence_ms must be shorter than min_pause_ms")
        if self.min_segment_ms <= 0 or self.min_segment_words < 1 or self.wpm_outlier <= 0:
            raise ValueError("segment reliability thresholds must be positive")
        if not 0 < self.pace_deviation_ratio < 1 or self.min_segments_for_typical_pace < 2:
            raise ValueError("typical-pace thresholds are out of range")
        if not 0 < self.pitch_voiced_probability < 1:
            raise ValueError("pitch_voiced_probability must be between 0 and 1")

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, stored: dict) -> "AnalysisSettings":
        """The settings a stored result was made with.

        Values the result does not record (it is older than they are) take today's default,
        and names this version of the code does not know are ignored. The one exception is
        the segment break: a result from before it existed ended a segment at every pause.
        """
        known = {field.name for field in fields(cls)}
        values = {name: value for name, value in stored.items() if name in known}
        if "segment_break_ms" not in values:
            values["segment_break_ms"] = values.get("min_pause_ms", cls.min_pause_ms)
        return cls(**values)


DEFAULT_SETTINGS = AnalysisSettings()
