"""Works a result out again from a transcript the user has corrected. No audio involved.

    stored result + corrected words -> a new result

Only what rests on the words is worked out again: word counts, the WPM figures, pace
variation, hesitation sounds. It is done by the same functions the audio pipeline uses, from
the corrected word count and the phrase's own measured length. Nothing is multiplied by a
correction factor.

Everything measured from the sound stays exactly as it was: where the phrases and pauses
are, how long they last, loudness and pitch. The stored result this starts from is not
touched; the caller saves the outcome as a new revision.
"""

from app import schemas, stretches
from app.comparison.align import align_words, match_key
from app.pipeline.fillers import find_hesitations
from app.pipeline.metrics import (
    SegmentPace,
    pace_vs_typical,
    segment_pace,
    summarize_pace,
    typical_wpm,
)
from app.pipeline.runner import (
    WARNINGS,
    WORD_WARNINGS,
    round_out,
    weaker,
    word_metric_values,
    word_quality_of,
)
from app.pipeline.segmentation import Segment, Stretch, Word, assign_words
from app.pipeline.settings import AnalysisSettings

CORRECTED = "transcript_corrected"


def same_words(a: str | None, b: str | None) -> bool:
    """Whether two versions of a phrase say the same thing, spacing aside."""
    return (a or "").split() == (b or "").split()


def retime(
    old_words: list[schemas.WordTiming], tokens: list[str], start: float, end: float
) -> list[Word]:
    """Gives the corrected words of one phrase their times.

    A corrected word that is also in the recognised version, at the same place in order,
    keeps the time and confidence the recogniser gave it. The words in between were never
    timed by anyone, so they are spread evenly across the gap they sit in, and carry no
    confidence: they come from the user, not from the recogniser.
    """
    pairs = {
        new: old
        for old, new in align_words(
            [match_key(word.text) for word in old_words], [match_key(token) for token in tokens]
        ).pairs
    }
    words: list[Word | None] = [
        Word(
            token,
            old_words[pairs[index]].start_seconds,
            old_words[pairs[index]].end_seconds,
            old_words[pairs[index]].confidence,
        )
        if index in pairs
        else None
        for index, token in enumerate(tokens)
    ]
    index = 0
    while index < len(words):
        if words[index] is not None:
            index += 1
            continue
        run_end = index
        while run_end < len(words) and words[run_end] is None:
            run_end += 1
        left = words[index - 1].end if index > 0 else start
        right = words[run_end].start if run_end < len(words) else end
        # Recognised times can stray; keep the gap inside the phrase and the right way round.
        left = min(max(left, start), end)
        right = min(max(right, left), end)
        share = (right - left) / (run_end - index)
        for offset in range(run_end - index):
            words[index + offset] = Word(
                tokens[index + offset], left + offset * share, left + (offset + 1) * share, None
            )
        index = run_end
    return [word for word in words if word is not None]


def _stored_pace(segment: schemas.SpeechSegment) -> SegmentPace:
    """A phrase whose words did not change keeps the figures it was stored with."""
    return SegmentPace(
        word_count=segment.word_count or 0,
        wpm=stretches.delivery_wpm_of(segment),
        speaking_wpm=segment.segment_wpm,
        confidence=segment.confidence,
        quality="unavailable"
        if segment.segment_wpm is None
        else "measured"
        if segment.reliable
        else "estimated",
        reliable=segment.reliable,
        flags=tuple(segment.flags),
    )


def correct_transcript(
    body: schemas.AnalysisBody, corrections: dict[str, str]
) -> tuple[schemas.AnalysisBody, list[str]]:
    """The result with the given phrases' words replaced. Also returns which phrases changed.

    `corrections` maps a segment ID to the words as they were really said. A phrase whose
    words come out the same as before is left alone.
    """
    # The settings the result was made with, not today's: the phrases were cut by those.
    settings = AnalysisSettings.from_dict(body.settings)
    changed = [
        segment.id
        for segment in body.segments
        if segment.id in corrections and not same_words(corrections[segment.id], segment.transcript)
    ]
    if not changed:
        return body, []

    stored_words: dict[str, list[schemas.WordTiming]] = {}
    for word in body.words:
        if word.segment_id:
            stored_words.setdefault(word.segment_id, []).append(word)

    stored_stretches: dict[str, list[schemas.SpeechStretch]] = {}
    for stretch in stretches.stretches_of(body):
        stored_stretches.setdefault(stretch.segment_id, []).append(stretch)

    had_transcript = bool(body.words)
    segments: list[Segment] = []
    paces: list[SegmentPace] = []
    for stored in body.segments:
        old_words = stored_words.get(stored.id, [])
        segment = Segment(
            index=stored.index,
            stretches=[
                Stretch(stretch.index, stretch.start_seconds, stretch.end_seconds)
                for stretch in stored_stretches[stored.id]
            ],
            section_index=stored.section_index,
        )
        by_index = {stretch.index: stretch for stretch in segment.stretches}
        if stored.id in changed:
            # A corrected word has no stretch of its own yet. It goes where its time puts
            # it, by the rule the pipeline uses, so it lands on one side of a pause inside
            # the phrase or the other.
            assign_words(
                [segment],
                retime(
                    old_words,
                    corrections[stored.id].split(),
                    stored.start_seconds,
                    stored.end_seconds,
                ),
            )
        else:
            for word in old_words:
                index = stretches.stretch_index_of(body, word)
                by_index.get(index, segment.stretches[0]).words.append(
                    Word(word.text, word.start_seconds, word.end_seconds, word.confidence)
                )
        segments.append(segment)
        paces.append(
            _stored_pace(stored)
            if stored.id not in changed and had_transcript
            else segment_pace(segment, settings, has_transcript=True)
        )

    all_words = [word for segment in segments for word in segment.words]
    language = body.language.code if body.language.source == "declared" else "auto"
    codes: list[str] = []
    word_quality = word_quality_of(all_words, 0, language, settings, codes)
    if not all_words:
        codes.append("no_words")
    # Whether the recogniser's timings lined up with the detected speech is a fact about
    # the original run. Correcting words does not make it better or worse.
    if any(warning.code == "word_timing_uncertain" for warning in body.warnings):
        codes.append("word_timing_uncertain")
        if word_quality == "measured":
            word_quality = "estimated"

    has_transcript = bool(all_words)
    pace = summarize_pace(
        segments,
        paces,
        body.duration_seconds,
        has_transcript=has_transcript,
        word_quality=word_quality,
    )
    typical = typical_wpm(paces, settings)
    hesitations = find_hesitations(all_words)

    word_segment = {
        id(word): stored.id
        for stored, segment in zip(body.segments, segments, strict=True)
        for word in segment.words
    }
    # A result from before segments could hold a pause keeps the shape it was stored in.
    with_stretches = stretches.has_delivery_pace(body)
    word_stretch = {
        id(word): stretch.index
        for segment in segments
        for stretch in segment.stretches
        for word in stretch.words
    }
    segments_out = [
        stored.model_copy(
            update={
                "transcript": " ".join(word.text for word in segment.words)
                if has_transcript
                else None,
                "word_count": info.word_count if has_transcript else None,
                "segment_wpm": round_out(info.speaking_wpm, 1),
                "delivery_wpm": round_out(info.wpm, 1) if with_stretches else None,
                "pace_vs_typical": pace_vs_typical(info, typical, settings),
                "quality": weaker(info.quality, word_quality),
                "reliable": info.reliable,
                "flags": list(info.flags),
                "confidence": round_out(info.confidence, 3),
            }
        )
        for stored, segment, info in zip(body.segments, segments, paces, strict=True)
    ]

    # Loudness and pitch per word were measured from the sound, which is not kept. A
    # candidate survives only if its word is still there, at the same time.
    still_said = {(match_key(word.text), round(word.start, 3)) for word in all_words}
    emphasis = [
        candidate
        for candidate in body.emphasis_candidates
        if (match_key(candidate.text), round(candidate.start_seconds, 3)) in still_said
    ]

    kept = [w for w in body.warnings if w.code not in WORD_WARNINGS and w.code != CORRECTED]
    added = [
        schemas.AnalysisWarning(code=code, message=WARNINGS[code])
        for code in dict.fromkeys([*codes, CORRECTED])
    ]
    corrected = body.model_copy(
        update={
            "transcript": " ".join(word.text for word in all_words) if has_transcript else None,
            "segments": segments_out,
            "words": [
                schemas.WordTiming(
                    text=word.text,
                    start_seconds=round_out(word.start, 3),
                    end_seconds=round_out(word.end, 3),
                    confidence=round_out(word.probability, 3),
                    segment_id=word_segment[id(word)],
                    stretch_index=word_stretch[id(word)] if with_stretches else None,
                )
                for word in all_words
            ],
            "metrics": body.metrics.model_copy(
                update={
                    name: value
                    for name, value in word_metric_values(
                        pace,
                        typical,
                        hesitation_count=len(hesitations),
                        has_transcript=has_transcript,
                        word_quality=word_quality,
                        settings=settings,
                    ).items()
                    if with_stretches or name != "delivery_wpm"
                }
            ),
            "emphasis_candidates": emphasis,
            "hesitations": [
                schemas.Hesitation(text=word.text, start_seconds=round_out(word.start, 3))
                for word in hesitations
            ],
            "warnings": [*kept, *added],
        }
    )
    return corrected, changed
