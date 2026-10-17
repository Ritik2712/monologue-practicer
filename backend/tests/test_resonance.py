"""Resonance: formants found by the real analysis, on sounds whose formants are known."""

import numpy as np
import pytest

from app.pipeline import resonance
from app.pipeline.segmentation import Stretch
from app.pipeline.settings import SAMPLE_RATE


def vowel(formants: tuple[float, ...], *, seconds: float = 1.5, pitch_hz: float = 120.0):
    """A buzz at `pitch_hz` passed through one resonator per formant: a crude, exact vowel."""
    from scipy.signal import lfilter

    samples = np.zeros(int(seconds * SAMPLE_RATE))
    samples[:: int(SAMPLE_RATE / pitch_hz)] = 1.0
    for hz in formants:
        # A two-pole resonator at `hz`, 80 Hz wide.
        radius = np.exp(-np.pi * 80.0 / SAMPLE_RATE)
        theta = 2 * np.pi * hz / SAMPLE_RATE
        samples = lfilter([1.0], [1.0, -2 * radius * np.cos(theta), radius**2], samples)
    return (0.3 * samples / np.max(np.abs(samples))).astype(np.float32)


def whole(samples: np.ndarray) -> list[Stretch]:
    return [Stretch(index=0, start=0.0, end=samples.shape[0] / SAMPLE_RATE)]


def spacing(samples: np.ndarray, segments: list[Stretch] | None = None) -> float | None:
    track = resonance.measure_resonance(samples, whole(samples) if segments is None else segments)
    return track.spacing_hz(0.0, 1e9, min_frames=resonance.MIN_RECORDING_FRAMES)


def test_the_spacing_of_an_evenly_spaced_ladder_is_its_step():
    # A uniform tube 17.5 cm long: formants at 500, 1500 and 2500 Hz, 1000 Hz apart.
    assert resonance.formant_spacing(np.array([500.0, 1500.0, 2500.0])) == pytest.approx(1000.0)
    assert resonance.formant_spacing(np.array([600.0, 1800.0, 3000.0])) == pytest.approx(1200.0)


def test_the_higher_formants_weigh_more_because_they_depend_less_on_the_vowel():
    ladder = np.array([500.0, 1500.0, 2500.0])
    moved_first = resonance.formant_spacing(ladder + [100.0, 0.0, 0.0])
    moved_third = resonance.formant_spacing(ladder + [0.0, 0.0, 100.0])
    assert moved_first - 1000.0 < (moved_third - 1000.0) / 4


def test_known_formants_are_found_and_a_deeper_voice_reads_lower_than_a_brighter_one():
    samples = vowel((500, 1500, 2500))
    deep = resonance.measure_resonance(samples, whole(samples))
    found = deep.formants_hz(0.0, 1e9, min_frames=resonance.MIN_RECORDING_FRAMES)
    assert found == pytest.approx([500, 1500, 2500], abs=40)

    assert spacing(vowel((500, 1500, 2500))) == pytest.approx(1000, abs=20)
    assert spacing(vowel((600, 1800, 3000))) == pytest.approx(1200, abs=20)


def test_the_note_the_voice_speaks_on_does_not_move_its_resonance():
    low_note = spacing(vowel((500, 1500, 2500), pitch_hz=100.0))
    high_note = spacing(vowel((500, 1500, 2500), pitch_hz=220.0))
    assert low_note == pytest.approx(high_note, abs=30)


def test_a_quieter_recording_of_the_same_voice_reads_the_same():
    samples = vowel((550, 1650, 2750))
    assert spacing(samples * 0.05) == pytest.approx(spacing(samples), abs=5)


def test_only_speech_is_measured_and_silence_gives_nothing():
    samples = np.concatenate([vowel((500, 1500, 2500)), np.zeros(SAMPLE_RATE, dtype=np.float32)])
    speech = [Stretch(index=0, start=0.0, end=1.5)]
    track = resonance.measure_resonance(samples, speech)

    assert track.times.size > 0 and track.times.max() <= 1.5
    assert resonance.measure_resonance(samples, []).times.size == 0
    silence = np.zeros(2 * SAMPLE_RATE, dtype=np.float32)
    assert resonance.measure_resonance(silence, whole(silence)).times.size == 0
    assert spacing(silence) is None


def test_too_few_frames_is_reported_as_unavailable_not_as_a_number():
    samples = vowel((500, 1500, 2500))
    track = resonance.measure_resonance(samples, whole(samples))

    assert track.spacing_hz(0.0, 0.1, min_frames=resonance.MIN_SEGMENT_FRAMES) is None
    assert track.spacing_hz(0.0, 1.0, min_frames=resonance.MIN_SEGMENT_FRAMES) is not None
    assert track.frame_count(0.0, 0.1) < resonance.MIN_SEGMENT_FRAMES
