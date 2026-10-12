"""Placing a pitch or a resonance in one of the three ranges, and the percentage with it."""

import pytest

from app.pipeline.voice_range import (
    DEFAULT_VOICE_RANGES,
    Placement,
    VoiceRangeSettings,
    overall_marker,
    place,
)


def placed(value: float, scale: str = "pitch") -> Placement:
    return place(value, scale, DEFAULT_VOICE_RANGES)


def test_the_default_ranges_are_stated_and_run_from_low_to_high():
    assert DEFAULT_VOICE_RANGES.edges("pitch") == (85.0, 145.0, 175.0, 255.0)
    assert DEFAULT_VOICE_RANGES.edges("resonance") == (940.0, 1040.0, 1100.0, 1300.0)
    assert DEFAULT_VOICE_RANGES.to_dict()["version"] == 1


@pytest.mark.parametrize(
    ("hz", "band", "percent"),
    [
        # The lower range: 0% at the edge of the neutral range, 100% at the deep end.
        (144.9, "lower", 0),
        (130.0, "lower", 25),  # (145 - 130) / (145 - 85)
        (115.0, "lower", 50),
        (85.0, "lower", 100),
        # The higher range: 0% at the edge of the neutral range, 100% at the high end.
        (175.1, "higher", 0),
        (195.0, "higher", 25),  # (195 - 175) / (255 - 175)
        (215.0, "higher", 50),
        (255.0, "higher", 100),
        # The neutral range: 100% in the middle, 0% at either edge.
        (145.0, "neutral", 0),
        (152.5, "neutral", 50),
        (160.0, "neutral", 100),
        (167.5, "neutral", 50),
        (175.0, "neutral", 0),
    ],
)
def test_a_pitch_is_placed_by_its_position_inside_its_range(hz, band, percent):
    assert placed(hz) == Placement(band, percent)


def test_a_value_beyond_the_far_end_of_a_range_stays_at_100_percent():
    assert placed(60.0) == Placement("lower", 100)
    assert placed(400.0) == Placement("higher", 100)


def test_the_edges_of_the_neutral_range_belong_to_it():
    assert placed(145.0).band == placed(175.0).band == "neutral"
    assert placed(144.99).band == "lower"
    assert placed(175.01).band == "higher"


@pytest.mark.parametrize(
    ("hz", "band", "percent"),
    [
        (990.0, "lower", 50),  # (1040 - 990) / (1040 - 940)
        (1070.0, "neutral", 100),
        (1200.0, "higher", 50),  # (1200 - 1100) / (1300 - 1100)
    ],
)
def test_resonance_has_ranges_of_its_own(hz, band, percent):
    assert placed(hz, "resonance") == Placement(band, percent)


def test_ranges_that_overlap_or_run_backwards_are_refused():
    with pytest.raises(ValueError, match="pitch"):
        VoiceRangeSettings(pitch_neutral_from_hz=180.0)
    with pytest.raises(ValueError, match="resonance"):
        VoiceRangeSettings(resonance_high_end_hz=1000.0)


@pytest.mark.parametrize(
    ("pitch", "resonance", "marker"),
    [
        ("lower", "lower", "lower"),
        ("higher", "higher", "higher"),
        ("neutral", "neutral", "neutral"),
        # One neutral, the other not: the voice leans the other's way.
        ("neutral", "lower", "lower"),
        ("higher", "neutral", "higher"),
        # The two cues disagree.
        ("lower", "higher", "mixed"),
        ("higher", "lower", "mixed"),
        # Only one of the two was measured: that one decides.
        ("lower", None, "lower"),
        (None, "higher", "higher"),
        (None, None, None),
    ],
)
def test_one_marker_sums_up_pitch_and_resonance(pitch, resonance, marker):
    assert overall_marker(pitch, resonance) == marker
