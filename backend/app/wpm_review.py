"""What goes into a WPM figure, laid out for a user who says it looks wrong.

A report of "the WPM looks too high" never changes the number. WPM is words divided by
time, so it can only be wrong if the words or the time are wrong. This lays both out, with
what was measured for each, and points at the feedback that would correct them.

The figure reviewed is the one the screen shows first: the delivery pace, which counts the
short pauses inside a phrase. In a result from before phrases could hold a pause, that is
the same number as the speaking speed.
"""

from typing import Literal

from app import schemas, stretches
from app.pipeline.segmentation import is_countable_word
from app.pipeline.settings import AnalysisSettings

# How many doubtful words are quoted.
QUOTED_WORDS = 5

# The same advice, worded for the user's own take (False) and for a reference recording
# (True), where "you" did not do the speaking.
NOT_SAID = {False: "A word you did not say", True: "A word that was not said"}
READ_AGAINST = {
    False: (
        " Read the words against what you said. If they are wrong, correct them: the WPM is "
        "then worked out again from your words."
    ),
    True: (
        " Read the words against what is said in the recording. If they are wrong, correct "
        "them: the WPM is then worked out again from the corrected words."
    ),
}
STILL_SPEAKING = {
    False: "If you were still speaking during one of them",
    True: "If the speaker was still speaking during one of them",
}


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
    on_reference: bool = False,
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
        f" {NOT_SAID[on_reference]}, or one word heard as two, makes the WPM too high."
        if too == "high"
        else " A word that was dropped, or two words heard as one, makes the WPM too low."
    )
    text += READ_AGAINST[on_reference]
    return schemas.WpmCheck(label="The words", text=text, action="correct_transcript")


def _formula(words: int | None, seconds: float | None, wpm: float | None) -> str:
    if words is None or not seconds or wpm is None:
        return "No WPM could be worked out here, because no words were recognised."
    return f"{words} words ÷ {seconds:.2f} s of speaking × 60 = {wpm:.1f} WPM."


def _pauses(count: int, seconds: float) -> str:
    return f"{count} {'pause' if count == 1 else 'pauses'}, {_seconds(seconds)} in all"


def _delivery_formula(
    words: int | None,
    seconds: float,
    wpm: float | None,
    pause_count: int,
    pause_seconds: float,
    speaking_wpm: float | None,
    *,
    where: str,
) -> str:
    """The arithmetic of a delivery pace, with the pauses it counts named."""
    if words is None or seconds <= 0 or wpm is None:
        return "No WPM could be worked out here, because no words were recognised."
    text = f"{words} words ÷ {seconds:.2f} s × 60 = {wpm:.1f} WPM."
    if pause_count == 0:
        return f"{text} There is no pause inside {where}, so all of that time is speaking."
    text += f" The {seconds:.2f} s include {_pauses(pause_count, pause_seconds)}, inside {where}."
    if speaking_wpm is not None:
        text += f" With those left out, the speaking speed is {speaking_wpm:.1f} WPM."
    return text


def _seconds(value: float) -> str:
    return f"{value:.2f} s"


def review(
    body: schemas.AnalysisBody,
    target_id: str | None,
    too: Literal["high", "low"],
    on_reference: bool = False,
) -> schemas.WpmReview:
    """The review for one segment, or for the whole recording when no segment is named.

    `on_reference` words it for a reference recording, where the user is not the speaker.
    """
    settings = AnalysisSettings.from_dict(body.settings)
    segment = next((s for s in body.segments if s.id == target_id), None)
    if segment is None:
        return _review_recording(body, settings, too, on_reference)

    checks = [
        _words_check(
            [word for word in body.words if word.segment_id == segment.id],
            settings,
            too,
            "in this phrase",
            on_reference,
        )
    ]

    inside = stretches.pauses_inside(body, segment.id)
    span = segment.end_seconds - segment.start_seconds
    length = (
        f"The phrase lasts {_seconds(span)}, of which {_seconds(segment.speech_active_seconds)} "
        "is speaking."
        if inside
        else f"The phrase lasts {_seconds(segment.speech_active_seconds)}."
    )
    if inside:
        checks.append(
            schemas.WpmCheck(
                label="The pauses inside the phrase",
                text=(
                    f"This phrase holds {_pauses(len(inside), segment.pause_seconds)}. They "
                    "are part of how the line was delivered, so the delivery pace counts "
                    "them, and comes out lower than the speaking speed. A pause is left "
                    "out of both only when it is long enough to end the phrase."
                ),
                action=None,
            )
        )
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
        between = [pause for pause in body.pauses if not pause.inside_segment]
        before = next((p for p in between if p.before_segment_id == segment.id), None)
        after = next((p for p in between if p.after_segment_id == segment.id), None)
        around = [
            f"a pause of {_seconds(pause.duration_seconds)} {side} it"
            for pause, side in ((before, "before"), (after, "after"))
            if pause is not None
        ]
        if around:
            text = (
                f"{length} There is {' and '.join(around)}. Time inside a pause that ends "
                f"a phrase is not counted. {STILL_SPEAKING[on_reference]}, the WPM comes "
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
    wpm = stretches.delivery_wpm_of(segment)
    return schemas.WpmReview(
        target=f"Segment {segment.index + 1}",
        words=segment.word_count,
        speaking_seconds=segment.speech_active_seconds,
        wpm=wpm,
        formula=_delivery_formula(
            segment.word_count,
            span,
            wpm,
            len(inside),
            segment.pause_seconds,
            segment.segment_wpm,
            where="the phrase",
        )
        if stretches.has_delivery_pace(body)
        else _formula(segment.word_count, segment.speech_active_seconds, wpm),
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
    body: schemas.AnalysisBody,
    settings: AnalysisSettings,
    too: Literal["high", "low"],
    on_reference: bool = False,
) -> schemas.WpmReview:
    metrics = body.metrics
    words = metrics.total_word_count.value
    seconds = metrics.speech_active_seconds.value
    speaking_wpm = metrics.speech_active_wpm.value
    with_delivery = stretches.has_delivery_pace(body)
    wpm = stretches.recording_delivery_wpm(body).value
    inside = [pause for pause in body.pauses if pause.inside_segment]
    inside_seconds = sum(pause.duration_seconds for pause in inside)
    delivery_seconds = sum(s.end_seconds - s.start_seconds for s in body.segments)
    checks = [_words_check(body.words, settings, too, "in the whole recording", on_reference)]

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
            f"time. {STILL_SPEAKING[on_reference]}, the WPM comes out too high: "
            "mark that pause as “Not a pause”."
        )
        action = "report_false_pause" if body.pauses else None
    checks.append(schemas.WpmCheck(label="The speaking time", text=text, action=action))

    whole = metrics.whole_clip_wpm.value
    if whole is not None and wpm is not None and with_delivery and speaking_wpm is not None:
        checks.append(
            schemas.WpmCheck(
                label="Which WPM this is",
                text=(
                    "This is the delivery pace: the short pauses inside a phrase are counted, "
                    "and the longer pauses that end a phrase are not. With every pause left "
                    f"out, the speaking speed is {speaking_wpm:.1f} WPM. Counting every "
                    f"pause in, and the silence before and after, the same recording comes "
                    f"to {whole:.1f} WPM. If you were comparing with a figure worked out "
                    "another way, that is the difference."
                ),
                action=None,
            )
        )
    elif whole is not None and wpm is not None:
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
    counted = None if words is None else int(words)
    return schemas.WpmReview(
        target="The whole recording",
        words=counted,
        speaking_seconds=seconds,
        wpm=wpm,
        formula=_delivery_formula(
            counted,
            delivery_seconds,
            wpm,
            len(inside),
            inside_seconds,
            speaking_wpm,
            where="the phrases",
        )
        if with_delivery
        else _formula(counted, seconds, wpm),
        checks=checks,
    )
