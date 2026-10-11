"""Counting hesitation sounds in the transcript.

Only sounds that are never real words are counted ("um", "uh", "अं"…). Words such as
"like", "you know", "मतलब" or "तो" are sometimes fillers and sometimes meaningful, and a
transcript alone cannot tell which, so they are deliberately left out.

Speech recognisers tend to drop hesitation sounds from their output, so the count is a
lower bound and is always labelled as an estimate.
"""

from app.pipeline.segmentation import Word

HESITATION_SOUNDS = frozenset(
    {
        # English
        "um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mmm",
        # Hindi
        "अं", "अँ", "अम", "अम्म", "उम", "उम्म", "हम्म", "ऊँ", "एँ",
    }
)  # fmt: skip

_STRIP = " \t\n.,!?;:\"'()[]{}…-–—।॥"


def normalize(text: str) -> str:
    return text.strip(_STRIP).lower()


def find_hesitations(words: list[Word]) -> list[Word]:
    return [word for word in words if normalize(word.text) in HESITATION_SOUNDS]
