"""Reading the stretches of a stored result.

A segment is one or more stretches of unbroken speaking, with the short pauses between them
inside it. Results stored before segments could hold a pause record no stretches: there,
every pause ended a segment, so each segment is one stretch. These helpers give both kinds
of result the same shape, so the code that reads them does not have to care which it has.
"""

from app import schemas


def stretches_of(body: schemas.AnalysisBody) -> list[schemas.SpeechStretch]:
    """Every stretch of the recording, in order. Pause `n` lies after stretch `n`."""
    if body.stretches is not None:
        return body.stretches
    return [
        schemas.SpeechStretch(
            index=segment.index,
            start_seconds=segment.start_seconds,
            end_seconds=segment.end_seconds,
            segment_id=segment.id,
        )
        for segment in body.segments
    ]


def stretch_index_of(body: schemas.AnalysisBody, word: schemas.WordTiming) -> int | None:
    """The stretch a word was spoken in, or None for a word that belongs to no segment."""
    if word.stretch_index is not None:
        return word.stretch_index
    if body.stretches is not None or word.segment_id is None:
        return None
    return next((segment.index for segment in body.segments if segment.id == word.segment_id), None)


def pauses_inside(body: schemas.AnalysisBody, segment_id: str) -> list[schemas.PauseEvent]:
    """The pauses a segment holds: shorter than the segment break, so they did not end it."""
    return [
        pause
        for pause in body.pauses
        if pause.inside_segment and pause.after_segment_id == segment_id
    ]


def has_delivery_pace(body: schemas.AnalysisBody) -> bool:
    """False for a result from before segments could hold a pause.

    In such a result a segment's delivery pace and its speaking speed are the same number,
    stored once, as `segment_wpm`.
    """
    return body.stretches is not None


def delivery_wpm_of(segment: schemas.SpeechSegment) -> float | None:
    """A segment's delivery pace, whichever kind of result it is from."""
    return segment.delivery_wpm if segment.delivery_wpm is not None else segment.segment_wpm


def recording_delivery_wpm(body: schemas.AnalysisBody) -> schemas.MetricValue:
    """The recording's delivery pace, whichever kind of result it is from."""
    return body.metrics.delivery_wpm or body.metrics.speech_active_wpm
