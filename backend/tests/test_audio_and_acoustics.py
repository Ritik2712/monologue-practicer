import math

import numpy as np
import pytest

from app.pipeline import acoustics
from app.pipeline.audio import clipping_ratio, decode_audio, probe_audio
from app.pipeline.errors import PipelineError
from app.pipeline.fillers import find_hesitations
from app.pipeline.segmentation import Segment, Word
from app.pipeline.settings import DEFAULT_SETTINGS, SAMPLE_RATE
from app.pipeline.vad import detect_speech
from tests.conftest import wav_bytes


def tone(seconds: float, frequency: float = 220.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * math.pi * frequency * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE), dtype=np.float32)


# --- Decoding ----------------------------------------------------------------------------


def test_decoding_converts_any_file_to_mono_16khz(tmp_path):
    path = tmp_path / "stereo.wav"
    path.write_bytes(wav_bytes(2.0, rate=44_100, channels=2))

    samples = decode_audio(path)

    assert samples.dtype == np.float32
    assert samples.ndim == 1
    assert samples.shape[0] == pytest.approx(2.0 * SAMPLE_RATE, abs=SAMPLE_RATE * 0.05)
    assert 0.25 < np.abs(samples).max() <= 1.0


def test_probe_reads_the_length_without_decoding(tmp_path):
    path = tmp_path / "clip.wav"
    path.write_bytes(wav_bytes(3.0))
    probe = probe_audio(path)
    assert probe.has_audio
    assert probe.duration_seconds == pytest.approx(3.0, abs=0.05)


def test_a_file_that_is_not_audio_is_rejected_with_a_safe_message(tmp_path):
    path = tmp_path / "secret-folder-name" / "notes.mp3"
    path.parent.mkdir()
    path.write_bytes(b"this is not audio at all\n" * 40)

    for read in (probe_audio, decode_audio):
        with pytest.raises(PipelineError) as raised:
            read(path)
        assert raised.value.code == "unreadable_audio"
        assert not raised.value.retryable
        assert "secret-folder-name" not in raised.value.message


def test_decoding_stops_when_the_recording_is_over_the_limit(tmp_path):
    path = tmp_path / "long.wav"
    path.write_bytes(wav_bytes(4.0))
    with pytest.raises(PipelineError) as raised:
        decode_audio(path, max_seconds=2.0)
    assert raised.value.code == "audio_too_long"
    assert decode_audio(path, max_seconds=5.0).shape[0] == pytest.approx(4.0 * SAMPLE_RATE, abs=800)


def test_clipping_ratio_counts_samples_at_full_scale():
    samples = np.array([0.0, 0.5, 1.0, -1.0, 0.2, 0.9995, -0.3, 0.1], dtype=np.float32)
    assert clipping_ratio(samples) == pytest.approx(3 / 8)
    assert clipping_ratio(np.array([], dtype=np.float32)) == 0


# --- Speech detection --------------------------------------------------------------------


def test_the_speech_detector_finds_nothing_in_silence_or_a_plain_tone():
    assert detect_speech(silence(3.0), DEFAULT_SETTINGS) == []
    # A steady tone is sound but not speech; a loudness threshold would get this wrong.
    assert detect_speech(tone(3.0), DEFAULT_SETTINGS) == []


# --- Loudness ----------------------------------------------------------------------------


def test_energy_is_reported_in_decibels_relative_to_full_scale():
    track = acoustics.measure_energy(tone(1.0, amplitude=0.5))
    # RMS of a sine is amplitude / sqrt(2): 0.5 -> -9.03 dBFS.
    assert track.mean_db(0.1, 0.9) == pytest.approx(-9.03, abs=0.1)
    assert acoustics.power_to_db(0.0) == acoustics.FLOOR_DB


def test_a_part_ten_times_quieter_measures_twenty_decibels_lower():
    samples = np.concatenate([tone(2.0, amplitude=0.5), tone(2.0, amplitude=0.05)])
    track = acoustics.measure_energy(samples)
    loud = track.mean_db(0.2, 1.8)
    quiet = track.mean_db(2.2, 3.8)
    assert loud - quiet == pytest.approx(20, abs=0.2)


def test_signal_to_noise_compares_speech_with_the_background_between_it():
    samples = np.concatenate([tone(2.0, amplitude=0.3), tone(2.0, amplitude=0.003), tone(2.0, amplitude=0.3)])  # fmt: skip
    track = acoustics.measure_energy(samples)
    segments = [Segment(0, 0.0, 2.0), Segment(1, 4.0, 6.0)]

    summary = acoustics.summarize_energy(track, segments)

    assert summary.snr_db == pytest.approx(40, abs=1)
    # Both spoken parts are equally loud, so loudness barely varies.
    assert summary.variation_db == pytest.approx(0, abs=0.5)


def test_energy_summary_is_empty_without_speech_or_background():
    track = acoustics.measure_energy(tone(2.0))
    assert acoustics.summarize_energy(track, []) == acoustics.EnergySummary(None, None)
    # Speech from start to end leaves no background to compare against.
    assert acoustics.summarize_energy(track, [Segment(0, 0.0, 2.0)]).snr_db is None


def test_the_timeline_has_one_point_per_quarter_second_and_is_capped_for_long_clips():
    seconds_per_point, values = acoustics.energy_timeline(acoustics.measure_energy(tone(3.0)), 3.0)
    assert seconds_per_point == pytest.approx(0.25)
    assert len(values) == 12

    long_track = acoustics.measure_energy(silence(900.0))
    seconds_per_point, values = acoustics.energy_timeline(long_track, 900.0)
    assert len(values) <= acoustics.TIMELINE_MAX_POINTS
    assert seconds_per_point == pytest.approx(0.75)


def test_a_clip_shorter_than_one_analysis_window_does_not_crash():
    track = acoustics.measure_energy(tone(0.01))
    assert track.power.shape[0] == 1


# --- Pitch -------------------------------------------------------------------------------


def test_pitch_of_a_steady_tone_is_found():
    samples = np.concatenate([silence(0.5), tone(2.0, frequency=220.0), silence(0.5)])
    track = acoustics.measure_pitch(samples, [Segment(0, 0.5, 2.5)])
    summary = acoustics.summarize_pitch(track)

    assert summary is not None
    assert summary.median_hz == pytest.approx(220, abs=3)
    assert summary.range_semitones < 1
    assert track.times.min() >= 0.5
    assert track.times.max() <= 2.5


def test_pitch_is_unavailable_for_silence_and_for_too_little_voiced_sound():
    quiet = acoustics.measure_pitch(silence(2.0), [Segment(0, 0.0, 2.0)])
    assert acoustics.summarize_pitch(quiet) is None

    few = acoustics.PitchTrack(np.arange(10) * 0.016, np.full(10, 200.0))
    assert acoustics.summarize_pitch(few) is None


def test_pitch_range_and_variation_are_in_semitones_relative_to_the_speaker():
    # Half the frames at 100 Hz and half an octave higher: the same shape at any register.
    def summary(base: float):
        hz = np.array([base] * 50 + [base * 2] * 50)
        return acoustics.summarize_pitch(acoustics.PitchTrack(np.arange(100) * 0.016, hz))

    low, high = summary(100.0), summary(200.0)
    assert low.range_semitones == pytest.approx(12)
    assert high.range_semitones == pytest.approx(12)
    assert low.variation_semitones == pytest.approx(high.variation_semitones)
    assert high.high_hz - high.low_hz == pytest.approx(2 * (low.high_hz - low.low_hz))
    assert acoustics.semitones(440, 220) == pytest.approx(12)


# --- Emphasis candidates -----------------------------------------------------------------


def test_a_word_clearly_louder_than_the_rest_is_an_emphasis_candidate():
    levels = [0.1, 0.1, 0.1, 0.4, 0.1, 0.1]  # the fourth word is 12 dB louder
    samples = np.concatenate([tone(0.5, amplitude=level) for level in levels])
    words = [Word(f"w{i}", i * 0.5 + 0.05, i * 0.5 + 0.45, 0.9) for i in range(6)]
    energy = acoustics.measure_energy(samples)
    no_pitch = acoustics.PitchTrack(np.array([]), np.array([]))

    candidates = acoustics.find_emphasis_candidates(words, energy, no_pitch, None)

    assert [candidate.word.text for candidate in candidates] == ["w3"]
    assert candidates[0].reasons == ("louder",)
    assert candidates[0].energy_delta_db == pytest.approx(12, abs=0.5)
    assert candidates[0].pitch_delta_semitones is None


def test_a_word_clearly_higher_than_the_speakers_median_is_an_emphasis_candidate():
    samples = tone(3.0, amplitude=0.1)
    words = [Word(f"w{i}", i * 0.5 + 0.05, i * 0.5 + 0.45, 0.9) for i in range(6)]
    times = np.arange(0, 3.0, 0.016)
    hz = np.where((times >= 1.0) & (times < 1.5), 150.0, 120.0)  # third word ~3.9 semitones up
    pitch = acoustics.PitchTrack(times, hz)

    candidates = acoustics.find_emphasis_candidates(
        words, acoustics.measure_energy(samples), pitch, acoustics.summarize_pitch(pitch)
    )

    assert [(c.word.text, c.reasons) for c in candidates] == [("w2", ("higher_pitch",))]
    assert candidates[0].pitch_delta_semitones == pytest.approx(3.86, abs=0.1)


def test_no_emphasis_candidates_without_enough_words_for_a_baseline():
    samples = np.concatenate([tone(0.5, amplitude=0.1), tone(0.5, amplitude=0.5)])
    words = [Word("quiet", 0.05, 0.45, 0.9), Word("LOUD", 0.55, 0.95, 0.9)]
    no_pitch = acoustics.PitchTrack(np.array([]), np.array([]))
    assert acoustics.find_emphasis_candidates(words, acoustics.measure_energy(samples), no_pitch, None) == []  # fmt: skip


def test_even_delivery_produces_no_emphasis_candidates():
    words = [Word(f"w{i}", i * 0.5 + 0.05, i * 0.5 + 0.45, 0.9) for i in range(6)]
    no_pitch = acoustics.PitchTrack(np.array([]), np.array([]))
    assert acoustics.find_emphasis_candidates(words, acoustics.measure_energy(tone(3.0)), no_pitch, None) == []  # fmt: skip


# --- Hesitation sounds -------------------------------------------------------------------


def test_only_unambiguous_hesitation_sounds_are_counted():
    words = [
        Word("Um,", 0.0, 0.2),
        Word("I", 0.3, 0.4),
        Word("like", 0.5, 0.7),  # a real word here, so not counted
        Word("uh...", 0.8, 1.0),
        Word("मतलब", 1.1, 1.4),  # can be meaningful, so not counted
        Word("अं", 1.5, 1.7),
        Word("हम्म।", 1.8, 2.0),
        Word("umbrella", 2.1, 2.5),
    ]
    assert [word.text for word in find_hesitations(words)] == ["Um,", "uh...", "अं", "हम्म।"]
