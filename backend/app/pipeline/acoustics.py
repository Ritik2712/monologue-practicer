"""Loudness and pitch measurements taken directly from the sound wave.

Loudness here is RMS energy in decibels relative to digital full scale (dBFS). It depends on
the microphone, its distance and the recording gain, so it can only be compared within one
recording: "this part is louder than that part", never "this is 60 dB loud".
"""

import math
from dataclasses import dataclass

import numpy as np

from app.pipeline.segmentation import Segment, Word, is_countable_word
from app.pipeline.settings import SAMPLE_RATE

# Energy is measured over 25 ms windows, every 10 ms.
FRAME_SAMPLES = 400
HOP_SAMPLES = 160
FRAMES_PER_SECOND = SAMPLE_RATE / HOP_SAMPLES
# Anything quieter than this is treated as digital silence.
FLOOR_DB = -100.0

TIMELINE_BIN_SECONDS = 0.25
# Sound this close to a speech segment is not used to judge the background level.
BACKGROUND_GUARD_SECONDS = 0.1
TIMELINE_MAX_POINTS = 1200

# Pitch search range in Hz: wide enough for low male and high female or child voices.
PITCH_MIN_HZ = 65.0
PITCH_MAX_HZ = 500.0
PITCH_FRAME_SAMPLES = 1024
PITCH_HOP_SAMPLES = 256
# Fewer voiced frames than this (about half a second) is too little to describe a voice.
MIN_VOICED_FRAMES = 30

# A word must stand out by at least this much to be suggested as emphasised.
EMPHASIS_ENERGY_DB = 3.0
EMPHASIS_PITCH_SEMITONES = 2.0
EMPHASIS_MIN_WORDS = 5
EMPHASIS_MAX_CANDIDATES = 10


def power_to_db(power: float) -> float:
    return max(FLOOR_DB, 10 * math.log10(power)) if power > 0 else FLOOR_DB


@dataclass(frozen=True)
class EnergyTrack:
    """Mean squared amplitude per frame, with the time at the centre of each frame."""

    power: np.ndarray
    times: np.ndarray

    def mean_db(self, start: float, end: float) -> float | None:
        selected = self.power[(self.times >= start) & (self.times <= end)]
        return power_to_db(float(selected.mean())) if selected.size else None


def measure_energy(samples: np.ndarray) -> EnergyTrack:
    if samples.shape[0] < FRAME_SAMPLES:
        samples = np.pad(samples, (0, FRAME_SAMPLES - samples.shape[0]))
    windows = np.lib.stride_tricks.sliding_window_view(samples, FRAME_SAMPLES)[::HOP_SAMPLES]
    power = np.mean(windows.astype(np.float64) ** 2, axis=1)
    times = (np.arange(power.shape[0]) * HOP_SAMPLES + FRAME_SAMPLES / 2) / SAMPLE_RATE
    return EnergyTrack(power, times)


def speech_mask(track: EnergyTrack, segments: list[Segment]) -> np.ndarray:
    mask = np.zeros(track.times.shape[0], dtype=bool)
    for segment in segments:
        mask |= (track.times >= segment.start) & (track.times <= segment.end)
    return mask


def energy_timeline(track: EnergyTrack, duration_seconds: float) -> tuple[float, list[float]]:
    """Loudness over time for drawing. Returns (seconds per point, dB values)."""
    bin_seconds = max(TIMELINE_BIN_SECONDS, duration_seconds / TIMELINE_MAX_POINTS)
    frames_per_bin = max(1, round(bin_seconds * FRAMES_PER_SECOND))
    values = [
        round(power_to_db(float(track.power[start : start + frames_per_bin].mean())), 1)
        for start in range(0, track.power.shape[0], frames_per_bin)
    ]
    return frames_per_bin / FRAMES_PER_SECOND, values


@dataclass(frozen=True)
class EnergySummary:
    # Standard deviation of loudness across quarter-second stretches of speech.
    variation_db: float | None
    # How far speech stands above the background, when there is enough background to judge.
    snr_db: float | None


def summarize_energy(track: EnergyTrack, segments: list[Segment]) -> EnergySummary:
    mask = speech_mask(track, segments)
    if not mask.any():
        return EnergySummary(None, None)

    frames_per_bin = round(TIMELINE_BIN_SECONDS * FRAMES_PER_SECOND)
    bin_levels = []
    for start in range(0, track.power.shape[0], frames_per_bin):
        in_bin = mask[start : start + frames_per_bin]
        # Only stretches that are mostly speech describe how the voice varies.
        if in_bin.mean() >= 0.5:
            bin_levels.append(
                power_to_db(float(track.power[start : start + frames_per_bin][in_bin].mean()))
            )
    variation = float(np.std(bin_levels)) if len(bin_levels) >= 4 else None

    # The background is judged well away from speech, and by its typical (median) level:
    # the edges of words and the odd click would otherwise count as background noise.
    near_speech = np.zeros_like(mask)
    for segment in segments:
        near_speech |= (track.times >= segment.start - BACKGROUND_GUARD_SECONDS) & (
            track.times <= segment.end + BACKGROUND_GUARD_SECONDS
        )
    background = track.power[~near_speech]
    snr = None
    if background.size >= FRAMES_PER_SECOND / 2:
        snr = power_to_db(float(track.power[mask].mean())) - power_to_db(
            float(np.median(background))
        )
    return EnergySummary(variation, snr)


@dataclass(frozen=True)
class PitchTrack:
    """Fundamental frequency in Hz for each frame judged to be voiced."""

    times: np.ndarray
    hz: np.ndarray

    def median_hz(self, start: float, end: float, *, min_frames: int) -> float | None:
        selected = self.hz[(self.times >= start) & (self.times <= end)]
        return float(np.median(selected)) if selected.size >= min_frames else None


def measure_pitch(samples: np.ndarray, segments: list[Segment]) -> PitchTrack:
    """Tracks pitch inside the speech segments only, using the pYIN algorithm."""
    import librosa

    times: list[np.ndarray] = []
    values: list[np.ndarray] = []
    for segment in segments:
        first = max(0, int(segment.start * SAMPLE_RATE))
        last = min(samples.shape[0], int(segment.end * SAMPLE_RATE))
        if last - first < PITCH_FRAME_SAMPLES * 2:
            continue
        f0, voiced, probability = librosa.pyin(
            samples[first:last],
            fmin=PITCH_MIN_HZ,
            fmax=PITCH_MAX_HZ,
            sr=SAMPLE_RATE,
            frame_length=PITCH_FRAME_SAMPLES,
            hop_length=PITCH_HOP_SAMPLES,
        )
        keep = voiced & (probability >= 0.5) & np.isfinite(f0)
        frame_times = segment.start + np.arange(f0.shape[0]) * PITCH_HOP_SAMPLES / SAMPLE_RATE
        times.append(frame_times[keep])
        values.append(f0[keep])

    if not values:
        return PitchTrack(np.array([]), np.array([]))
    return PitchTrack(np.concatenate(times), np.concatenate(values))


@dataclass(frozen=True)
class PitchSummary:
    median_hz: float
    # 5th to 95th percentile, which ignores the occasional octave jump of the tracker.
    low_hz: float
    high_hz: float
    range_semitones: float
    # Spread around the speaker's own median, so it does not depend on how deep the voice is.
    variation_semitones: float
    voiced_frames: int


def semitones(hz: float, reference_hz: float) -> float:
    return 12 * math.log2(hz / reference_hz)


def summarize_pitch(track: PitchTrack) -> PitchSummary | None:
    if track.hz.size < MIN_VOICED_FRAMES:
        return None
    median = float(np.median(track.hz))
    low, high = (float(value) for value in np.percentile(track.hz, [5, 95]))
    relative = 12 * np.log2(track.hz / median)
    return PitchSummary(
        median_hz=median,
        low_hz=low,
        high_hz=high,
        range_semitones=semitones(high, low),
        variation_semitones=float(np.std(relative)),
        voiced_frames=int(track.hz.size),
    )


@dataclass(frozen=True)
class EmphasisCandidate:
    word: Word
    reasons: tuple[str, ...]
    energy_delta_db: float | None
    pitch_delta_semitones: float | None
    score: float


def find_emphasis_candidates(
    words: list[Word], energy: EnergyTrack, pitch: PitchTrack, pitch_summary: PitchSummary | None
) -> list[EmphasisCandidate]:
    """Words that are clearly louder or higher than the speaker's own typical word.

    These are candidates only: the measurements say a word stands out, not that the
    speaker meant to stress it.
    """
    measured = []
    for word in words:
        if not is_countable_word(word.text) or word.end - word.start < 0.08:
            continue
        level = energy.mean_db(word.start, word.end)
        if level is not None:
            measured.append((word, level))
    if len(measured) < EMPHASIS_MIN_WORDS:
        return []

    typical_level = float(np.median([level for _, level in measured]))
    candidates: list[EmphasisCandidate] = []
    for word, level in measured:
        energy_delta = level - typical_level
        pitch_delta = None
        if pitch_summary is not None:
            word_pitch = pitch.median_hz(word.start, word.end, min_frames=3)
            if word_pitch is not None:
                pitch_delta = semitones(word_pitch, pitch_summary.median_hz)

        reasons = []
        score = 0.0
        if energy_delta >= EMPHASIS_ENERGY_DB:
            reasons.append("louder")
            score += energy_delta / EMPHASIS_ENERGY_DB
        if pitch_delta is not None and pitch_delta >= EMPHASIS_PITCH_SEMITONES:
            reasons.append("higher_pitch")
            score += pitch_delta / EMPHASIS_PITCH_SEMITONES
        if reasons:
            candidates.append(
                EmphasisCandidate(word, tuple(reasons), energy_delta, pitch_delta, score)
            )

    strongest = sorted(candidates, key=lambda c: c.score, reverse=True)[:EMPHASIS_MAX_CANDIDATES]
    return sorted(strongest, key=lambda c: c.word.start)
