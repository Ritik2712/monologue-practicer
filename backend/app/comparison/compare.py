"""Sets a take against a reference recording of the same passage.

Both recordings were measured by the same pipeline. This file only reads those two stored
results and does arithmetic on them: it never touches audio, and it changes neither result.

    two results -> line up the words -> pauses compared -> phrases compared -> differences

Three things are deliberately not compared, because the difference would say nothing about
the performance: how loud each recording is, how high each voice is, and the sound waves
themselves.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from app import schemas
from app.calibration.registry import MIN_PAUSE, show
from app.coaching.findings import number, seconds_text
from app.comparison.align import Alignment, align_words, match_key
from app.comparison.settings import ComparisonSettings

# How many words of a phrase are shown when pointing at it.
QUOTED_WORDS = 6


@dataclass(frozen=True)
class MetricSpec:
    name: str
    label: str
    unit: str
    digits: int
    scale: float = 1.0
    note: str | None = None


# The whole-recording figures worth setting side by side. Loudness level and median pitch
# are left out on purpose: see the caveats.
METRICS: tuple[MetricSpec, ...] = (
    MetricSpec("speechActiveSeconds", "Time speaking", "s", 1),
    MetricSpec("totalWordCount", "Words", "", 0),
    MetricSpec("speechActiveWpm", "Speech-active WPM", "WPM", 1),
    MetricSpec("wholeClipWpm", "Whole-clip WPM (including pauses)", "WPM", 1),
    MetricSpec("paceVariation", "Pace variation", "WPM", 1),
    MetricSpec("pauseCount", "Pauses", "", 0),
    MetricSpec("medianPauseSeconds", "Median pause", "s", 2),
    MetricSpec("longestPauseSeconds", "Longest pause", "s", 2),
    MetricSpec("totalPauseSeconds", "Total pause time", "s", 1),
    MetricSpec("pauseRatio", "Share of the recording spent in pauses", "%", 0, scale=100),
    MetricSpec(
        "energyVariation",
        "Loudness variation",
        "dB",
        1,
        note="Also depends on how each recording was made, for example on compression.",
    ),
    MetricSpec("pitchVariationSemitones", "Pitch variation", "semitones", 2),
    MetricSpec("pitchRangeSemitones", "Pitch range", "semitones", 1),
)

NOT_COMPARED = (
    "Loudness itself is not compared. How loud a recording is depends on the microphone, "
    "the distance and how it was processed, not on the performance."
)
PITCH_NOT_COMPARED = (
    "How high each voice is, is not compared. Two voices differ in pitch; only how much "
    "each one moves is set side by side."
)
WORD_TIMES_NOTE = (
    "Phrases are lined up through the recognised words, whose times are good to about a "
    "tenth of a second. Phrase-by-phrase pace is therefore an estimate."
)
REFERENCE_SOUNDS_NOTE = (
    "If the reference has music, other voices or effects in it, its pauses and voice "
    "figures are less reliable than those of a clean recording."
)


class Side:
    """One recording, prepared for comparison."""

    def __init__(self, body: schemas.AnalysisBody) -> None:
        self.body = body
        # Only words with something to match on; a lone punctuation mark has none.
        self.words = [word for word in body.words if match_key(word.text)]
        self.keys = [match_key(word.text) for word in self.words]
        self.segments = {segment.id: segment for segment in body.segments}
        # For each segment, the positions of its first and last word in `self.words`.
        self.segment_words: dict[str, tuple[int, int]] = {}
        for index, word in enumerate(self.words):
            if word.segment_id is None:
                continue
            first, _ = self.segment_words.get(word.segment_id, (index, index))
            self.segment_words[word.segment_id] = (first, index)

    def pauses_between(self, left: int, right: int) -> list:
        """The pauses that fall between two words, given by their positions in `self.words`.

        Decided by which phrase each word belongs to, never by the words' own times. A
        pause is by definition the gap between two phrases, and the recogniser's word times
        stray: the first word after a pause is often given a start time inside the pause.
        Two words of the same phrase therefore have no pause between them, whatever their
        times say.
        """
        first = self.segments.get(self.words[left].segment_id or "")
        last = self.segments.get(self.words[right].segment_id or "")
        if first is None or last is None:
            return []
        # Pause number i lies between phrase number i and phrase number i + 1.
        return [pause for pause in self.body.pauses if first.index <= pause.index < last.index]

    def clamp(self, start: float, end: float) -> schemas.PlayRange:
        return schemas.PlayRange(
            start_seconds=round(max(0.0, start), 3),
            end_seconds=round(min(self.body.duration_seconds, max(end, start)), 3),
        )

    def last_words(self, segment_id: str) -> str:
        """The closing words of a phrase, to say where a pause falls."""
        words = (self.segments[segment_id].transcript or "").split()
        shown = " ".join(words[-QUOTED_WORDS:]).rstrip(".,;:!?।")
        return ("…" if len(words) > QUOTED_WORDS else "") + shown


class Bridge:
    """Carries a position from one recording to the same place in the other."""

    def __init__(self, pairs: list[tuple[int, int]], max_gap: int) -> None:
        self.source = [a for a, _ in pairs]
        self.target = [b for _, b in pairs]
        self.max_gap = max_gap

    def at_or_before(self, index: int) -> int | None:
        """The partner of the nearest matched word at or before `index`, if close enough."""
        position = bisect_right(self.source, index) - 1
        if position < 0 or index - self.source[position] > self.max_gap:
            return None
        return self.target[position]

    def at_or_after(self, index: int) -> int | None:
        position = bisect_left(self.source, index)
        if position >= len(self.source) or self.source[position] - index > self.max_gap:
            return None
        return self.target[position]

    def within(self, first: int, last: int) -> list[tuple[int, int]]:
        """The matched words from position `first` to `last`, with their partners."""
        lo, hi = bisect_left(self.source, first), bisect_right(self.source, last)
        return list(zip(self.source[lo:hi], self.target[lo:hi], strict=True))


# --- Whole recordings --------------------------------------------------------------------


def compare_metrics(
    take: schemas.AnalysisBody, reference: schemas.AnalysisBody
) -> list[schemas.ComparedMetric]:
    def row(spec: MetricSpec, mine, theirs, estimated: bool) -> schemas.ComparedMetric:
        def shown(value: float | None) -> float | None:
            return None if value is None else round(value * spec.scale, spec.digits)

        a, b = shown(mine), shown(theirs)
        return schemas.ComparedMetric(
            metric=spec.name,
            label=spec.label,
            unit=spec.unit,
            digits=spec.digits,
            take=a,
            reference=b,
            # From the rounded values, so the three columns always add up on screen.
            difference=None if a is None or b is None else round(a - b, spec.digits),
            estimated=estimated,
            note=spec.note,
        )

    mine = take.metrics.model_dump(by_alias=True)
    theirs = reference.metrics.model_dump(by_alias=True)
    rows = [
        row(
            MetricSpec("durationSeconds", "Length of the recording", "s", 1),
            take.duration_seconds,
            reference.duration_seconds,
            False,
        )
    ]
    for spec in METRICS:
        a, b = mine[spec.name], theirs[spec.name]
        estimated = "estimated" in (a["quality"], b["quality"])
        rows.append(row(spec, a["value"], b["value"], estimated))
    return rows


# --- Pauses ------------------------------------------------------------------------------


def _side_of(pause) -> schemas.PauseSide:
    return schemas.PauseSide(
        pause_id=pause.id,
        start_seconds=pause.start_seconds,
        end_seconds=pause.end_seconds,
        duration_seconds=pause.duration_seconds,
    )


def _around(side: Side, start: float, end: float, context: float) -> schemas.PlayRange:
    return side.clamp(start - context, end + context)


def _locate(pause, here: Side, there: Side, bridge: Bridge) -> tuple[int, int] | None:
    """The two words of the other recording that a pause in this one falls between.

    The pause sits between the last word of one phrase and the first word of the next. If
    matched words can be found close on both sides, their partners in the other recording
    mark the same place there. Returns their positions in the other recording's words.
    """
    before = here.segment_words.get(pause.after_segment_id)
    after = here.segment_words.get(pause.before_segment_id)
    if before is None or after is None:
        return None
    left, right = bridge.at_or_before(before[1]), bridge.at_or_after(after[0])
    if left is None or right is None or right <= left:
        return None
    return left, right


def _spot(side: Side, left: int, right: int, context: float) -> schemas.PlayRange:
    """What to play to hear the place between two words, where that recording has no pause."""
    return _around(side, side.words[left].end_seconds, side.words[right].start_seconds, context)


def compare_pauses(
    take: Side, reference: Side, alignment: Alignment, settings: ComparisonSettings
) -> list[schemas.ComparedPause]:
    """Every pause of the reference, and every extra pause of the take, in passage order."""
    context = settings.pause_context_seconds
    to_take = Bridge(alignment.pairs, settings.max_anchor_gap_words)
    to_reference = Bridge([(b, a) for a, b in alignment.pairs], settings.max_anchor_gap_words)
    used: set[str] = set()
    # Each row with the reference time it belongs at, so the list reads in passage order.
    rows: list[tuple[float, schemas.ComparedPause]] = []

    for pause in reference.body.pauses:
        reference_side = _side_of(pause)
        reference_play = _around(reference, pause.start_seconds, pause.end_seconds, context)
        after_words = reference.last_words(pause.after_segment_id)
        spot = _locate(pause, reference, take, to_take)
        if spot is None:
            row = schemas.ComparedPause(
                status="unplaced",
                after_words=after_words,
                reference=reference_side,
                take=None,
                difference_seconds=None,
                reference_play=reference_play,
                take_play=None,
            )
            rows.append((pause.start_seconds, row))
            continue

        candidates = [p for p in take.pauses_between(*spot) if p.id not in used]
        if candidates:
            # A phrase split in two by the speaker can leave two pauses here; the longer
            # one is the one a listener would hear as "the" pause.
            match = max(candidates, key=lambda p: p.duration_seconds)
            used.add(match.id)
            row = schemas.ComparedPause(
                status="both",
                after_words=after_words,
                reference=reference_side,
                take=_side_of(match),
                difference_seconds=round(match.duration_seconds - pause.duration_seconds, 2),
                reference_play=reference_play,
                take_play=_around(take, match.start_seconds, match.end_seconds, context),
            )
        else:
            row = schemas.ComparedPause(
                status="reference_only",
                after_words=after_words,
                reference=reference_side,
                take=None,
                difference_seconds=None,
                reference_play=reference_play,
                take_play=_spot(take, *spot, context),
            )
        rows.append((pause.start_seconds, row))

    for pause in take.body.pauses:
        if pause.id in used:
            continue
        spot = _locate(pause, take, reference, to_reference)
        if spot is None:
            # A pause in a part of the take that has no counterpart: nothing to say about it.
            continue
        if reference.pauses_between(*spot):
            # The reference pauses here as well; that pause already has its own row.
            continue
        row = schemas.ComparedPause(
            status="take_only",
            after_words=take.last_words(pause.after_segment_id),
            reference=None,
            take=_side_of(pause),
            difference_seconds=None,
            reference_play=_spot(reference, *spot, context),
            take_play=_around(take, pause.start_seconds, pause.end_seconds, context),
        )
        rows.append((reference.words[spot[0]].end_seconds, row))

    return [row for _, row in sorted(rows, key=lambda item: item[0])]


# --- Phrases -----------------------------------------------------------------------------


def compare_phrases(
    take: Side, reference: Side, alignment: Alignment, settings: ComparisonSettings
) -> list[schemas.ComparedPhrase]:
    """The pace of each phrase of the reference, against the same words in the take."""
    to_take = Bridge(alignment.pairs, 0)
    phrases: list[schemas.ComparedPhrase] = []
    for segment in reference.body.segments:
        span = reference.segment_words.get(segment.id)
        if span is None:
            continue
        first, last = span
        word_count = last - first + 1
        matched = to_take.within(first, last)
        coverage = len(matched) / word_count
        reference_play = reference.clamp(segment.start_seconds, segment.end_seconds)
        phrase = schemas.ComparedPhrase(
            reference_segment_id=segment.id,
            text=segment.transcript or "",
            coverage=round(coverage, 2),
            comparable=False,
            reference_wpm=None,
            take_wpm=None,
            difference_wpm=None,
            difference_ratio=None,
            reference_play=reference_play,
            take_play=None,
        )
        phrases.append(phrase)
        if not matched:
            continue

        (r1, t1), (r2, t2) = matched[0], matched[-1]
        take_start, take_end = take.words[t1].start_seconds, take.words[t2].end_seconds
        phrase.take_play = take.clamp(take_start, take_end)
        if word_count < settings.phrase_min_words or coverage < settings.phrase_min_coverage:
            continue

        # Both paces are taken over the same stretch of words: from the first matched word
        # to the last. Pauses the take makes inside that stretch are left out, as always.
        reference_seconds = reference.words[r2].end_seconds - reference.words[r1].start_seconds
        take_seconds = (take_end - take_start) - sum(
            pause.duration_seconds for pause in take.pauses_between(t1, t2)
        )
        if min(reference_seconds, take_seconds) < settings.phrase_min_seconds:
            continue
        reference_wpm = (r2 - r1 + 1) / (reference_seconds / 60)
        take_wpm = (t2 - t1 + 1) / (take_seconds / 60)
        phrase.comparable = True
        phrase.reference_wpm = round(reference_wpm, 1)
        phrase.take_wpm = round(take_wpm, 1)
        phrase.difference_wpm = round(phrase.take_wpm - phrase.reference_wpm, 1)
        phrase.difference_ratio = round(take_wpm / reference_wpm - 1, 3)
    return phrases


# --- The biggest differences --------------------------------------------------------------


def _quote(text: str) -> str:
    words = text.split()
    return "“" + " ".join(words[:QUOTED_WORDS]) + ("…" if len(words) > QUOTED_WORDS else "") + "”"


def find_differences(
    metrics: list[schemas.ComparedMetric],
    pauses: list[schemas.ComparedPause],
    phrases: list[schemas.ComparedPhrase],
    settings: ComparisonSettings,
) -> list[schemas.Difference]:
    """The differences a listener would most notice, largest first.

    Each kind is weighed in rough seconds of silence, so a missing two-second pause and a
    phrase taken much too fast can be put in one order.
    """
    found: list[tuple[float, schemas.Difference]] = []

    def add(weight: float, kind: str, statement: str, source) -> None:
        difference = schemas.Difference(
            kind=kind,
            statement=statement,
            reference_play=source.reference_play if source else None,
            take_play=source.take_play if source else None,
        )
        found.append((weight, difference))

    for pause in pauses:
        after = f"after “{pause.after_words}”"
        if pause.status == "reference_only":
            length = pause.reference.duration_seconds
            if length >= settings.notable_pause_seconds:
                add(
                    min(length, 3.0),
                    "pause_missing",
                    f"The reference pauses for {seconds_text(length)} {after}. You did not "
                    "pause there.",
                    pause,
                )
        elif pause.status == "take_only":
            length = pause.take.duration_seconds
            if length >= settings.notable_pause_seconds:
                add(
                    min(length, 3.0) * 0.7,
                    "pause_extra",
                    f"You paused for {seconds_text(length)} {after}. The reference does not "
                    "pause there.",
                    pause,
                )
        elif pause.status == "both":
            theirs, mine = pause.reference.duration_seconds, pause.take.duration_seconds
            change = abs(mine - theirs)
            if (
                change >= settings.notable_pause_change_seconds
                and change >= settings.notable_pause_change_ratio * theirs
            ):
                add(
                    min(change, 3.0) * 0.8,
                    "pause_shorter" if mine < theirs else "pause_longer",
                    f"The reference holds {seconds_text(theirs)} {after}; you held "
                    f"{seconds_text(mine)}.",
                    pause,
                )

    for phrase in phrases:
        ratio = phrase.difference_ratio
        if not phrase.comparable or ratio is None:
            continue
        if abs(ratio) >= settings.notable_phrase_pace_ratio:
            add(
                abs(ratio) * 3.0,
                "phrase_faster" if ratio > 0 else "phrase_slower",
                f"You said {_quote(phrase.text)} at {number(phrase.take_wpm)} WPM. The "
                f"reference says it at {number(phrase.reference_wpm)} WPM, so you were "
                f"{round(abs(ratio) * 100)}% {'faster' if ratio > 0 else 'slower'}.",
                phrase,
            )

    pace = next((m for m in metrics if m.metric == "speechActiveWpm"), None)
    if pace and pace.take and pace.reference:
        ratio = pace.take / pace.reference - 1
        if abs(ratio) >= settings.notable_overall_pace_ratio:
            add(
                abs(ratio) * 2.0,
                "overall_faster" if ratio > 0 else "overall_slower",
                f"Overall you spoke at {number(pace.take)} WPM while speaking; the reference "
                f"speaks at {number(pace.reference)} WPM. That is {round(abs(ratio) * 100)}% "
                f"{'faster' if ratio > 0 else 'slower'}.",
                None,
            )

    found.sort(key=lambda item: -item[0])
    return [difference for _, difference in found[: settings.max_differences]]


# --- Everything together -----------------------------------------------------------------


def _alignment_summary(
    alignment: Alignment, take: Side, reference: Side, settings: ComparisonSettings
) -> schemas.AlignmentSummary:
    share = round(alignment.coverage * 100)
    if not reference.words or not take.words:
        which = "the reference" if not reference.words else "your take"
        status, note = (
            "no_words",
            (
                f"No words were recognised in {which}, so the two cannot be lined up phrase by "
                "phrase. They are compared only as whole recordings."
            ),
        )
    elif alignment.coverage >= settings.matched_coverage:
        status, note = (
            "matched",
            (
                f"{share}% of the reference's words were found in your take, in the same order, "
                "so the two could be lined up phrase by phrase."
            ),
        )
    elif alignment.coverage >= settings.partial_coverage:
        status, note = (
            "partial",
            (
                f"Only {share}% of the reference's words were found in your take, in the same "
                "order. The parts that match are lined up; the rest is not compared."
            ),
        )
    else:
        status, note = (
            "unmatched",
            (
                f"Only {share}% of the reference's words were found in your take, so they do "
                "not appear to be the same passage. They are compared only as whole recordings."
            ),
        )
    return schemas.AlignmentSummary(
        status=status,
        matched_words=len(alignment.pairs),
        reference_words=alignment.reference_words,
        take_words=alignment.take_words,
        coverage=round(alignment.coverage, 3),
        note=note,
    )


def settings_note(take: schemas.AnalysisBody, reference: schemas.AnalysisBody) -> str | None:
    """Says so when the two recordings were analysed with a different minimum pause.

    Feedback can move the minimum pause. Two results made either side of such a change cut
    their pauses differently, and setting them side by side without saying so would pass a
    change of settings off as a change of delivery.
    """
    mine = take.settings.get(MIN_PAUSE.name, MIN_PAUSE.default)
    theirs = reference.settings.get(MIN_PAUSE.name, MIN_PAUSE.default)
    if mine == theirs:
        return None
    return (
        f"These two were analysed with different settings: the minimum pause was "
        f"{show(MIN_PAUSE, mine)} for your take and {show(MIN_PAUSE, theirs)} for the "
        "reference. A silence between those two lengths counts as a pause in one and not "
        "in the other, so pause counts "
        "and phrases are not like for like. Analyse the older result again, with the "
        "settings as they are now, to bring the two into line."
    )


def compare(
    take: schemas.AnalysisBody,
    reference: schemas.AnalysisBody,
    settings: ComparisonSettings,
    *,
    take_id: str,
    reference_id: str,
    reference_title: str | None,
) -> schemas.Comparison:
    mine, theirs = Side(take), Side(reference)
    alignment = align_words(theirs.keys, mine.keys)
    summary = _alignment_summary(alignment, mine, theirs, settings)
    metrics = compare_metrics(take, reference)

    lined_up = summary.status in ("matched", "partial")
    pauses = compare_pauses(mine, theirs, alignment, settings) if lined_up else []
    phrases = compare_phrases(mine, theirs, alignment, settings) if lined_up else []

    caveats = [NOT_COMPARED, PITCH_NOT_COMPARED]
    if lined_up:
        caveats.append(WORD_TIMES_NOTE)
    caveats.append(REFERENCE_SOUNDS_NOTE)
    caveats += [f"About the reference: {warning.message}" for warning in reference.warnings]
    caveats += [f"About your take: {warning.message}" for warning in take.warnings]

    return schemas.Comparison(
        take_id=take_id,
        reference_id=reference_id,
        reference_title=reference_title,
        alignment=summary,
        metrics=metrics,
        pauses=pauses,
        phrases=phrases,
        differences=find_differences(metrics, pauses, phrases, settings),
        settings_note=settings_note(take, reference),
        caveats=caveats,
        settings=settings.to_dict(),
    )
