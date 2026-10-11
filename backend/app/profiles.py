"""The delivery profiles a user can choose as a coaching target.

A profile is a description of a speaking style in words. It is not a measurement of any
actor's voice and contains no reference numbers: the app has no recording of these
characters to compare against. `focus` names the measurements that matter most for the
style; `not_measured` lists parts of the style the app cannot hear, so the screen can say so.

This is the single source for these descriptions: the frontend fetches them, and the
coaching step uses the same text.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FocusMetric:
    # Key of a metric in the analysis result, as it appears in the JSON.
    metric: str
    label: str
    looks_for: str
    # Which way the style leans on this measurement. The coaching step reads this; a profile
    # still holds no reference numbers.
    wants: Literal["low", "high"]


@dataclass(frozen=True)
class DeliveryProfile:
    id: str
    name: str
    summary: str
    targets: tuple[str, ...] = ()
    focus: tuple[FocusMetric, ...] = ()
    not_measured: tuple[str, ...] = ()


PROFILE_NOTE = (
    "A profile is a coaching target, not a rule, and not a measurement of any actor's voice. "
    "A good performance can depart from it on purpose."
)

PROFILES: tuple[DeliveryProfile, ...] = (
    DeliveryProfile(
        id="walter_white",
        name="Walter White",
        summary="Controlled and deliberate. Every phrase sounds decided in advance.",
        targets=(
            "A measured, steady pace",
            "Intentional pauses placed between thoughts",
            "Restrained intensity: the voice stays level rather than rising",
            "Clear, clean consonants",
        ),
        focus=(
            FocusMetric(
                "paceVariation",
                "Pace consistency",
                "A similar speed from phrase to phrase (low pace variation)",
                "low",
            ),
            FocusMetric(
                "medianPauseSeconds",
                "Deliberate pauses",
                "Pauses long enough to register between phrases",
                "high",
            ),
            FocusMetric(
                "energyVariation", "Restrained intensity", "Loudness that stays fairly even", "low"
            ),
        ),
        not_measured=("Clarity of consonants",),
    ),
    DeliveryProfile(
        id="joker",
        name="Joker",
        summary=(
            "Expressive and unpredictable. Calm and energetic passages are set against each other."
        ),
        targets=(
            "A rhythm that keeps changing",
            "Wide swings in pace, pitch and intensity",
            "Purposeful contrast between calm and energetic sections",
        ),
        focus=(
            FocusMetric(
                "paceVariation",
                "Changing pace",
                "Clear differences in speed between phrases (high pace variation)",
                "high",
            ),
            FocusMetric(
                "pitchVariationSemitones",
                "Pitch movement",
                "A wide spread of pitch around your own median",
                "high",
            ),
            FocusMetric(
                "energyVariation",
                "Dynamic intensity",
                "Loud and quiet stretches that clearly differ",
                "high",
            ),
        ),
        not_measured=("Whether a contrast was purposeful",),
    ),
    DeliveryProfile(
        id="thomas_shelby",
        name="Thomas Shelby",
        summary="Composed and economical. Few words, low intensity, and silence used on purpose.",
        targets=(
            "A measured pace",
            "Low-key intensity",
            "Crisp, short phrasing",
            "Deliberate silence",
        ),
        focus=(
            FocusMetric(
                "speechActiveWpm",
                "Measured pace",
                "An unhurried speaking rate while speaking",
                "low",
            ),
            FocusMetric(
                "longestPauseSeconds",
                "Deliberate silence",
                "At least one silence held long enough to carry weight",
                "high",
            ),
            FocusMetric(
                "energyVariation", "Low-key intensity", "Loudness that stays fairly even", "low"
            ),
        ),
        not_measured=("Crispness of phrasing",),
    ),
    DeliveryProfile(
        id="custom",
        name="Custom / neutral",
        summary="No style target. All measurements are shown without a profile's priorities.",
    ),
)


def get_profile(profile_id: str) -> DeliveryProfile:
    for profile in PROFILES:
        if profile.id == profile_id:
            return profile
    return PROFILES[-1]


LANGUAGES: tuple[tuple[str, str, str | None], ...] = (
    ("auto", "Detect automatically", None),
    ("en", "English", None),
    ("hi", "Hindi", None),
    (
        "hinglish",
        "Hinglish (Hindi + English)",
        "Best effort: transcribed as Hindi, so word counts and WPM are estimates.",
    ),
)
