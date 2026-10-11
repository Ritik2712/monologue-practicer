"""Reading an audio file into the one format the rest of the pipeline uses:
mono, 16 kHz, floating-point samples between -1 and 1.

Decoding is done by PyAV, which bundles FFmpeg's decoders, so common browser and phone
formats (webm/opus, mp3, m4a, wav, ogg, flac) work without a separately installed ffmpeg.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.pipeline.errors import PipelineError
from app.pipeline.settings import SAMPLE_RATE

# A sample this close to full scale almost certainly hit the recorder's ceiling.
CLIPPING_LEVEL = 0.999


@dataclass(frozen=True)
class AudioProbe:
    has_audio: bool
    # None when the file does not say how long it is (typical for browser recordings).
    duration_seconds: float | None


def probe_audio(path: Path) -> AudioProbe:
    """A quick look at the file's header, without decoding the audio."""
    import av

    try:
        with av.open(str(path), mode="r") as container:
            if not container.streams.audio:
                return AudioProbe(False, None)
            stream = container.streams.audio[0]
            duration: float | None = None
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            elif container.duration is not None:
                duration = container.duration / av.time_base
            if duration is not None and duration <= 0:
                duration = None
            return AudioProbe(True, duration)
    except Exception as error:
        raise PipelineError(
            "unreadable_audio",
            "This file could not be read as audio. Try a WAV, MP3, M4A, OGG, FLAC or WebM file.",
        ) from error


def decode_audio(path: Path, *, max_seconds: float | None = None) -> np.ndarray:
    """Decodes the whole file. Stops early, with an error, once it exceeds `max_seconds`."""
    import av
    from av.audio.resampler import AudioResampler

    resampler = AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    max_samples = None if max_seconds is None else int(max_seconds * SAMPLE_RATE)
    chunks: list[np.ndarray] = []
    total = 0

    def collect(frames) -> None:
        nonlocal total
        for frame in frames:
            chunk = frame.to_ndarray().reshape(-1)
            chunks.append(chunk)
            total += chunk.shape[0]
        if max_samples is not None and total > max_samples:
            raise PipelineError(
                "audio_too_long",
                f"The recording is longer than the {_minutes(max_seconds)} limit.",
            )

    try:
        with av.open(str(path), mode="r") as container:
            if not container.streams.audio:
                raise PipelineError("no_audio_stream", "This file has no audio track.")
            for frame in container.decode(audio=0):
                collect(resampler.resample(frame))
            collect(resampler.resample(None))
    except PipelineError:
        raise
    except Exception as error:
        raise PipelineError(
            "unreadable_audio",
            "This file could not be read as audio. Try a WAV, MP3, M4A, OGG, FLAC or WebM file.",
        ) from error

    if total == 0:
        raise PipelineError("empty_audio", "The recording contains no audio.")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def clipping_ratio(samples: np.ndarray) -> float:
    """Share of samples at the recorder's ceiling. More than a trace means distortion."""
    if samples.size == 0:
        return 0.0
    return float(np.mean(np.abs(samples) >= CLIPPING_LEVEL))


def _minutes(seconds: float | None) -> str:
    minutes = (seconds or 0) / 60
    return f"{minutes:g}-minute"
