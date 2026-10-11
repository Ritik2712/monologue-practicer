"""The settings that feedback is allowed to adjust, and how far.

Everything adjustable is listed here, with its default, its lowest and highest allowed
value, and the size of one step. A setting that is not in this file is never changed by
feedback. Nothing here reads the database.
"""

from dataclasses import dataclass
from typing import Literal

from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from app.pipeline.settings import DEFAULT_SETTINGS

Group = Literal["analysis", "coaching"]

# A setting moves only when at least this many reports agree ...
MIN_REPORTS = 3
# ... from at least this many different recordings, so one odd recording changes nothing ...
MIN_RECORDINGS = 2
# ... and they make up at least this share of the reports being looked at.
MIN_AGREEMENT = 0.75
# Only the most recent reports about a setting are looked at.
WINDOW = 10
# Moving a setting back the way it just came needs more reports, so it cannot flip-flop.
REVERSAL_REPORTS = 5

# The kinds of finding a correction can be about. Each has its own priority.
CORRECTION_KINDS: dict[str, str] = {
    "pace": "overall pace",
    "pace_variation": "how even the pace is",
    "pause_length": "pause length",
    "no_pauses": "missing pauses",
    "held_silence": "holding a silence",
    "accidental_pauses": "accidental pauses",
    "loudness_variation": "loudness",
    "pitch_variation": "pitch",
    "fast_segment": "a rushed phrase",
    "slow_segment": "a slow phrase",
    "hesitations": "hesitation sounds",
    "no_emphasis": "emphasis",
}
PRIORITY_PREFIX = "priority_"


@dataclass(frozen=True)
class Adaptive:
    name: str
    group: Group
    label: str
    description: str
    unit: str
    default: float
    minimum: float
    maximum: float
    # Values sit on a grid this far apart, and one adjustment moves at least this much.
    step: float
    # The most one adjustment may move the value.
    max_step: float
    # Decimal places the value is kept and shown to.
    digits: int
    # What a higher and a lower value mean, to finish "… made <words>".
    raised: str
    lowered: str

    def clamp(self, value: float) -> float:
        return round(min(self.maximum, max(self.minimum, value)), self.digits)


MIN_PAUSE = Adaptive(
    name="min_pause_ms",
    group="analysis",
    label="Minimum pause",
    description=(
        "A silence at least this long counts as a pause and ends a phrase. Shorter silences "
        "stay inside the phrase as speaking time."
    ),
    unit="ms",
    default=float(DEFAULT_SETTINGS.min_pause_ms),
    # Below a quarter of a second a silence is usually part of pronouncing a word.
    minimum=250.0,
    # A silence this long is a pause for any speaker, so the threshold never passes it.
    maximum=800.0,
    step=50.0,
    max_step=100.0,
    digits=0,
    raised="raised",
    lowered="lowered",
)


def priority_name(kind: str) -> str:
    return f"{PRIORITY_PREFIX}{kind}"


def _priority(kind: str, about: str) -> Adaptive:
    return Adaptive(
        name=priority_name(kind),
        group="coaching",
        label=f"Priority of corrections about {about}",
        description=(
            "How readily this kind of correction makes it into the top three. At 1 it is "
            "ranked on the measurements alone. Lower moves it down the list. The measurement "
            "behind it is always still shown."
        ),
        unit="",
        default=1.0,
        # Never zero: a correction can be moved down the list, not switched off.
        minimum=0.4,
        maximum=1.0,
        step=0.2,
        max_step=0.2,
        digits=1,
        raised="raised",
        lowered="lowered",
    )


ADAPTIVE: dict[str, Adaptive] = {
    setting.name: setting
    for setting in (
        MIN_PAUSE,
        *(_priority(kind, about) for kind, about in CORRECTION_KINDS.items()),
    )
}

DEFAULT_VALUES: dict[str, float] = {name: setting.default for name, setting in ADAPTIVE.items()}

# Thresholds that feedback never changes. Listed on the calibration screen so nothing that
# shapes a result is hidden. (name, label, value, unit)
#
# The speech detection threshold is here on purpose. Measured on the real detector, moving
# it between 0.35 and 0.65 shifts where a phrase starts or ends by 0.2 s at most and never
# adds or removes a pause, while below 0.3 it starts swallowing real pauses. A setting that
# changes nothing a user can see must not be "learned" from their reports.
FIXED: tuple[tuple[str, str, float, str], ...] = (
    (
        "vad_threshold",
        "How sure the detector must be that a sound is speech (0 to 1)",
        DEFAULT_SETTINGS.vad_threshold,
        "",
    ),
    (
        "medium_pause_ms",
        "A pause is “medium” from",
        DEFAULT_SETTINGS.medium_pause_ms,
        "ms",
    ),
    (
        "long_silence_ms",
        "A pause is a “long silence”, starting a new section, from",
        DEFAULT_SETTINGS.long_silence_ms,
        "ms",
    ),
    (
        "min_segment_ms",
        "Shortest phrase whose WPM is trusted",
        DEFAULT_SETTINGS.min_segment_ms,
        "ms",
    ),
    (
        "min_segment_words",
        "Fewest words for a trusted WPM",
        DEFAULT_SETTINGS.min_segment_words,
        "words",
    ),
    (
        "wpm_outlier",
        "A phrase is flagged for review above",
        DEFAULT_SETTINGS.wpm_outlier,
        "WPM",
    ),
    (
        "slow_wpm",
        "Coaching calls a pace “unhurried” below",
        DEFAULT_COACHING_SETTINGS.slow_wpm,
        "WPM",
    ),
    (
        "fast_wpm",
        "Coaching calls a pace “fast” above",
        DEFAULT_COACHING_SETTINGS.fast_wpm,
        "WPM",
    ),
    (
        "registering_pause_seconds",
        "Coaching says a pause “registers” from",
        DEFAULT_COACHING_SETTINGS.registering_pause_seconds,
        "s",
    ),
    (
        "held_silence_seconds",
        "Coaching calls a pause a “held silence” from",
        DEFAULT_COACHING_SETTINGS.held_silence_seconds,
        "s",
    ),
)


def show(setting: Adaptive, value: float) -> str:
    """A value the way the screen writes it: "450 ms", "0.55", "0.8"."""
    text = f"{value:.{setting.digits}f}"
    return f"{text} {setting.unit}" if setting.unit else text
