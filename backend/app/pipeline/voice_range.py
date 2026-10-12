"""Where a voice sits: its pitch and its resonance, each placed in one of three ranges.

    lower range    typically heard as a masculine voice
    neutral range  could be heard either way
    higher range   typically heard as a feminine voice

The ranges are this app's own, stated in `VoiceRangeSettings` and stored with every result.
The pitch ranges follow the speaking pitches usually given for adult voices. The resonance
ranges come from this app's own measurement of fourteen synthesised voices, described in
DOCUMENTATION_SCIENCE.md. Neither was fitted to recordings of real people.

Everything here describes a sound. A range says how a voice is likely to be heard, never
who the speaker is.
"""

from dataclasses import asdict, dataclass
from typing import Literal

Band = Literal["lower", "neutral", "higher"]
Marker = Literal["lower", "neutral", "higher", "mixed"]
Goal = Literal["none", "lower", "higher"]

GOALS: tuple[tuple[Goal, str, str | None], ...] = (
    ("none", "No goal", None),
    (
        "lower",
        "Keep my voice lower",
        "Coaching will point at the phrases where your pitch or resonance left the lower range.",
    ),
    (
        "higher",
        "Keep my voice higher",
        "Coaching will point at the phrases where your pitch or resonance left the higher range.",
    ),
)
GOAL_NOTE = (
    "Optional. The app measures where your voice sits, in pitch and in resonance, whether or "
    "not you choose a goal. With a goal, the coaching points at the phrases that left that "
    "range and gives a drill. With none, nothing about it is judged. The ranges describe how "
    "a voice is typically heard, not who is speaking."
)
_POSITION = {"lower": -1, "neutral": 0, "higher": 1}


@dataclass(frozen=True)
class VoiceRangeSettings:
    # Bumped whenever a value below changes, so results stay traceable.
    version: int = 1

    # Pitch: the median fundamental frequency of the voiced sound, in Hz.
    pitch_low_end_hz: float = 85.0
    pitch_neutral_from_hz: float = 145.0
    pitch_neutral_to_hz: float = 175.0
    pitch_high_end_hz: float = 255.0

    # Resonance: the average spacing of the first three formants, in Hz.
    resonance_low_end_hz: float = 940.0
    resonance_neutral_from_hz: float = 1040.0
    resonance_neutral_to_hz: float = 1100.0
    resonance_high_end_hz: float = 1300.0

    def __post_init__(self) -> None:
        for scale in ("pitch", "resonance"):
            low_end, neutral_from, neutral_to, high_end = self.edges(scale)
            if not 0 < low_end < neutral_from < neutral_to < high_end:
                raise ValueError(f"the {scale} ranges must run from low to high without gaps")

    def edges(self, scale: Literal["pitch", "resonance"]) -> tuple[float, float, float, float]:
        """The four values that bound the three ranges of one scale, lowest first."""
        return (
            getattr(self, f"{scale}_low_end_hz"),
            getattr(self, f"{scale}_neutral_from_hz"),
            getattr(self, f"{scale}_neutral_to_hz"),
            getattr(self, f"{scale}_high_end_hz"),
        )

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


DEFAULT_VOICE_RANGES = VoiceRangeSettings()


@dataclass(frozen=True)
class Placement:
    band: Band
    # How far into its range the value lies, 0 to 100. See `place`.
    percent: int


def place(
    value: float, scale: Literal["pitch", "resonance"], settings: VoiceRangeSettings
) -> Placement:
    """The range a value falls in, and how far into that range it lies.

    The percentage is a position, not a probability. In the lower and higher ranges it is
    0 at the edge shared with the neutral range and 100 at the far end, and stays 100
    beyond it. In the neutral range it is 100 in the middle and 0 at either edge.
    """
    low_end, neutral_from, neutral_to, high_end = settings.edges(scale)
    if value < neutral_from:
        band, share = "lower", (neutral_from - value) / (neutral_from - low_end)
    elif value > neutral_to:
        band, share = "higher", (value - neutral_to) / (high_end - neutral_to)
    else:
        middle, half = (neutral_from + neutral_to) / 2, (neutral_to - neutral_from) / 2
        band, share = "neutral", 1 - abs(value - middle) / half
    return Placement(band, round(100 * min(1.0, max(0.0, share))))


def overall_marker(pitch: Band | None, resonance: Band | None) -> Marker | None:
    """One word for a stretch of speech, from where its pitch and its resonance each sit.

    Both in the same range: that range. One neutral and the other not: the other's range,
    since the voice leans that way. One lower and one higher: "mixed", because a listener
    is given two different cues. With only one of the two measured, that one decides.
    """
    known = [band for band in (pitch, resonance) if band is not None]
    if not known:
        return None
    lean = sum(_POSITION[band] for band in known)
    if lean < 0:
        return "lower"
    if lean > 0:
        return "higher"
    return "neutral" if all(band == "neutral" for band in known) else "mixed"
