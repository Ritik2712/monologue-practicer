"""Voice activity detection: which parts of the recording contain speech.

Uses the Silero VAD model that ships inside faster-whisper. It is a small neural network
that runs locally and copes with background noise far better than a loudness threshold.
"""

import numpy as np

from app.pipeline.segmentation import SpeechRegion
from app.pipeline.settings import SAMPLE_RATE, AnalysisSettings


def detect_speech(samples: np.ndarray, settings: AnalysisSettings) -> list[SpeechRegion]:
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    options = VadOptions(
        threshold=settings.vad_threshold,
        min_speech_duration_ms=settings.vad_min_speech_ms,
        min_silence_duration_ms=settings.vad_min_silence_ms,
        # The library's default pads each side by 400 ms, which would shorten every pause
        # by up to 0.8 s. Pause lengths are the point here, so padding stays small.
        speech_pad_ms=settings.vad_speech_pad_ms,
    )
    timestamps = get_speech_timestamps(samples, options, sampling_rate=SAMPLE_RATE)
    duration = samples.shape[0] / SAMPLE_RATE
    return [
        SpeechRegion(
            max(0.0, stamp["start"] / SAMPLE_RATE), min(duration, stamp["end"] / SAMPLE_RATE)
        )
        for stamp in timestamps
    ]
