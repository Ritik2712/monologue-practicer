"""The outline of a recording's sound wave, for drawing.

This is a picture, not a measurement. Nothing else in the pipeline reads it: speaking rate,
pauses, loudness and pitch are all worked out elsewhere, from the samples themselves.

A recording has far too many samples to draw (ten minutes is 9.6 million), so the samples
are grouped into at most a couple of thousand buckets and only the lowest and highest sample
of each bucket is kept. Drawn as a filled band, that looks the same as drawing every sample.
"""

import math

import numpy as np

from app import schemas
from app.pipeline.settings import SAMPLE_RATE

# Enough for a sharp picture on a wide screen, and small enough to send in one response.
MAX_POINTS = 2000
# A short recording is not split finer than this: beyond it the eye sees no more detail.
MIN_SECONDS_PER_POINT = 0.005


def waveform_outline(
    samples: np.ndarray, sample_rate: int = SAMPLE_RATE, max_points: int = MAX_POINTS
) -> schemas.Waveform:
    """Lowest and highest sample in each bucket, on the recording's own scale (-1 to 1).

    The values are not normalised: a quiet recording gives a thin outline. Whether to
    stretch it for looking at is a choice for the screen, and it says so when it does.
    """
    count = int(samples.shape[0])
    duration = count / sample_rate
    if count == 0:
        return schemas.Waveform(duration_seconds=0.0, seconds_per_point=0.0, minimum=[], maximum=[])
    per_point = max(math.ceil(count / max_points), round(MIN_SECONDS_PER_POINT * sample_rate))
    points = math.ceil(count / per_point)
    # Pad the last bucket with its own final sample so every bucket is the same size.
    padded = np.pad(samples, (0, points * per_point - count), mode="edge")
    buckets = padded.reshape(points, per_point)
    return schemas.Waveform(
        duration_seconds=round(duration, 3),
        seconds_per_point=per_point / sample_rate,
        minimum=[round(float(value), 3) for value in buckets.min(axis=1)],
        maximum=[round(float(value), 3) for value in buckets.max(axis=1)],
    )
