"""The bands that turn a measurement into a word such as "fast" or "even".

A measurement on its own says nothing about delivery: "pitch varied by 1.6 semitones" only
becomes useful once something says whether that is a little or a lot. These bands do that.

They are this app's own rough choices for orientation. They are not taken from any actor's
voice, and they are not targets. Every coaching result stores a copy, so its wording can
always be explained by the values that were active at the time.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CoachingSettings:
    # Bumped whenever a default below changes, so results stay traceable.
    # 2: the delivery-pace bands added. Coaching of version 1 judged pace on the
    #    speech-active WPM, the only pace there was.
    version: int = 2
    # Which version of the user's calibration supplied the priorities below. 1 means none.
    calibration_version: int = 1
    # How readily each kind of correction makes the top three, as (finding kind, priority)
    # pairs. Feedback on corrections moves these; a kind that is not listed has priority 1.
    priorities: tuple[tuple[str, float], ...] = ()

    # Delivery pace: words over the length of the phrases, the short pauses inside them
    # counted. Below the first is "unhurried", above the second "fast". On the three real
    # recordings this was set from, delivery pace came to 85 to 90% of the speech-active
    # WPM, so these are the bands below scaled by that and rounded.
    delivery_slow_wpm: float = 125.0
    delivery_fast_wpm: float = 175.0
    # Speech-active WPM (every pause left out). Used only for a result made before the
    # delivery pace existed, where it is the one pace there is.
    slow_wpm: float = 140.0
    fast_wpm: float = 200.0
    # Pace variation as a share of the speaker's own typical pace. 0.10 means 10%.
    even_pace_ratio: float = 0.10
    varied_pace_ratio: float = 0.25
    # A median pause at least this long "registers" with a listener.
    registering_pause_seconds: float = 1.0
    # A single pause at least this long is a "held silence".
    held_silence_seconds: float = 2.0
    # Spread of loudness across speech, in dB.
    even_loudness_db: float = 3.0
    varied_loudness_db: float = 6.0
    # Spread of pitch around the speaker's own median, in semitones.
    narrow_pitch_semitones: float = 2.0
    wide_pitch_semitones: float = 4.0
    # With no pause at all, speech shorter than this is not remarked on.
    no_pause_min_speech_seconds: float = 15.0
    # At most this many "this phrase was faster/slower" findings of each kind.
    max_segment_findings: int = 2

    def __post_init__(self) -> None:
        ordered = (
            (self.delivery_slow_wpm, self.delivery_fast_wpm),
            (self.slow_wpm, self.fast_wpm),
            (self.even_pace_ratio, self.varied_pace_ratio),
            (self.even_loudness_db, self.varied_loudness_db),
            (self.narrow_pitch_semitones, self.wide_pitch_semitones),
        )
        if any(not 0 < low < high for low, high in ordered):
            raise ValueError("each lower band must be positive and below its upper band")
        if self.registering_pause_seconds <= 0 or self.held_silence_seconds <= 0:
            raise ValueError("pause bands must be positive")

    def priority(self, kind: str) -> float:
        return dict(self.priorities).get(kind, 1.0)

    def to_dict(self) -> dict[str, float | int]:
        values = asdict(self)
        del values["priorities"]
        values.update({f"priority_{kind}": value for kind, value in self.priorities})
        return values


DEFAULT_COACHING_SETTINGS = CoachingSettings()
