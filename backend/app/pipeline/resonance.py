"""Resonance: how deep or bright a voice sounds, measured from its formants.

A voice has resonances, called formants: bands of frequency that the throat and mouth
strengthen. A longer vocal tract puts them closer together and the voice sounds deeper; a
shorter one spreads them out and the voice sounds brighter. This is separate from pitch: two
voices can speak on the same note and still differ here.

The figure reported is the average spacing between the first three formants, in Hz. It is
found frame by frame with linear prediction (LPC), the standard way of estimating formants,
and summarised by medians, so the odd badly tracked frame does not move it.

Only the part of the sound below 4,000 Hz is used, and only three formants. A fourth, and
a higher ceiling, told the test voices apart a little better on clean recordings and far
worse on ones with any hiss: above 4,000 Hz a voice has little energy, so a formant
"found" there is as likely to be the background. The measurements behind this choice are
in DOCUMENTATION_SCIENCE.md.

Like loudness and pitch it is measured from the sound alone. It says how the voice sounds,
and nothing about who is speaking.
"""

from dataclasses import dataclass

import numpy as np

from app.pipeline.segmentation import Segment
from app.pipeline.settings import SAMPLE_RATE

# Formants are searched for below this frequency, with one pair of LPC coefficients for
# each of the four formants a voice can have there. The same values are used for every
# voice, deep or bright: choosing them by the kind of voice would decide the answer first.
CEILING_HZ = 4000.0
LPC_ORDER = 8
FORMANT_COUNT = 3
FRAME_SECONDS = 0.025
HOP_SECONDS = 0.010
# Each sample minus this share of the one before it: lifts the weaker high formants.
PRE_EMPHASIS = 0.97
# A resonance broader than this is not a formant, and one this low is the hum of the voice
# itself or of the room.
MAX_BANDWIDTH_HZ = 500.0
MIN_FORMANT_HZ = 90.0
# Frames much quieter than the loud parts of the speech are consonants, breaths and
# background, where there is no clear resonance to measure.
QUIET_BELOW_PEAK_DB = 20.0
LOUD_PERCENTILE = 95
# Fewer usable frames than this is too little to describe a phrase, or a recording.
MIN_SEGMENT_FRAMES = 20
MIN_RECORDING_FRAMES = 50
# A phrase with fewer usable frames than this (about a second and a half of voiced sound,
# which is two and a half seconds or so of speech) gets a figure labelled an estimate. In
# testing, of stretches 1 to 1.5 seconds long, 2 to 4 in a hundred landed in the opposite
# range and 10 to 16 in the neutral one; of stretches 2.5 seconds long, none landed in the
# opposite range.
RELIABLE_SEGMENT_FRAMES = 150

# Background hiss reads as resonance that is not there, and pushes the figure up, towards
# "brighter". Measured with hiss added to clean recordings: at 30 dB between voice and
# background the figure moved by 12 Hz typically and 54 Hz at worst; at 20 dB by 30 and 74;
# at 15 dB one deeper voice moved by 175 and landed in the higher range; at 10 dB by 97
# typically and 272 at worst. The lower range is 100 Hz wide. So under 30 dB the figure is
# labelled an estimate, and under 20 dB, where it can land in the wrong range, it is not
# given at all: a wrong answer here would tell a speaker their voice is brighter than it is.
ESTIMATE_BELOW_SNR_DB = 30.0
UNAVAILABLE_BELOW_SNR_DB = 20.0

# Formant n of a uniform tube lies at (2n - 1) / 2 times the spacing between formants.
_TUBE_POSITIONS = np.arange(1, FORMANT_COUNT + 1) - 0.5


def formant_spacing(formants_hz: np.ndarray) -> float:
    """The average spacing of the formants, from the best-fitting evenly spaced ladder.

    The higher formants weigh more in the fit. They depend least on which vowel is being
    said, so the figure describes the voice more than the words.
    """
    return float(np.sum(_TUBE_POSITIONS * formants_hz) / np.sum(_TUBE_POSITIONS**2))


@dataclass(frozen=True)
class ResonanceTrack:
    """The first three formants in Hz, for each frame in which they could be found."""

    times: np.ndarray
    # One row per frame, FORMANT_COUNT columns.
    formants: np.ndarray

    def formants_hz(self, start: float, end: float, *, min_frames: int) -> np.ndarray | None:
        """The typical (median) formants between two moments, or None with too few frames."""
        selected = self.formants[(self.times >= start) & (self.times <= end)]
        return np.median(selected, axis=0) if selected.shape[0] >= min_frames else None

    def spacing_hz(self, start: float, end: float, *, min_frames: int) -> float | None:
        formants = self.formants_hz(start, end, min_frames=min_frames)
        return None if formants is None else formant_spacing(formants)

    def frame_count(self, start: float, end: float) -> int:
        return int(np.count_nonzero((self.times >= start) & (self.times <= end)))


EMPTY = ResonanceTrack(np.array([]), np.empty((0, FORMANT_COUNT)))


def _frame_formants(frame: np.ndarray, rate: int) -> np.ndarray | None:
    """The first three formants of one windowed frame, or None if they cannot be told."""
    import librosa

    try:
        coefficients = librosa.lpc(frame, order=LPC_ORDER)
    except (FloatingPointError, ValueError):
        return None
    if not np.all(np.isfinite(coefficients)):
        return None
    roots = np.roots(coefficients)
    roots = roots[np.imag(roots) > 0]
    frequencies = np.angle(roots) * rate / (2 * np.pi)
    bandwidths = -rate / np.pi * np.log(np.abs(roots))
    plausible = (
        (frequencies > MIN_FORMANT_HZ)
        & (frequencies < CEILING_HZ - 50)
        & (bandwidths < MAX_BANDWIDTH_HZ)
    )
    found = np.sort(frequencies[plausible])
    return found[:FORMANT_COUNT] if found.shape[0] >= FORMANT_COUNT else None


def measure_resonance(samples: np.ndarray, segments: list[Segment]) -> ResonanceTrack:
    """Tracks the formants inside the speech segments only."""
    if not segments or samples.shape[0] == 0:
        return EMPTY
    import librosa

    rate = int(2 * CEILING_HZ)
    resampled = librosa.resample(samples.astype(np.float64), orig_sr=SAMPLE_RATE, target_sr=rate)
    frame, hop = int(FRAME_SECONDS * rate), int(HOP_SECONDS * rate)
    if resampled.shape[0] < frame:
        return EMPTY
    starts = np.arange(0, resampled.shape[0] - frame + 1, hop)
    times = (starts + frame / 2) / rate
    in_speech = np.zeros(times.shape[0], dtype=bool)
    for segment in segments:
        in_speech |= (times >= segment.start) & (times <= segment.end)
    if not in_speech.any():
        return EMPTY

    windows = np.lib.stride_tricks.sliding_window_view(resampled, frame)[starts]
    power = np.mean(windows**2, axis=1)
    loud = np.percentile(power[in_speech], LOUD_PERCENTILE)
    if loud <= 0:
        return EMPTY
    usable = in_speech & (power >= loud * 10 ** (-QUIET_BELOW_PEAK_DB / 10))

    emphasised = np.append(resampled[0], resampled[1:] - PRE_EMPHASIS * resampled[:-1])
    window = np.hamming(frame)
    kept_times: list[float] = []
    kept_formants: list[np.ndarray] = []
    for index in np.flatnonzero(usable):
        start = starts[index]
        formants = _frame_formants(emphasised[start : start + frame] * window, rate)
        if formants is not None:
            kept_times.append(float(times[index]))
            kept_formants.append(formants)
    if not kept_formants:
        return EMPTY
    return ResonanceTrack(np.array(kept_times), np.vstack(kept_formants))
