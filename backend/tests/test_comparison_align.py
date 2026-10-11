"""Lining up the words of two recordings of the same passage."""

import random

import pytest

from app.comparison.align import align_words, match_key


@pytest.mark.parametrize(
    ("spoken", "key"),
    [
        ("Danger,", "danger"),
        ("danger.", "danger"),
        ("don't", "dont"),
        ("2", "2"),
        ("…", ""),
        ("—", ""),
        # The recogniser's Hindi spelling varies in the vowel signs and half-letters.
        ("खतरे", "खतर"),
        ("खत्रे", "खतर"),
        ("हूँ", "ह"),
        ("हु,", "ह"),
        ("आद्मी", "आदम"),
        ("आदमी", "आदम"),
    ],
)
def test_two_spellings_of_one_spoken_word_share_a_key(spoken, key):
    assert match_key(spoken) == key


def keys(text: str) -> list[str]:
    return [match_key(word) for word in text.split()]


def test_identical_passages_line_up_word_for_word():
    words = keys("I am the one who knocks")
    alignment = align_words(words, words)
    assert alignment.pairs == [(i, i) for i in range(6)]
    assert alignment.coverage == 1.0


def test_a_dropped_word_and_an_added_word_leave_the_rest_in_line():
    reference = keys("I am not in danger Skylar I am the danger")
    take = keys("Listen I am not in danger I am the danger")
    alignment = align_words(reference, take)
    # "Skylar" has no partner in the take, and "Listen" none in the reference.
    assert alignment.pairs == [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (4, 5),
        (6, 6),
        (7, 7),
        (8, 8),
        (9, 9),
    ]
    assert alignment.coverage == pytest.approx(0.9)


def test_a_misheard_word_does_not_break_the_line_up():
    alignment = align_words(keys("a guy opens his door"), keys("a guy open his door"))
    assert alignment.pairs == [(0, 0), (1, 1), (3, 3), (4, 4)]


def test_hindi_lines_up_despite_spelling_differences():
    reference = keys("मैं खतरे में नहीं हूँ, मैं ही खतरा हूँ")
    take = keys("मैं खत्रे में नहीं हु, मैं ही खत्रा हु")
    assert align_words(reference, take).coverage == 1.0


def test_words_with_nothing_to_match_on_are_skipped():
    alignment = align_words(["a", "", "b"], ["", "a", "b", "c"])
    assert alignment.pairs == [(0, 1), (2, 2)]
    assert (alignment.reference_words, alignment.take_words) == (2, 3)


def test_nothing_to_line_up_is_not_an_error():
    assert align_words([], ["a"]).coverage == 0.0
    assert align_words(["a"], []).pairs == []
    assert align_words(["a", "b"], ["c", "d"]).coverage == 0.0


def test_a_repeated_line_is_matched_to_the_right_repetition():
    """The line-up is worked out for the whole passage, not block by block."""
    line = keys("you clearly do not know who you are talking to so let me clue you in")
    passage = line * 40
    randomness = random.Random(7)
    # A take of the same passage with one word in twelve dropped.
    kept = [i for i in range(len(passage)) if randomness.random() > 1 / 12]
    alignment = align_words(passage, [passage[i] for i in kept])

    assert alignment.coverage == pytest.approx(len(kept) / len(passage))
    # Every kept word is matched within a word or two of where it really came from; the
    # words of a line repeat, so a neighbour with the same spelling is as good a match.
    assert all(abs(reference - kept[take]) <= 3 for reference, take in alignment.pairs)


def test_a_ten_minute_passage_is_lined_up_quickly():
    import time

    words = [f"w{random.Random(i).randrange(300)}" for i in range(2600)]
    started = time.perf_counter()
    align_words(words, words[::-1])
    assert time.perf_counter() - started < 2.0
