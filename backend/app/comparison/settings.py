"""The thresholds used when a take is compared with a reference recording.

Like the analysis thresholds and the coaching bands, these are this app's own choices. They
are sent with every comparison so that its wording can be explained.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ComparisonSettings:
    # Bumped whenever a default below changes.
    version: int = 1

    # Share of the reference's words that must be found in the take, in the same order,
    # for the two to count as the same passage. Between the two values: partly.
    matched_coverage: float = 0.6
    partial_coverage: float = 0.3
    # A pause is located in the other recording through matched words on either side of
    # it. Those words may be at most this many words away from the pause.
    max_anchor_gap_words: int = 3

    # A phrase's pace is compared when this share of its words was matched, it has at
    # least this many words, and the matched stretch lasts this long in both recordings.
    phrase_min_coverage: float = 0.6
    phrase_min_words: int = 3
    phrase_min_seconds: float = 1.5

    # What counts as a difference worth listing.
    # A pause that only one recording has, from this length.
    notable_pause_seconds: float = 1.0
    # A pause both have, when the lengths differ by at least this much and this share.
    notable_pause_change_seconds: float = 0.5
    notable_pause_change_ratio: float = 0.4
    # A phrase, when its pace differs from the reference's by this share.
    notable_phrase_pace_ratio: float = 0.25
    # The whole recording, when its speaking pace differs by this share.
    notable_overall_pace_ratio: float = 0.15
    # How many of the biggest differences are listed.
    max_differences: int = 5
    # Seconds of audio played either side of a pause, so it is heard in context.
    pause_context_seconds: float = 1.5

    def __post_init__(self) -> None:
        if not 0 < self.partial_coverage <= self.matched_coverage <= 1:
            raise ValueError("coverage thresholds must satisfy 0 < partial <= matched <= 1")
        if self.max_anchor_gap_words < 0 or self.max_differences < 1:
            raise ValueError("counts must not be negative")

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


DEFAULT_COMPARISON_SETTINGS = ComparisonSettings()
