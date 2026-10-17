"""Runs the stages of an analysis in order and assembles the result.

    file -> decode -> detect speech -> transcribe -> measure -> AnalysisBody

The slow parts (decoding, speech detection, transcription, pitch tracking) are passed in as
`PipelineDeps`, so tests can replace them and exercise everything else quickly.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.pipeline import acoustics, resonance, voice_range
from app.pipeline.audio import clipping_ratio, decode_audio
from app.pipeline.fillers import find_hesitations
from app.pipeline.metrics import (
    Metric,
    Quality,
    pace_vs_typical,
    segment_pace,
    summarize_pace,
    summarize_pauses,
    typical_wpm,
    unavailable,
)
from app.pipeline.segmentation import (
    Segment,
    SpeechRegion,
    Stretch,
    Word,
    assign_words,
    build_segments,
    find_short_silences,
    stretches_of,
)
from app.pipeline.settings import SAMPLE_RATE, AnalysisSettings
from app.pipeline.transcribe import LanguageHint, Transcriber, Transcription, looks_garbled
from app.pipeline.vad import detect_speech
from app.schemas import (
    AnalysisBody,
    AnalysisWarning,
    EmphasisCandidate,
    EnergyTimeline,
    Hesitation,
    LanguageInfo,
    Metrics,
    MetricValue,
    PauseEvent,
    PipelineInfo,
    Profile,
    SegmentVoice,
    ShortSilence,
    SpeechSegment,
    SpeechStretch,
    VoiceGoal,
    VoicePhraseCounts,
    VoicePlacement,
    VoiceRange,
    WordTiming,
)

# Below this share of clipped samples, clipping is not worth mentioning.
CLIPPING_WARNING_RATIO = 0.001
NOISY_SNR_DB = 10.0
UNCERTAIN_LANGUAGE = 0.6
# If more than this share of words had to be moved into a segment, timings are doubtful.
MOVED_WORDS_WARNING_RATIO = 0.1
VERY_SHORT_SECONDS = 3.0

WARNINGS = {
    "no_speech": "No speech was detected in this recording.",
    "no_words": "Speech was detected, but no words were recognised.",
    "very_short": "The recording is very short, so most figures are unreliable.",
    "hinglish_best_effort": (
        "Mixed Hindi-English speech is transcribed as Hindi on a best-effort basis, so word "
        "counts and WPM are estimates."
    ),
    "uncertain_transcription": (
        "The speech recogniser was unsure about many words, so word counts and WPM are estimates."
    ),
    "garbled_transcription": (
        "Part of the transcript looks garbled: the speech recogniser got stuck repeating "
        "itself. Word counts and WPM are estimates and may be well off."
    ),
    "word_timing_uncertain": (
        "Many word timings did not line up with the detected speech, so per-segment word "
        "counts are estimates."
    ),
    "language_uncertain": "The spoken language could not be identified with confidence.",
    "clipping": (
        "Parts of the recording are clipped (too loud for the microphone), which makes "
        "loudness and pitch figures less reliable."
    ),
    "noisy": (
        "The background is loud compared with the voice, so pause detection may be less accurate."
    ),
    "pitch_unavailable": "There was too little clearly voiced sound to measure pitch.",
    "resonance_noisy": (
        "The background is loud enough to make the voice's resonance read brighter than it "
        "is, so the resonance figures are estimates."
    ),
    # Added by `app.transcript_correction`, never by an analysis of the audio.
    "transcript_corrected": (
        "You corrected the transcript, and this revision uses your words. Word counts and WPM "
        "were worked out again from them. Where a word changed, its timing is an estimate, "
        "and emphasis candidates are kept only for words that stayed the same."
    ),
}
# The warnings that speak about how far the recognised words can be trusted.
WORD_WARNINGS = (
    "no_words",
    "hinglish_best_effort",
    "uncertain_transcription",
    "garbled_transcription",
    "word_timing_uncertain",
)


@dataclass
class PipelineDeps:
    transcriber: Transcriber
    decode: Callable[..., np.ndarray] = decode_audio
    detect_speech: Callable[[np.ndarray, AnalysisSettings], list[SpeechRegion]] = detect_speech
    measure_pitch: Callable[[np.ndarray, list[Stretch]], acoustics.PitchTrack] = (
        acoustics.measure_pitch
    )
    measure_resonance: Callable[[np.ndarray, list[Stretch]], resonance.ResonanceTrack] = (
        resonance.measure_resonance
    )


def run_analysis(
    audio_path: Path,
    *,
    profile: Profile,
    language: LanguageHint,
    settings: AnalysisSettings,
    max_seconds: float | None,
    deps: PipelineDeps,
    voice_goal: VoiceGoal = "none",
    voice_ranges: voice_range.VoiceRangeSettings = voice_range.DEFAULT_VOICE_RANGES,
    on_stage: Callable[[str], None] = lambda stage: None,
    check: Callable[[], None] = lambda: None,
    on_audio: Callable[[np.ndarray], None] = lambda samples: None,
) -> AnalysisBody:
    """`check` is called at every safe stopping point and raises to abort the run.

    `on_audio` is handed the decoded samples once, for uses outside the measurements (the
    waveform picture). Nothing it does can reach the result returned here.
    """
    warnings: list[str] = []

    on_stage("preparing_audio")
    samples = deps.decode(audio_path, max_seconds=max_seconds)
    on_audio(samples)
    duration = samples.shape[0] / SAMPLE_RATE
    clipped = clipping_ratio(samples)
    if clipped > CLIPPING_WARNING_RATIO:
        warnings.append("clipping")
    if duration < VERY_SHORT_SECONDS:
        warnings.append("very_short")
    check()

    on_stage("detecting_speech")
    regions = deps.detect_speech(samples, settings)
    segments, pauses = build_segments(regions, settings)
    # Sound is measured where there is speech: in the stretches, not in the pauses a
    # segment may hold between them.
    stretches = stretches_of(segments)
    short_silences = find_short_silences(regions, settings)
    check()

    transcription: Transcription | None = None
    moved_words = 0
    if segments:
        # Silence is never sent to the recogniser: with nothing to hear, it tends to invent words.
        on_stage("transcribing")
        transcription = deps.transcriber.transcribe(samples, language, check)
        moved_words = assign_words(segments, transcription.words)
        check()
    else:
        warnings.append("no_speech")

    on_stage("measuring_audio")
    words = transcription.words if transcription else []
    has_transcript = bool(words)
    if segments and not has_transcript:
        warnings.append("no_words")

    word_quality = word_quality_of(words, moved_words, language, settings, warnings)
    paces = [segment_pace(segment, settings, has_transcript=has_transcript) for segment in segments]
    pace = summarize_pace(
        segments, paces, duration, has_transcript=has_transcript, word_quality=word_quality
    )
    typical = typical_wpm(paces, settings)
    pause_summary = summarize_pauses(pauses, duration, speech_detected=bool(segments))

    energy = acoustics.measure_energy(samples)
    energy_summary = acoustics.summarize_energy(energy, stretches)
    if energy_summary.snr_db is not None and energy_summary.snr_db < NOISY_SNR_DB:
        warnings.append("noisy")
    check()

    pitch = deps.measure_pitch(samples, stretches)
    pitch_summary = acoustics.summarize_pitch(pitch)
    if segments and pitch_summary is None:
        warnings.append("pitch_unavailable")
    check()

    formants = deps.measure_resonance(samples, stretches)
    voice = _VoiceReader(formants, energy_summary.snr_db, voice_ranges)
    if voice.noisy and formants.times.size:
        warnings.append("resonance_noisy")
    check()

    segment_ids = {id(segment): f"seg-{segment.index + 1}" for segment in segments}
    word_segment = {
        id(word): segment_ids[id(segment)] for segment in segments for word in segment.words
    }
    word_stretch = {id(word): stretch.index for stretch in stretches for word in stretch.words}
    segment_levels = [energy.mean_db_within(segment.stretches) for segment in segments]
    known_levels = [level for level in segment_levels if level is not None]
    typical_level = float(np.median(known_levels)) if len(known_levels) >= 2 else None

    segments_out = []
    for segment, pace_info, level in zip(segments, paces, segment_levels, strict=True):
        segment_pitch = pitch.median_hz(segment.start, segment.end, min_frames=5)
        segment_voice = voice.of_segment(segment, segment_pitch)
        segments_out.append(
            SpeechSegment(
                id=segment_ids[id(segment)],
                index=segment.index,
                section_index=segment.section_index,
                start_seconds=round_out(segment.start, 3),
                end_seconds=round_out(segment.end, 3),
                speech_active_seconds=round_out(segment.speaking_seconds, 3),
                pause_count=segment.pause_count,
                pause_seconds=round_out(segment.pause_seconds, 3),
                transcript=" ".join(word.text for word in segment.words)
                if has_transcript
                else None,
                word_count=pace_info.word_count if has_transcript else None,
                segment_wpm=round_out(pace_info.speaking_wpm, 1),
                delivery_wpm=round_out(pace_info.wpm, 1),
                pace_vs_typical=pace_vs_typical(pace_info, typical, settings),
                quality=weaker(pace_info.quality, word_quality),
                reliable=pace_info.reliable,
                flags=list(pace_info.flags),
                confidence=round_out(pace_info.confidence, 3),
                mean_energy_db=round_out(level, 1),
                energy_delta_db=(
                    round_out(level - typical_level, 1)
                    if level is not None and typical_level is not None
                    else None
                ),
                median_pitch_hz=round_out(segment_pitch, 1),
                pitch_delta_semitones=(
                    round_out(acoustics.semitones(segment_pitch, pitch_summary.median_hz), 1)
                    if segment_pitch is not None and pitch_summary is not None
                    else None
                ),
                voice=segment_voice,
            )
        )

    pauses_out = [
        PauseEvent(
            id=f"pause-{pause.index + 1}",
            index=pause.index,
            start_seconds=round_out(pause.start, 3),
            end_seconds=round_out(pause.end, 3),
            duration_seconds=round_out(pause.duration, 3),
            significance=pause.significance,
            after_segment_id=f"seg-{pause.after_segment + 1}",
            before_segment_id=f"seg-{pause.before_segment + 1}",
            inside_segment=pause.inside_segment,
            starts_new_section=pause.significance == "long",
        )
        for pause in pauses
    ]

    emphasis = acoustics.find_emphasis_candidates(words, energy, pitch, pitch_summary)
    hesitations = find_hesitations(words)
    seconds_per_point, timeline = acoustics.energy_timeline(energy, duration)

    return AnalysisBody(
        profile=profile,
        language=_language_info(language, transcription, warnings),
        duration_seconds=round_out(duration, 3),
        transcript=transcription.text if has_transcript and transcription else None,
        segments=segments_out,
        stretches=[
            SpeechStretch(
                index=stretch.index,
                start_seconds=round_out(stretch.start, 3),
                end_seconds=round_out(stretch.end, 3),
                segment_id=segment_ids[id(segment)],
            )
            for segment in segments
            for stretch in segment.stretches
        ],
        pauses=pauses_out,
        short_silences=[
            ShortSilence(
                start_seconds=round_out(silence.start, 3),
                end_seconds=round_out(silence.end, 3),
                duration_seconds=round_out(silence.duration, 3),
                segment_id=next(
                    (
                        segment_ids[id(segment)]
                        for segment in segments
                        if segment.start <= silence.start and silence.end <= segment.end
                    ),
                    None,
                ),
            )
            for silence in short_silences
        ],
        words=[
            WordTiming(
                text=word.text,
                start_seconds=round_out(word.start, 3),
                end_seconds=round_out(word.end, 3),
                confidence=round_out(word.probability, 3),
                segment_id=word_segment.get(id(word)),
                stretch_index=word_stretch.get(id(word)),
            )
            for word in words
        ],
        metrics=_metrics(
            segments,
            pace,
            pause_summary,
            energy_summary,
            pitch_summary,
            duration,
            clipped,
            hesitation_count=len(hesitations),
            has_transcript=has_transcript,
            word_quality=word_quality,
            typical=typical,
            settings=settings,
        ),
        energy_timeline=EnergyTimeline(
            seconds_per_point=seconds_per_point, unit="dBFS (relative)", values=timeline
        ),
        emphasis_candidates=[
            EmphasisCandidate(
                text=candidate.word.text,
                start_seconds=round_out(candidate.word.start, 3),
                end_seconds=round_out(candidate.word.end, 3),
                segment_id=word_segment.get(id(candidate.word)),
                reasons=list(candidate.reasons),
                energy_delta_db=round_out(candidate.energy_delta_db, 1),
                pitch_delta_semitones=round_out(candidate.pitch_delta_semitones, 1),
            )
            for candidate in emphasis
        ],
        hesitations=[
            Hesitation(text=word.text, start_seconds=round_out(word.start, 3))
            for word in hesitations
        ],
        settings=settings.to_dict(),
        pipeline=PipelineInfo(
            speech_model=deps.transcriber.name if transcription else None,
            voice_activity_detector="silero-vad",
            pitch_tracker="librosa-pyin",
        ),
        warnings=[AnalysisWarning(code=code, message=WARNINGS[code]) for code in warnings],
        voice_range=(
            voice.of_recording(
                pitch_summary.median_hz if pitch_summary else None, segments_out, voice_goal
            )
            if segments
            else None
        ),
    )


class _VoiceReader:
    """Places pitch and resonance in this app's ranges, for a phrase and for a recording."""

    def __init__(
        self,
        formants: resonance.ResonanceTrack,
        snr_db: float | None,
        ranges: voice_range.VoiceRangeSettings,
    ) -> None:
        self.formants = formants
        self.ranges = ranges
        # With a loud background the resonance reads brighter than the voice is.
        self.unusable = snr_db is not None and snr_db < resonance.UNAVAILABLE_BELOW_SNR_DB
        self.noisy = (
            snr_db is not None and snr_db < resonance.ESTIMATE_BELOW_SNR_DB and not self.unusable
        )

    def _placed(self, value: float | None, scale, quality: Quality) -> VoicePlacement | None:
        if value is None:
            return None
        placement = voice_range.place(value, scale, self.ranges)
        return VoicePlacement(
            value_hz=round(value, 1),
            band=placement.band,
            percent=placement.percent,
            quality=quality,
        )

    def _resonance(self, start: float, end: float, min_frames: int, enough: int):
        if self.unusable:
            return None
        spacing = self.formants.spacing_hz(start, end, min_frames=min_frames)
        few = self.formants.frame_count(start, end) < enough
        return self._placed(spacing, "resonance", "estimated" if few or self.noisy else "measured")

    def of_segment(self, segment: Segment, pitch_hz: float | None) -> SegmentVoice | None:
        pitch = self._placed(pitch_hz, "pitch", "measured")
        placed = self._resonance(
            segment.start,
            segment.end,
            resonance.MIN_SEGMENT_FRAMES,
            resonance.RELIABLE_SEGMENT_FRAMES,
        )
        if pitch is None and placed is None:
            return None
        return SegmentVoice(
            pitch=pitch,
            resonance=placed,
            marker=voice_range.overall_marker(
                pitch.band if pitch else None, placed.band if placed else None
            ),
        )

    def of_recording(
        self, pitch_hz: float | None, segments: list[SpeechSegment], goal: VoiceGoal
    ) -> VoiceRange:
        pitch = self._placed(pitch_hz, "pitch", "measured")
        everything = (0.0, float("inf"))
        placed = self._resonance(
            *everything, resonance.MIN_RECORDING_FRAMES, resonance.MIN_RECORDING_FRAMES
        )
        typical = (
            None
            if placed is None
            else self.formants.formants_hz(*everything, min_frames=resonance.MIN_RECORDING_FRAMES)
        )
        counts = VoicePhraseCounts()
        for segment in segments:
            marker = segment.voice.marker if segment.voice else None
            name = marker or "unmeasured"
            setattr(counts, name, getattr(counts, name) + 1)
        note = None
        if self.unusable:
            note = (
                "The background is too loud for resonance to be measured: it would read "
                "far brighter than the voice is."
            )
        elif placed is None:
            note = "There was too little clear, voiced sound to measure resonance."
        elif self.noisy:
            note = WARNINGS["resonance_noisy"]
        return VoiceRange(
            goal=goal,
            pitch=pitch,
            resonance=placed,
            marker=voice_range.overall_marker(
                pitch.band if pitch else None, placed.band if placed else None
            ),
            formants_hz=None if typical is None else [round(float(hz)) for hz in typical],
            phrases=counts,
            bands=self.ranges.to_dict(),
            resonance_note=note,
        )


def word_quality_of(
    words: list[Word],
    moved_words: int,
    language: LanguageHint,
    settings: AnalysisSettings,
    warnings: list[str],
) -> Quality:
    """How far numbers built on recognised words can be trusted. Adds the matching warnings."""
    if not words:
        return "unavailable"
    quality: Quality = "measured"
    if language == "hinglish":
        warnings.append("hinglish_best_effort")
        quality = "estimated"
    confidences = [word.probability for word in words if word.probability is not None]
    if confidences and sum(confidences) / len(confidences) < settings.low_confidence:
        warnings.append("uncertain_transcription")
        quality = "estimated"
    if any(looks_garbled(word.text) for word in words):
        warnings.append("garbled_transcription")
        quality = "estimated"
    if moved_words / len(words) > MOVED_WORDS_WARNING_RATIO:
        warnings.append("word_timing_uncertain")
        quality = "estimated"
    return quality


def _language_info(
    language: LanguageHint, transcription: Transcription | None, warnings: list[str]
) -> LanguageInfo:
    if language != "auto":
        return LanguageInfo(code=language, source="declared", confidence=None)
    if transcription is None or not transcription.language:
        return LanguageInfo(code="unknown", source="none", confidence=None)
    confidence = transcription.language_probability
    if confidence is not None and confidence < UNCERTAIN_LANGUAGE:
        warnings.append("language_uncertain")
    return LanguageInfo(
        code=transcription.language, source="detected", confidence=round_out(confidence, 3)
    )


def _metrics(
    segments: list[Segment],
    pace,
    pauses,
    energy: acoustics.EnergySummary,
    pitch: acoustics.PitchSummary | None,
    duration: float,
    clipped: float,
    *,
    hesitation_count: int,
    has_transcript: bool,
    word_quality: Quality,
    typical: float | None,
    settings: AnalysisSettings,
) -> Metrics:
    no_speech = "No speech was detected."

    def seconds(value: float | None, note: str | None = None) -> Metric:
        return (
            Metric(value, "seconds", "measured", note)
            if segments
            else unavailable("seconds", no_speech)
        )

    if pitch is None:
        no_pitch = "Too little clearly voiced sound to measure pitch."
        pitch_median = unavailable("Hz", no_pitch)
        pitch_range_hz = unavailable("Hz", no_pitch)
        pitch_range_st = unavailable("semitones", no_pitch)
        pitch_variation = unavailable("semitones", no_pitch)
    else:
        pitch_median = Metric(pitch.median_hz, "Hz", "measured", "Median pitch of voiced sound.")
        pitch_range_hz = Metric(
            pitch.high_hz - pitch.low_hz,
            "Hz",
            "measured",
            f"From {pitch.low_hz:.0f} Hz to {pitch.high_hz:.0f} Hz (5th to 95th percentile).",
        )
        pitch_range_st = Metric(
            pitch.range_semitones, "semitones", "measured", "5th to 95th percentile, in semitones."
        )
        pitch_variation = Metric(
            pitch.variation_semitones,
            "semitones",
            "measured",
            "Spread around the speaker's own median pitch.",
        )

    return Metrics(
        **word_metric_values(
            pace,
            typical,
            hesitation_count=hesitation_count,
            has_transcript=has_transcript,
            word_quality=word_quality,
            settings=settings,
        ),
        speech_active_seconds=_out(
            seconds(pace.speech_active_seconds, "Total time spent speaking: every pause left out."),
            3,
        ),
        pause_count=_out(pauses.count, 0),
        total_pause_seconds=_out(pauses.total_seconds, 3),
        average_pause_seconds=_out(pauses.average_seconds, 3),
        median_pause_seconds=_out(pauses.median_seconds, 3),
        longest_pause_seconds=_out(pauses.longest_seconds, 3),
        pause_ratio=_out(pauses.ratio, 4),
        leading_silence_seconds=_out(
            seconds(segments[0].start if segments else None, "Silence before the first word."), 3
        ),
        trailing_silence_seconds=_out(
            seconds(
                duration - segments[-1].end if segments else None, "Silence after the last word."
            ),
            3,
        ),
        energy_variation=_out(
            Metric(
                energy.variation_db,
                "dB",
                "measured",
                "Spread of loudness across quarter-second stretches of speech. Relative to "
                "this recording only; not calibrated loudness.",
            )
            if energy.variation_db is not None
            else unavailable("dB", "Too little speech to measure how loudness varies."),
            1,
        ),
        signal_to_noise=_out(
            Metric(
                energy.snr_db,
                "dB",
                "estimated",
                "How far the voice stands above the background between speech.",
            )
            if energy.snr_db is not None
            else unavailable("dB", "Needs both speech and at least half a second without it."),
            1,
        ),
        pitch_median_hz=_out(pitch_median, 1),
        pitch_range_hz=_out(pitch_range_hz, 1),
        pitch_range_semitones=_out(pitch_range_st, 1),
        pitch_variation_semitones=_out(pitch_variation, 2),
        breath_count=_out(
            unavailable(
                "count",
                "Breath detection is not available. A silence is not evidence of a breath, so "
                "none are reported.",
            ),
            0,
        ),
        clipping_ratio=_out(
            Metric(
                clipped, "ratio", "measured", "Share of samples at the recorder's maximum level."
            ),
            5,
        ),
    )


def word_metric_values(
    pace,
    typical: float | None,
    *,
    hesitation_count: int,
    has_transcript: bool,
    word_quality: Quality,
    settings: AnalysisSettings,
) -> dict[str, MetricValue]:
    """The metrics that are built on the recognised words, and on nothing else.

    Kept apart from the rest so that a corrected transcript can have exactly these worked
    out again, by the same code, while every acoustic measurement stays as it was.
    """
    if has_transcript:
        fillers = Metric(
            float(hesitation_count),
            "count",
            "estimated",
            "Hesitation sounds such as 'um' and 'uh'. Speech recognition often leaves these "
            "out, so the real number may be higher.",
        )
    else:
        fillers = unavailable("count", "No transcript is available.")

    return {
        "total_word_count": _out(
            Metric(float(pace.total_words), "words", word_quality)
            if has_transcript
            else unavailable("words", "No transcript is available."),
            0,
        ),
        "delivery_wpm": _out(pace.delivery_wpm, 1),
        "speech_active_wpm": _out(pace.speech_active_wpm, 1),
        "whole_clip_wpm": _out(pace.whole_clip_wpm, 1),
        "pace_variation": _out(pace.pace_variation, 1),
        "pace_min_wpm": _out(pace.pace_min_wpm, 1),
        "pace_max_wpm": _out(pace.pace_max_wpm, 1),
        "typical_segment_wpm": _out(
            Metric(
                typical,
                "words/minute",
                word_quality,
                "Median delivery pace of the segments long enough to measure reliably: your "
                "usual pace in this recording.",
            )
            if typical is not None
            else unavailable(
                "words/minute",
                f"Needs at least {settings.min_segments_for_typical_pace} segments long enough "
                "to measure reliably.",
            ),
            1,
        ),
        "filler_word_count": _out(fillers, 0),
    }


def _out(metric: Metric, digits: int) -> MetricValue:
    return MetricValue(
        value=round_out(metric.value, digits),
        unit=metric.unit,
        quality=metric.quality,
        note=metric.note,
    )


def round_out(value: float | None, digits: int) -> float | None:
    """Rounds for output, so results do not suggest more precision than the method has."""
    return None if value is None else round(float(value), digits)


def weaker(a: Quality, b: Quality) -> Quality:
    order = {"measured": 0, "estimated": 1, "unavailable": 2}
    return a if order[a] >= order[b] else b
