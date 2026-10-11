"""The outline of the sound wave: a picture for the screen, never a measurement."""

import numpy as np

from app.pipeline.waveform import waveform_outline


def test_each_point_holds_the_lowest_and_highest_sample_of_its_stretch():
    samples = np.array([0.1, -0.2, 0.3, 0.0, -0.5, 0.4, 0.2, 0.25], dtype=np.float32)
    outline = waveform_outline(samples, sample_rate=4, max_points=4)
    # Two samples per point.
    assert outline.seconds_per_point == 0.5
    assert outline.minimum == [-0.2, 0.0, -0.5, 0.2]
    assert outline.maximum == [0.1, 0.3, 0.4, 0.25]
    assert outline.duration_seconds == 2.0


def test_a_long_recording_is_reduced_to_a_drawable_number_of_points():
    ten_minutes = np.zeros(600 * 16_000, dtype=np.float32)
    ten_minutes[5_000_000] = 0.9
    outline = waveform_outline(ten_minutes)
    assert len(outline.minimum) == len(outline.maximum) == 2000
    assert outline.seconds_per_point == 0.3
    # The one loud sample is still there: nothing is averaged away.
    assert max(outline.maximum) == 0.9
    assert outline.maximum.index(0.9) == 5_000_000 // 4800


def test_a_short_recording_is_not_split_finer_than_the_eye_can_see():
    one_second = np.zeros(16_000, dtype=np.float32)
    outline = waveform_outline(one_second)
    assert outline.seconds_per_point == 0.005
    assert len(outline.minimum) == 200


def test_a_length_that_does_not_divide_evenly_is_padded_not_dropped():
    samples = np.array([0.1, 0.2, 0.3, 0.4, -0.9], dtype=np.float32)
    outline = waveform_outline(samples, sample_rate=2, max_points=2)
    assert outline.minimum == [0.1, -0.9]
    assert outline.maximum == [0.3, 0.4]
    assert outline.duration_seconds == 2.5


def test_a_quiet_recording_stays_quiet():
    """Nothing is stretched to fill the scale: that would hide a real difference in level."""
    quiet = np.full(16_000, 0.01, dtype=np.float32)
    outline = waveform_outline(quiet)
    assert max(outline.maximum) == 0.01 and min(outline.minimum) == 0.01


def test_an_empty_recording_has_an_empty_outline():
    outline = waveform_outline(np.array([], dtype=np.float32))
    assert (outline.duration_seconds, outline.minimum, outline.maximum) == (0.0, [], [])
