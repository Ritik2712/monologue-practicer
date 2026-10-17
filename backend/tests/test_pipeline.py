"""The whole pipeline, with speech detection and transcription scripted so the expected
numbers can be worked out by hand."""

import json

import numpy as np
import pytest

from app.pipeline.errors import JobCancelled, PipelineError
from app.pipeline.runner import PipelineDeps, run_analysis
from app.pipeline.segmentation import Word
from app.pipeline.settings import DEFAULT_SETTINGS
from app.pipeline.transcribe import looks_garbled
from app.schemas import AnalysisBody
from tests.conftest import (
    FakeTranscriber,
    fake_vad,
    make_words,
    no_pitch,
    no_resonance,
    steady_pitch,
    steady_resonance,
    wav_bytes,
)


def run(tmp_path, *, regions, words, seconds=10.0, language="auto", transcriber=None, **options):
    # The test recording is a tone wherever "speech" is scripted and silent everywhere else.
    path = tmp_path / "take.wav"
    path.write_bytes(
        wav_bytes(seconds, sounding=options.pop("sounding", regions), **options.pop("wav", {}))
    )
    transcriber = transcriber or FakeTranscriber(words)
    stages: list[str] = []
    body = run_analysis(
        path,
        profile=options.pop("profile", "custom"),
        language=language,
        settings=DEFAULT_SETTINGS,
        max_seconds=options.pop("max_seconds", 600),
        deps=PipelineDeps(
            transcriber=transcriber,
            detect_speech=fake_vad(regions),
            measure_pitch=options.pop("pitch", steady_pitch),
            measure_resonance=options.pop("resonance", no_resonance),
        ),
        on_stage=stages.append,
        **options,
    )
    return body, stages, transcriber


def metric(body: AnalysisBody, name: str):
    return getattr(body.metrics, name)


def test_a_normal_recording_produces_the_expected_numbers(tmp_path):
    # Speech at 1-5 s (12 words) and 6.5-8.5 s (4 words), in a 10-second clip.
    body, stages, _ = run(
        tmp_path,
        regions=[(1.0, 5.0), (6.5, 8.5)],
        words=make_words(1.0, 5.0, 12) + make_words(6.5, 8.5, 4),
        profile="thomas_shelby",
    )

    assert stages == ["preparing_audio", "detecting_speech", "transcribing", "measuring_audio"]
    assert body.profile == "thomas_shelby"
    assert body.duration_seconds == pytest.approx(10.0, abs=0.01)

    first, second = body.segments
    assert (first.id, first.start_seconds, first.end_seconds) == ("seg-1", 1.0, 5.0)
    assert first.word_count == 12
    assert first.segment_wpm == 180.0  # 12 words in 4.0 s
    assert first.quality == "measured"
    assert first.reliable
    assert second.segment_wpm == 120.0  # 4 words in 2.0 s
    assert second.transcript == "word0 word1 word2 word3"

    (pause,) = body.pauses
    assert (pause.start_seconds, pause.end_seconds, pause.duration_seconds) == (5.0, 6.5, 1.5)
    assert pause.significance == "medium"
    assert (pause.after_segment_id, pause.before_segment_id) == ("seg-1", "seg-2")
    assert not pause.starts_new_section

    assert metric(body, "total_word_count").value == 16
    assert metric(body, "speech_active_seconds").value == 6.0
    assert metric(body, "speech_active_wpm").value == 160.0  # 16 words / 6 s
    assert metric(body, "whole_clip_wpm").value == 96.0  # 16 words / 10 s
    assert metric(body, "pause_count").value == 1
    assert metric(body, "longest_pause_seconds").value == 1.5
    assert metric(body, "pause_ratio").value == 0.15
    assert metric(body, "leading_silence_seconds").value == 1.0
    assert metric(body, "trailing_silence_seconds").value == 1.5
    assert body.warnings == []
    assert body.language.code == "en"
    assert body.language.source == "detected"


def test_every_word_is_listed_with_the_segment_it_belongs_to(tmp_path):
    body, _, _ = run(
        tmp_path,
        regions=[(1.0, 5.0), (6.5, 8.5)],
        words=make_words(1.0, 5.0, 3) + make_words(6.5, 8.5, 2),
    )
    assert [word.segment_id for word in body.words] == ["seg-1"] * 3 + ["seg-2"] * 2
    assert body.transcript == "word0 word1 word2 word0 word1"


def test_the_result_records_which_settings_and_tools_produced_it(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8))
    assert body.settings == DEFAULT_SETTINGS.to_dict()
    assert body.settings["version"] == 3
    assert body.settings["segment_break_ms"] == 1000
    # How sure the pitch tracker must be that a moment is voiced: lowered once, on evidence.
    assert body.settings["pitch_voiced_probability"] == 0.3
    assert body.settings["min_pause_ms"] == 500
    assert body.settings["long_silence_ms"] == 5000
    assert body.pipeline.speech_model == "fake-model"
    assert body.pipeline.voice_activity_detector == "silero-vad"


def test_the_json_uses_camel_case_and_never_reports_a_missing_number_as_zero(tmp_path):
    body, _, _ = run(tmp_path, regions=[], words=[])
    data = json.loads(body.model_dump_json(by_alias=True))

    assert "durationSeconds" in data
    assert "energyTimeline" in data
    assert data["metrics"]["speechActiveWpm"] == {
        "value": None,
        "unit": "words/minute",
        "quality": "unavailable",
        "note": "No speech was detected.",
    }
    AnalysisBody.model_validate(data)  # what is sent out can be read back in


def test_silence_is_never_sent_to_the_speech_recogniser(tmp_path):
    body, stages, transcriber = run(tmp_path, regions=[], words=make_words(0.0, 1.0, 5))

    assert transcriber.calls == 0
    assert "transcribing" not in stages
    assert [warning.code for warning in body.warnings] == ["no_speech"]
    assert body.segments == []
    assert body.pauses == []
    assert body.words == []
    assert body.transcript is None
    assert body.language.code == "unknown"
    assert body.pipeline.speech_model is None
    for name in ("speech_active_wpm", "whole_clip_wpm", "pause_count", "pause_ratio",
                 "average_pause_seconds", "leading_silence_seconds", "pitch_median_hz"):  # fmt: skip
        assert metric(body, name).value is None, name
        assert metric(body, name).quality == "unavailable", name


def test_speech_with_no_recognised_words_keeps_timing_but_drops_word_numbers(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0), (6.0, 9.0)], words=[])

    assert "no_words" in [warning.code for warning in body.warnings]
    assert body.transcript is None
    assert [segment.segment_wpm for segment in body.segments] == [None, None]
    assert [segment.word_count for segment in body.segments] == [None, None]
    assert metric(body, "speech_active_wpm").quality == "unavailable"
    assert metric(body, "filler_word_count").quality == "unavailable"
    # What comes from the sound alone is still measured.
    assert metric(body, "pause_count").value == 1
    assert metric(body, "speech_active_seconds").value == 7.0


def test_breath_detection_is_reported_as_unavailable_not_guessed(tmp_path):
    body, _, _ = run(
        tmp_path,
        regions=[(1.0, 3.0), (5.0, 8.0)],
        words=make_words(1.0, 3.0, 5) + make_words(5.0, 8.0, 6),
    )
    breath = metric(body, "breath_count")
    assert breath.value is None
    assert breath.quality == "unavailable"
    assert "not evidence of a breath" in breath.note


def test_loudness_is_labelled_as_relative(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8))
    assert body.energy_timeline.unit == "dBFS (relative)"
    assert len(body.energy_timeline.values) == 40
    assert "not calibrated" in metric(body, "energy_variation").note
    assert body.segments[0].mean_energy_db == pytest.approx(-13.5, abs=0.5)


def test_hinglish_is_best_effort_and_its_word_numbers_are_estimates(tmp_path):
    body, _, _ = run(
        tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 12), language="hinglish"
    )
    assert body.language.code == "hinglish"
    assert body.language.source == "declared"
    assert "hinglish_best_effort" in [warning.code for warning in body.warnings]
    assert metric(body, "speech_active_wpm").quality == "estimated"
    assert body.segments[0].quality == "estimated"
    # Pauses come from the sound, not the words, so they stay measured.
    assert metric(body, "pause_count").quality == "measured"


def test_unsure_transcription_is_flagged(tmp_path):
    body, _, _ = run(
        tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 12, probability=0.2)
    )
    assert "uncertain_transcription" in [warning.code for warning in body.warnings]
    assert metric(body, "speech_active_wpm").quality == "estimated"
    assert metric(body, "speech_active_wpm").value == 180.0


def test_word_times_that_disagree_with_the_detected_speech_are_flagged(tmp_path):
    # Speech was detected at 1-5 s but half the words are timed at 6-8 s, in silence.
    words = make_words(1.0, 5.0, 6) + make_words(6.0, 8.0, 6)
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=words)
    assert "word_timing_uncertain" in [warning.code for warning in body.warnings]
    assert body.segments[0].quality == "estimated"


def test_an_uncertain_language_guess_is_flagged(tmp_path):
    transcriber = FakeTranscriber(make_words(1.0, 5.0, 8), language="ur")
    transcriber.language_probability = 0.41
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=[], transcriber=transcriber)
    assert body.language.code == "ur"
    assert body.language.confidence == 0.41
    assert "language_uncertain" in [warning.code for warning in body.warnings]


def test_hesitation_sounds_are_counted_as_an_estimate(tmp_path):
    words = [Word("Um,", 1.0, 1.3, 0.9), *make_words(1.5, 4.5, 8), Word("uh", 4.6, 4.9, 0.9)]
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=words)
    fillers = metric(body, "filler_word_count")
    assert fillers.value == 2
    assert fillers.quality == "estimated"
    assert [item.text for item in body.hesitations] == ["Um,", "uh"]


def test_a_very_short_recording_is_flagged(tmp_path):
    body, _, _ = run(tmp_path, regions=[(0.2, 1.2)], words=make_words(0.2, 1.2, 2), seconds=1.5)
    assert "very_short" in [warning.code for warning in body.warnings]
    assert not body.segments[0].reliable


def test_a_recording_over_the_length_limit_is_refused(tmp_path):
    with pytest.raises(PipelineError) as raised:
        run(tmp_path, regions=[], words=[], seconds=5.0, max_seconds=2.0)
    assert raised.value.code == "audio_too_long"


def test_cancellation_stops_the_run_at_the_next_safe_point(tmp_path):
    reached: list[str] = []

    def check() -> None:
        if "transcribing" in reached:
            raise JobCancelled

    path = tmp_path / "take.wav"
    path.write_bytes(wav_bytes(10.0))
    with pytest.raises(JobCancelled):
        run_analysis(
            path,
            profile="custom",
            language="auto",
            settings=DEFAULT_SETTINGS,
            max_seconds=600,
            deps=PipelineDeps(
                transcriber=FakeTranscriber(make_words(1.0, 5.0, 8)),
                detect_speech=fake_vad([(1.0, 5.0)]),
                measure_pitch=no_pitch,
                measure_resonance=no_resonance,
            ),
            on_stage=reached.append,
            check=check,
        )
    assert reached == ["preparing_audio", "detecting_speech", "transcribing"]


def test_pitch_is_reported_relative_to_the_speakers_own_median(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8))
    assert metric(body, "pitch_median_hz").value == 200.0
    assert metric(body, "pitch_range_semitones").value == 0.0
    assert body.segments[0].median_pitch_hz == 200.0
    assert body.segments[0].pitch_delta_semitones == 0.0


def test_too_little_voiced_sound_makes_pitch_unavailable_with_a_warning(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8), pitch=no_pitch)
    assert "pitch_unavailable" in [warning.code for warning in body.warnings]
    assert metric(body, "pitch_median_hz").quality == "unavailable"
    assert body.segments[0].median_pitch_hz is None


def test_a_loud_background_is_flagged_because_pauses_become_harder_to_detect(tmp_path):
    # The tone carries on at the same level through the "pause".
    body, _, _ = run(
        tmp_path,
        regions=[(1.0, 4.0), (6.0, 9.0)],
        words=make_words(1.0, 4.0, 6) + make_words(6.0, 9.0, 6),
        sounding=None,
    )
    assert "noisy" in [warning.code for warning in body.warnings]
    assert metric(body, "signal_to_noise").value == pytest.approx(0, abs=0.5)
    assert metric(body, "signal_to_noise").quality == "estimated"


def test_clipping_is_measured_and_flagged(tmp_path):
    body, _, _ = run(
        tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8), wav={"amplitude": 1.0}
    )
    assert "clipping" in [warning.code for warning in body.warnings]
    assert metric(body, "clipping_ratio").value > 0.001


def test_segments_are_compared_with_the_speakers_own_typical_pace(tmp_path):
    # Three 4-second phrases at 120, 150 and 300 WPM.
    body, _, _ = run(
        tmp_path,
        seconds=16.0,
        regions=[(0.5, 4.5), (5.5, 9.5), (10.5, 14.5)],
        words=make_words(0.5, 4.5, 8) + make_words(5.5, 9.5, 10) + make_words(10.5, 14.5, 20),
    )
    assert metric(body, "typical_segment_wpm").value == 150.0
    assert [segment.pace_vs_typical for segment in body.segments] == [
        "typical",
        "typical",
        "faster",
    ]
    assert body.settings["pace_deviation_ratio"] == 0.25


def test_typical_pace_is_unavailable_for_a_recording_with_too_few_phrases(tmp_path):
    body, _, _ = run(tmp_path, regions=[(1.0, 5.0)], words=make_words(1.0, 5.0, 8))
    assert metric(body, "typical_segment_wpm").quality == "unavailable"
    assert body.segments[0].pace_vs_typical is None


def test_a_recogniser_stuck_repeating_itself_is_recognised():
    assert looks_garbled("हु" + "ँ" * 80)
    assert looks_garbled("aaaaaaaaaaaa")
    assert looks_garbled("x" * 41)
    # Real words, including long ones and ordinary doubled letters, are not flagged.
    for word in ["danger,", "खतरा", "disestablishmentarianism", "aaah", "soooo", "नहीं।"]:
        assert not looks_garbled(word), word


def test_garbled_transcription_is_flagged_and_downgrades_word_numbers(tmp_path):
    # What actually happened on one Hindi MP3: the last "word" swallowed five seconds.
    words = [*make_words(1.0, 3.0, 7), Word("हु" + "ँ" * 80, 3.0, 8.0, 0.4)]
    body, _, _ = run(tmp_path, regions=[(1.0, 8.0)], words=words)

    assert "garbled_transcription" in [warning.code for warning in body.warnings]
    assert metric(body, "speech_active_wpm").quality == "estimated"
    assert body.segments[0].quality == "estimated"
    # Pauses and timing come from the sound and are unaffected.
    assert metric(body, "speech_active_seconds").quality == "measured"


# --- Where the voice sits ----------------------------------------------------------------


def voiced(tmp_path, **options):
    """Two phrases, 1-5 s and 6.5-8.5 s, at a steady 200 Hz with formants 1000 Hz apart."""
    options.setdefault("resonance", steady_resonance(1000.0))
    body, _, _ = run(
        tmp_path,
        regions=[(1.0, 5.0), (6.5, 8.5)],
        words=make_words(1.0, 5.0, 12) + make_words(6.5, 8.5, 4),
        **options,
    )
    return body


def test_pitch_and_resonance_are_each_placed_in_a_range_with_a_position(tmp_path):
    voice = voiced(tmp_path).voice_range

    # 200 Hz is (200 - 175) / (255 - 175) = 31% of the way into the higher range.
    assert voice.pitch.model_dump() == {
        "value_hz": 200.0,
        "band": "higher",
        "percent": 31,
        "quality": "measured",
    }
    # 1000 Hz of formant spacing is (1040 - 1000) / (1040 - 940) = 40% into the lower range.
    assert voice.resonance.model_dump() == {
        "value_hz": 1000.0,
        "band": "lower",
        "percent": 40,
        "quality": "measured",
    }
    assert voice.formants_hz == [500, 1500, 2500]
    # A higher pitch with a deeper resonance gives a listener two different cues.
    assert voice.marker == "mixed"
    assert voice.resonance_note is None


def test_every_phrase_is_placed_too_and_the_recording_counts_them(tmp_path):
    body = voiced(tmp_path)

    first, second = body.segments
    assert (first.voice.pitch.band, first.voice.resonance.band, first.voice.marker) == (
        "higher",
        "lower",
        "mixed",
    )
    assert first.voice.resonance.quality == second.voice.resonance.quality == "measured"
    assert body.voice_range.phrases.model_dump() == {
        "lower": 0,
        "neutral": 0,
        "higher": 0,
        "mixed": 2,
        "unmeasured": 0,
    }


def test_the_ranges_used_are_stored_with_the_result(tmp_path):
    bands = voiced(tmp_path).voice_range.bands
    assert bands["version"] == 1
    assert (bands["pitch_neutral_from_hz"], bands["pitch_neutral_to_hz"]) == (145.0, 175.0)
    assert (bands["resonance_neutral_from_hz"], bands["resonance_neutral_to_hz"]) == (
        1040.0,
        1100.0,
    )


def test_the_goal_is_recorded_and_changes_no_measurement(tmp_path):
    plain = voiced(tmp_path)
    aimed = voiced(tmp_path, voice_goal="lower")

    assert (plain.voice_range.goal, aimed.voice_range.goal) == ("none", "lower")
    assert aimed.voice_range.model_copy(update={"goal": "none"}) == plain.voice_range
    assert aimed.segments == plain.segments
    assert aimed.metrics == plain.metrics


def test_a_voice_in_one_range_for_both_gets_that_marker(tmp_path):
    body = voiced(tmp_path, resonance=steady_resonance(1200.0))
    assert body.voice_range.marker == "higher"
    assert body.voice_range.resonance.percent == 50  # (1200 - 1100) / (1300 - 1100)
    assert body.voice_range.phrases.higher == 2


def test_resonance_that_could_not_be_measured_is_unavailable_and_pitch_still_decides(tmp_path):
    body = voiced(tmp_path, resonance=no_resonance)

    voice = body.voice_range
    assert voice.resonance is None and voice.formants_hz is None
    assert voice.resonance_note == "There was too little clear, voiced sound to measure resonance."
    assert (voice.pitch.band, voice.marker) == ("higher", "higher")
    assert body.segments[0].voice.resonance is None
    assert body.segments[0].voice.marker == "higher"


def test_a_phrase_with_neither_measured_has_no_voice_and_is_counted_as_unmeasured(tmp_path):
    body = voiced(tmp_path, pitch=no_pitch, resonance=no_resonance)

    assert body.segments[0].voice is None
    assert body.voice_range.marker is None
    assert body.voice_range.phrases.unmeasured == 2


def test_a_recording_with_no_speech_has_no_voice_range(tmp_path):
    body, _, _ = run(tmp_path, regions=[], words=[])
    assert body.voice_range is None


def test_a_loud_background_makes_resonance_an_estimate_and_a_very_loud_one_withholds_it():
    from app.pipeline.resonance import ResonanceTrack
    from app.pipeline.runner import WARNINGS, _VoiceReader
    from app.pipeline.segmentation import Segment, Stretch
    from app.pipeline.voice_range import DEFAULT_VOICE_RANGES

    times = np.arange(0.0, 4.0, 0.01)
    track = ResonanceTrack(times, np.tile([500.0, 1500.0, 2500.0], (times.shape[0], 1)))
    phrase = Segment(index=0, stretches=[Stretch(0, 0.0, 4.0)])

    def read(snr_db):
        reader = _VoiceReader(track, snr_db, DEFAULT_VOICE_RANGES)
        return reader.of_segment(phrase, 120.0), reader.of_recording(120.0, [], "none")

    # A phrase with under a second and a half of usable sound is placed, as an estimate.
    short = _VoiceReader(track, 40.0, DEFAULT_VOICE_RANGES).of_segment(
        Segment(index=1, stretches=[Stretch(1, 1.0, 2.0)]), 120.0
    )
    assert (short.resonance.band, short.resonance.quality) == ("lower", "estimated")

    # Quiet background, or none to judge by: measured.
    for snr_db in (40.0, None):
        segment, recording = read(snr_db)
        assert segment.resonance.quality == recording.resonance.quality == "measured"
        assert recording.resonance_note is None

    # Under 30 dB the figure reads brighter than the voice is: an estimate, and it says why.
    segment, recording = read(25.0)
    assert segment.resonance.quality == recording.resonance.quality == "estimated"
    assert recording.resonance_note == WARNINGS["resonance_noisy"]
    # Pitch does not suffer the same way.
    assert segment.pitch.quality == "measured"

    # Under 20 dB it can land in the wrong range altogether: not given at all.
    segment, recording = read(15.0)
    assert segment.resonance is None and recording.resonance is None
    assert "too loud" in recording.resonance_note
    assert segment.marker == "lower"  # from the pitch alone
