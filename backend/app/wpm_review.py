"""What goes into a WPM figure, laid out for a user who says it looks wrong.

A report of "the WPM looks too high" never changes the number. WPM is words divided by
speaking time, so it can only be wrong if the words or the time are wrong. This lays both
out, with what was measured for each, and points at the feedback that would correct them.
"""

from typing import Literal

from app import schemas
from app.pipeline.segmentation import is_countable_word
from app.pipeline.settings import AnalysisSettings

# How many doubtful words are quoted.
QUOTED_WORDS = 5


def _unsure_words(words: list[schemas.WordTiming], settings: AnalysisSettings) -> list[str]:
    return [
        word.text
        for word in words
        if word.confidence is not None and word.confidence < settings.low_confidence
    ]


def _words_check(
    words: list[schemas.WordTiming],
    settings: AnalysisSettings,
    too: Literal["high", "low"],
    where: str,
) -> schemas.WpmCheck:
    counted = [word for word in words if is_countable_word(word.text)]
    unsure = _unsure_words(counted, settings)
    text = f"{len(counted)} {'word was' if len(counted) == 1 else 'words were'} counted {where}."
    if unsure:
        quoted = ", ".join(f"“{word}”" for word in unsure[:QUOTED_WORDS])
        more = len(unsure) - QUOTED_WORDS
        text += (
            f" The speech recogniser was unsure of {len(unsure)} of them: {quoted}"
            + (f", and {more} more" if more > 0 else "")
            + "."
        )
    elif counted:
        text += " The speech recogniser was reasonably sure of each of them."
    text += (
        " A word you did not say, or one word heard as two, makes the WPM too high."
        if too == "high"
        else " A word that was dropped, or two words heard as one, makes the WPM too low."
    )
    text += (
        " Read the words against what you said. If they are wrong, correct them: the WPM is "
        "then worked out again from your words."
    )
    return schemas.WpmCheck(label="The words", text=text, action="correct_transcript")


def _formula(words: int | None, seconds: float | None, wpm: float | None) -> str:
    if words is None or not seconds or wpm is None:
        return "No WPM could be worked out here, because no words were recognised."
    return f"{words} words ÷ {seconds:.2f} s of speaking × 60 = {wpm:.1f} WPM."


def _seconds(value: float) -> str:
    return f"{value:.2f} s"


def review(
    body: schemas.AnalysisBody, target_id: str | None, too: Literal["high", "low"]
) -> schemas.WpmReview:
    """The review for one segment, or for the whole recording when no segment is named."""
    settings = AnalysisSettings.from_dict(body.settings)
    segment = next((s for s in body.segments if s.id == target_id), None)
    if segment is None:
        return _review_recording(body, settings, too)

    checks = [
        _words_check(
            [word for word in body.words if word.segment_id == segment.id],
            settings,
            too,
            "in this phrase",
        )
    ]

    length = f"The phrase lasts {_seconds(segment.speech_active_seconds)}."
    if too == "low":
        silences = [s for s in body.short_silences or [] if s.segment_id == segment.id]
        if body.short_silences is None:
            text = f"{length} Short silences inside phrases were not recorded for this result."
            action = None
        elif silences:
            total = sum(s.duration_seconds for s in silences)
            text = (
                f"{length} Inside it {'is' if len(silences) == 1 else 'are'} {len(silences)} "
                f"{'silence' if len(silences) == 1 else 'silences'} too short to count as a "
                f"pause, {_seconds(total)} in all, and that counts as speaking time. If one "
                "was a real pause, report it as a missed pause."
            )
            action = "report_missed_pause"
        else:
            text = f"{length} No silence was detected inside it, so all of it is speaking time."
            action = None
    else:
        before = next((p for p in body.pauses if p.before_segment_id == segment.id), None)
        after = next((p for p in body.pauses if p.after_segment_id == segment.id), None)
        around = [
            f"a pause of {_seconds(pause.duration_seconds)} {side} it"
            for pause, side in ((before, "before"), (after, "after"))
            if pause is not None
        ]
        if around:
            text = (
                f"{length} There is {' and '.join(around)}. Time inside a pause is not "
                "speaking time. If you were still speaking during one of them, the WPM comes "
                "out too high: mark that pause as “Not a pause”."
            )
            action = "report_false_pause"
        else:
            text = f"{length} No pause borders it."
            action = None
    checks.append(schemas.WpmCheck(label="The speaking time", text=text, action=action))

    if "short_segment" in segment.flags or "few_words" in segment.flags:
        checks.append(
            schemas.WpmCheck(
                label="How much there is to measure",
                text=(
                    "This phrase is short. Over so little speech, one word more or less moves "
                    "the WPM a long way, which is why the figure is marked as an estimate. "
                    "That alone can make it look wrong."
                ),
                action=None,
            )
        )
    if "wpm_outlier" in segment.flags:
        checks.append(
            schemas.WpmCheck(
                label="Flagged for review",
                text=(
                    f"The figure is above {settings.wpm_outlier:.0f} WPM, the level at which "
                    "the app flags a phrase for review. The figure itself was not changed."
                ),
                action=None,
            )
        )
    checks += _timing_check(body, segment)
    return schemas.WpmReview(
        target=f"Segment {segment.index + 1}",
        words=segment.word_count,
        speaking_seconds=segment.speech_active_seconds,
        wpm=segment.segment_wpm,
        formula=_formula(segment.word_count, segment.speech_active_seconds, segment.segment_wpm),
        checks=checks,
    )


def _timing_check(
    body: schemas.AnalysisBody, segment: schemas.SpeechSegment | None = None
) -> list[schemas.WpmCheck]:
    """Whether the recogniser's word times agree with where the speech was detected.

    Each word is counted in the phrase its time falls in. A word timed inside a pause is
    given to the nearest phrase, which is where a count can end up in the wrong phrase.
    """
    spans = {s.id: (s.start_seconds, s.end_seconds) for s in body.segments}

    def strayed(word: schemas.WordTiming) -> bool:
        span = spans.get(word.segment_id or "")
        middle = (word.start_seconds + word.end_seconds) / 2
        return span is None or not span[0] <= middle <= span[1]

    words = [
        word
        for word in body.words
        if is_countable_word(word.text) and (segment is None or word.segment_id == segment.id)
    ]
    moved = [word.text for word in words if strayed(word)]
    where = "this phrase" if segment else "a phrase"
    if moved:
        quoted = ", ".join(f"“{word}”" for word in moved[:QUOTED_WORDS])
        more = len(moved) - QUOTED_WORDS
        text = (
            f"{len(moved)} of the {len(words)} words "
            f"{'was' if len(moved) == 1 else 'were'} timed by the recogniser outside {where} "
            f"and counted in the nearest one: {quoted}"
            + (f", and {more} more" if more > 0 else "")
            + ". A word like that may belong to the phrase next door."
        )
    elif words:
        text = f"Every word's timing falls inside {'this phrase' if segment else 'the phrase it was counted in'}."
    else:
        return []
    if any(warning.code == "word_timing_uncertain" for warning in body.warnings):
        text += (
            " Across the whole recording, many word timings did not line up with the "
            "detected speech, so counts per phrase are estimates."
        )
    return [schemas.WpmCheck(label="Word timing", text=text, action=None)]


def _review_recording(
    body: schemas.AnalysisBody, settings: AnalysisSettings, too: Literal["high", "low"]
) -> schemas.WpmReview:
    metrics = body.metrics
    words = metrics.total_word_count.value
    seconds = metrics.speech_active_seconds.value
    wpm = metrics.speech_active_wpm.value
    checks = [_words_check(body.words, settings, too, "in the whole recording")]

    pauses = (
        f"{len(body.pauses)} {'pause' if len(body.pauses) == 1 else 'pauses'}, "
        f"{_seconds(sum(p.duration_seconds for p in body.pauses))} in all, were left out of it"
    )
    spoken = f"{_seconds(seconds)} of the recording counted as speaking" if seconds else None
    if spoken is None:
        text, action = "No speech was detected.", None
    elif too == "low":
        silences = body.short_silences
        if silences is None:
            inside = "Short silences inside phrases were not recorded for this result."
        elif silences:
            inside = (
                f"That includes {len(silences)} "
                f"{'silence' if len(silences) == 1 else 'silences'} too short to count as a "
                f"pause, {_seconds(sum(s.duration_seconds for s in silences))} in all. If some "
                "were real pauses, report them as missed pauses in their phrases."
            )
        else:
            inside = "No shorter silence was detected inside the phrases."
        text = f"{spoken[0].upper()}{spoken[1:]}; {pauses}. {inside}"
        action = "report_missed_pause" if silences else None
    else:
        text = (
            f"{spoken[0].upper()}{spoken[1:]}; {pauses}. Time inside a pause is not speaking "
            "time. If you were still speaking during one of them, the WPM comes out too high: "
            "mark that pause as “Not a pause”."
        )
        action = "report_false_pause" if body.pauses else None
    checks.append(schemas.WpmCheck(label="The speaking time", text=text, action=action))

    whole = metrics.whole_clip_wpm.value
    if whole is not None and wpm is not None:
        checks.append(
            schemas.WpmCheck(
                label="Which WPM this is",
                text=(
                    f"This is the WPM while speaking, with pauses left out. Counting the "
                    f"pauses in, the same recording comes to {whole:.1f} WPM. If you were "
                    "comparing with a figure worked out the second way, that is the difference."
                ),
                action=None,
            )
        )
    checks += _timing_check(body)
    return schemas.WpmReview(
        target="The whole recording",
        words=None if words is None else int(words),
        speaking_seconds=seconds,
        wpm=wpm,
        formula=_formula(None if words is None else int(words), seconds, wpm),
        checks=checks,
    )
