"""Lines up the words of two recordings of the same passage.

The speech recogniser hears each recording separately, so the two transcripts never agree
word for word: a word is misheard in one, dropped in the other, spelt differently in Hindi.
Lining them up means finding the longest run of words the two have in common, in order,
and treating those as the same moments in the passage.

Nothing here looks at the audio. It works only on the recognised words and their times.
"""

import unicodedata
from dataclasses import dataclass

import numpy as np


def match_key(text: str) -> str:
    """What two spellings of the same spoken word have in common.

    Case and punctuation are dropped. So are combining marks, which in Devanagari are the
    vowel signs, the nasal dot and the half-letter mark. The recogniser's Hindi spelling
    varies exactly there ("खतरे" / "खत्रे", "हूँ" / "हु"), so both come out as the same key.

    Some different words share a key this way ("में" and "मैं"). That is accepted: words
    are matched in order, so a stray equal key cannot move the line-up far.
    """
    kept = [
        character
        for character in unicodedata.normalize("NFC", text).lower()
        # Letters and digits of any script; marks, punctuation and spaces are left out.
        if unicodedata.category(character)[0] in ("L", "N")
    ]
    return "".join(kept)


@dataclass(frozen=True)
class Alignment:
    """Which word of the reference is which word of the take, for the words they share."""

    # (reference word index, take word index), in order.
    pairs: list[tuple[int, int]]
    reference_words: int
    take_words: int

    @property
    def coverage(self) -> float:
        """Share of the reference's words that were found in the take."""
        return len(self.pairs) / self.reference_words if self.reference_words else 0.0


def align_words(reference: list[str], take: list[str]) -> Alignment:
    """Matches two lists of word keys. Empty keys never match anything.

    Finds the longest list of words that appears in both, in the same order (the "longest
    common subsequence"). It is worked out for the whole passage at once, so a repeated
    line is matched to the right repetition wherever that leaves the most words in line.
    """
    reference_index = [i for i, key in enumerate(reference) if key]
    take_index = [i for i, key in enumerate(take) if key]
    if not reference_index or not take_index:
        return Alignment([], len(reference_index), len(take_index))

    # Words become numbers, so a whole row of comparisons is one array operation.
    ids: dict[str, int] = {}
    a = np.array([ids.setdefault(reference[i], len(ids)) for i in reference_index])
    b = np.array([ids.setdefault(take[i], len(ids)) for i in take_index])

    # lengths[i, j]: how many words the first i reference words and first j take words share.
    lengths = np.zeros((len(a) + 1, len(b) + 1), dtype=np.int32)
    for i in range(1, len(a) + 1):
        previous = lengths[i - 1]
        row = np.maximum(previous[1:], previous[:-1] + (b == a[i - 1]))
        lengths[i, 1:] = np.maximum.accumulate(row)

    # Walk back from the end to read off which words were matched.
    pairs: list[tuple[int, int]] = []
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if a[i - 1] == b[j - 1] and lengths[i, j] == lengths[i - 1, j - 1] + 1:
            pairs.append((reference_index[i - 1], take_index[j - 1]))
            i, j = i - 1, j - 1
        elif lengths[i - 1, j] >= lengths[i, j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return Alignment(pairs, len(reference_index), len(take_index))
