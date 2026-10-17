"""Feedback the user gives on an analysis: saving it, and working out what each piece does.

A piece of feedback does exactly one of three things:

- label a pause as intentional or accidental, which changes how the coaching reads it;
- report a mistake in the analysis or rate a correction, which counts as one report
  towards moving one adjustable setting (`app.calibration` decides when it moves);
- go on record and change nothing by itself.

Which of the three, and which setting, is decided here from what was measured, by ordinary
code. No feedback ever changes a stored measurement.

Feedback is taken on reference recordings too, with two differences. A reference has no
coaching, so its pauses cannot be labelled and there is nothing to rate. And its reports
count towards a setting only alongside a report from one of the user's own takes
(`app.calibration.engine` holds that rule).
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas, stretches, wpm_review
from app.calibration import engine, store
from app.calibration.registry import ADAPTIVE, CORRECTION_KINDS, MIN_PAUSE, priority_name
from app.job_queue import REFERENCE, new_id
from app.models import Analysis, CalibrationVersion, Feedback
from app.pipeline.settings import DEFAULT_SETTINGS, AnalysisSettings

# A short silence this close to the marked time is taken to be the one the user means.
NEAR_SECONDS = 0.5

PAUSE_LABELS = {"pause_intentional": "intentional", "pause_accidental": "accidental"}
PAUSE_CATEGORIES = (*PAUSE_LABELS, "pause_false", "split_wrong")
WPM_CATEGORIES = {"wpm_too_high": "high", "wpm_too_low": "low"}
COACHING_CATEGORIES = {"coaching_useful": 1, "coaching_not_useful": -1}


class FeedbackError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Classified:
    """What a piece of feedback is about, what was measured there, and what it speaks for."""

    target_kind: str
    target_id: str | None
    # One row is kept per slot: new feedback on the same thing replaces the old.
    slot: str
    features: dict = field(default_factory=dict)
    setting: str | None = None
    direction: int = 0
    evidence: float | None = None


def _unknown(what: str) -> FeedbackError:
    return FeedbackError(404, "unknown_target", f"This recording has no such {what}.")


def classify(
    request: schemas.FeedbackRequest,
    body: schemas.AnalysisBody,
    coaching: schemas.Coaching | None,
) -> Classified:
    """Decides what one piece of feedback does. Raises FeedbackError if it makes no sense."""
    category, target_id = request.category, request.target_id
    # The value the recording was analysed with: what the feedback is a comment on.
    used = {MIN_PAUSE.name: body.settings.get(MIN_PAUSE.name, DEFAULT_SETTINGS.min_pause_ms)}

    if category in PAUSE_CATEGORIES:
        pause = next((p for p in body.pauses if p.id == target_id), None)
        if pause is None:
            raise _unknown("pause")
        length_ms = round(pause.duration_seconds * 1000)
        features = {"pause_ms": length_ms, **used}

        def about_pause(**vote) -> Classified:
            return Classified("pause", pause.id, f"pause:{pause.id}", features, **vote)

        if category in PAUSE_LABELS:
            # A label says what the pause meant. The pause itself is measured and stays.
            return about_pause()
        if category == "split_wrong" and stretches.has_delivery_pace(body):
            # In a result whose phrases can hold a pause, only a pause as long as the
            # segment break splits one, and that length is not one feedback may move.
            if pause.inside_segment:
                raise FeedbackError(
                    422,
                    "not_a_split",
                    "This pause is inside a phrase and did not split it. If you were still "
                    "speaking there, mark it as “Not a pause”.",
                )
            features["no_vote"] = "fixed_break"
            features["segment_break_ms"] = AnalysisSettings.from_dict(
                body.settings
            ).segment_break_ms
            return about_pause()
        if length_ms < MIN_PAUSE.maximum:
            # Short enough that a higher minimum pause would no longer report it.
            return about_pause(setting=MIN_PAUSE.name, direction=1, evidence=float(length_ms))
        # Too long for any minimum pause to explain. If the user was speaking, the detector
        # did not hear it, and no setting that feedback may move would have made it.
        features["no_vote"] = "missed_speech" if category == "pause_false" else "long_pause"
        return about_pause()

    if category == "pause_missed":
        segment = next((s for s in body.segments if s.id == target_id), None)
        if segment is None:
            raise _unknown("phrase")
        at = request.at_seconds
        inside = segment.start_seconds - NEAR_SECONDS, segment.end_seconds + NEAR_SECONDS
        if at is not None and not inside[0] <= at <= inside[1]:
            raise FeedbackError(422, "outside_target", "That time is not inside this phrase.")
        features = dict(used)

        def about_segment(spot: str, **vote) -> Classified:
            # The slot names the spot, so one silence can only ever be reported once.
            return Classified(
                "segment", segment.id, f"missed:{segment.id}@{spot}", features, **vote
            )

        if at is None:
            features["no_vote"] = "no_position"
            return about_segment("?")
        if body.short_silences is None:
            features["no_vote"] = "not_recorded"
            return about_segment(f"~{round(at)}")
        near = [
            silence
            for silence in body.short_silences
            if silence.segment_id == segment.id
            and silence.start_seconds - NEAR_SECONDS <= at <= silence.end_seconds + NEAR_SECONDS
        ]
        if not near:
            # The detector heard speech straight through: nothing a minimum pause could catch.
            features |= {"silence_ms": None, "no_vote": "no_silence"}
            return about_segment(f"~{round(at)}")
        # Of the silences close by, the one whose middle is nearest the marked time.
        silence = min(near, key=lambda item: abs((item.start_seconds + item.end_seconds) / 2 - at))
        silence_ms = round(silence.duration_seconds * 1000)
        spot = f"{silence.start_seconds:.2f}"
        features |= {"silence_ms": silence_ms, "silence_start_seconds": silence.start_seconds}
        if silence_ms < MIN_PAUSE.minimum:
            features["no_vote"] = "too_short"
            return about_segment(spot)
        return about_segment(spot, setting=MIN_PAUSE.name, direction=-1, evidence=float(silence_ms))

    if category in WPM_CATEGORIES:
        if target_id is None:
            metrics = body.metrics
            # `wpm` is the figure the screen shows first, which is what was reported on.
            features = {
                "words": metrics.total_word_count.value,
                "seconds": metrics.speech_active_seconds.value,
                "wpm": stretches.recording_delivery_wpm(body).value,
                "speaking_wpm": metrics.speech_active_wpm.value,
            }
            return Classified("recording", None, "wpm:recording", features)
        segment = next((s for s in body.segments if s.id == target_id), None)
        if segment is None:
            raise _unknown("phrase")
        features = {
            "words": segment.word_count,
            "seconds": segment.speech_active_seconds,
            "wpm": stretches.delivery_wpm_of(segment),
            "speaking_wpm": segment.segment_wpm,
            "pause_seconds": segment.pause_seconds,
        }
        return Classified("segment", segment.id, f"wpm:{segment.id}", features)

    if category == "transcript_wrong":
        segment = next((s for s in body.segments if s.id == target_id), None)
        if segment is None:
            raise _unknown("phrase")
        return Classified(
            "segment", segment.id, f"transcript:{segment.id}", {"words": segment.word_count}
        )

    # A rating of one correction in the coaching.
    correction = next(
        (c for c in (coaching.corrections if coaching else []) if c.finding_id == target_id), None
    )
    finding = next((f for f in (coaching.findings if coaching else []) if f.id == target_id), None)
    if coaching is None or correction is None or finding is None:
        raise _unknown("correction")
    features = {"finding_kind": finding.kind, "source": coaching.source, "title": correction.title}
    slot = f"coaching:{finding.id}"
    if finding.kind not in CORRECTION_KINDS:
        return Classified("correction", finding.id, slot, features)
    return Classified(
        "correction",
        finding.id,
        slot,
        features,
        setting=priority_name(finding.kind),
        direction=COACHING_CATEGORIES[category],
    )


# --- Saving ------------------------------------------------------------------------------


def _note(text: str | None) -> str | None:
    cleaned = " ".join((text or "").split())
    return cleaned or None


def save(
    session: Session, analysis: Analysis, request: schemas.FeedbackRequest, now: datetime
) -> Feedback:
    """Stores one piece of feedback, replacing any earlier feedback on the same thing."""
    if analysis.role == REFERENCE and (
        request.category in PAUSE_LABELS or request.category in COACHING_CATEGORIES
    ):
        raise FeedbackError(
            409,
            "not_for_reference",
            "A reference recording has no coaching, so its pauses are not labelled and there "
            "is nothing to rate. Mistakes in how it was measured can be reported.",
        )
    body = schemas.AnalysisBody.model_validate(analysis.result)
    coaching = schemas.Coaching.model_validate(analysis.coaching) if analysis.coaching else None
    found = classify(request, body, coaching)

    existing = session.execute(
        select(Feedback).where(Feedback.analysis_id == analysis.id, Feedback.slot == found.slot)
    ).scalar_one_or_none()
    if existing is not None and existing.category == request.category:
        # The same thing said again: only the note can have changed. Leaving the note out
        # keeps the one that is there.
        if request.note is not None:
            existing.note = _note(request.note)
            existing.updated_at = now
            session.commit()
        return existing

    used_by = None
    if existing is not None:
        # Rewording a report that an adjustment already counted must not let it count twice.
        if (existing.setting, existing.direction) == (found.setting, found.direction):
            used_by = existing.used_by_version
        session.delete(existing)
        session.flush()
    row = Feedback(
        id=new_id(),
        analysis_id=analysis.id,
        recording_id=analysis.root_id or analysis.id,
        slot=found.slot,
        category=request.category,
        target_kind=found.target_kind,
        target_id=found.target_id,
        at_seconds=request.at_seconds if request.category == "pause_missed" else None,
        note=_note(request.note),
        calibration_version=analysis.calibration_version,
        features=found.features,
        setting=found.setting,
        direction=found.direction,
        evidence=found.evidence,
        used_by_version=used_by,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    return row


def record_correction(
    session: Session,
    analysis: Analysis,
    segment: schemas.SpeechSegment,
    new_words: int,
    revision: int,
    now: datetime,
) -> None:
    """Puts a transcript correction on record as feedback on the analysis it corrected."""
    slot = f"transcript:{segment.id}"
    existing = session.execute(
        select(Feedback).where(Feedback.analysis_id == analysis.id, Feedback.slot == slot)
    ).scalar_one_or_none()
    if existing is not None:
        session.delete(existing)
        session.flush()
    session.add(
        Feedback(
            id=new_id(),
            analysis_id=analysis.id,
            recording_id=analysis.root_id or analysis.id,
            slot=slot,
            category="transcript_wrong",
            target_kind="segment",
            target_id=segment.id,
            calibration_version=analysis.calibration_version,
            features={
                "words": segment.word_count,
                "corrected_words": new_words,
                "revision": revision,
            },
            created_at=now,
            updated_at=now,
        )
    )


def delete(session: Session, feedback_id: str) -> str | None:
    """Removes one piece of feedback. Returns the analysis it was on, or None if not found.

    An adjustment it already counted towards stays as it is; that is what undo is for.
    """
    row = session.get(Feedback, feedback_id)
    if row is None:
        return None
    analysis_id = row.analysis_id
    session.delete(row)
    session.commit()
    return analysis_id


def pause_labels(session: Session, analysis_id: str) -> dict[str, str]:
    """The user's labels on this analysis's pauses: pause ID -> "intentional" or "accidental"."""
    rows = session.execute(
        select(Feedback.target_id, Feedback.category).where(
            Feedback.analysis_id == analysis_id, Feedback.category.in_(tuple(PAUSE_LABELS))
        )
    ).all()
    return {target_id: PAUSE_LABELS[category] for target_id, category in rows if target_id}


def copy_pause_labels(session: Session, source_id: str, target: Analysis, now: datetime) -> None:
    """Carries pause labels over to a revision that has the very same pauses.

    Only labels are copied. Reports stay with the analysis they were made on, so no report
    is ever counted twice.
    """
    rows = session.execute(
        select(Feedback).where(
            Feedback.analysis_id == source_id, Feedback.category.in_(tuple(PAUSE_LABELS))
        )
    ).scalars()
    for row in rows:
        session.add(
            Feedback(
                id=new_id(),
                analysis_id=target.id,
                recording_id=target.root_id or target.id,
                slot=row.slot,
                category=row.category,
                target_kind=row.target_kind,
                target_id=row.target_id,
                note=row.note,
                calibration_version=target.calibration_version,
                features=dict(row.features),
                created_at=now,
                updated_at=now,
            )
        )


# --- Describing --------------------------------------------------------------------------

# What a label makes of a pause, to finish "treats the pause as …".
LABEL_READINGS = {"pause_intentional": "deliberate", "pause_accidental": "a slip"}
NO_VOTE_MESSAGES = {
    "long_pause": (
        "Saved. A silence of {pause_seconds} is a pause at any setting, and a pause always "
        "ends a phrase, so this changes no setting."
    ),
    "fixed_break": (
        "Saved. A pause of {break_seconds} or more ends a phrase, and this one lasted "
        "{pause_seconds}. That length is fixed and feedback does not move it, so this "
        "changes no setting."
    ),
    "missed_speech": (
        "Saved. The detector heard no speech for {pause_seconds} there. No minimum pause "
        "explains a silence that long, so this changes no setting. {unheard}"
    ),
    "no_silence": (
        "Saved. The detector heard speech straight through at that point, without a gap of "
        "even a tenth of a second, so no pause setting could have caught it. This changes no "
        "setting. A breath or a noise in the gap can sound like speech to the detector."
    ),
    "too_short": (
        "Saved. The silence there lasted {silence_ms} ms. Nothing shorter than "
        f"{MIN_PAUSE.minimum:.0f} ms is ever counted as a pause, so this changes no setting."
    ),
    "no_position": (
        "Saved. Without a position inside the phrase it cannot be checked against what the "
        "detector heard, so it does not count towards a setting."
    ),
    "not_recorded": (
        "Saved. This result was made before short silences were kept, so the report cannot "
        "be checked against what the detector heard. Analyse the recording again to use it."
    ),
}


# Why the detector may have heard nothing where there was speech, by whose recording it is.
UNHEARD = {
    False: "If you were speaking, it was too quiet for the detector to pick up.",
    True: (
        "If someone was speaking, it was too quiet, or too far under music or other sound, "
        "for the detector to pick up."
    ),
}


def _lower(label: str) -> str:
    return f"the {label[0].lower()}{label[1:]}"


def _message(
    row: Feedback,
    current: store.Active,
    versions: dict[int, CalibrationVersion],
    tallies: dict[str, engine.Tally],
    labels_used: dict[str, str],
    on_reference: bool = False,
) -> tuple[str, str]:
    """(effect, one sentence saying what this feedback does)."""
    if row.category in PAUSE_LABELS:
        reading = LABEL_READINGS[row.category]
        taken_in = labels_used.get(row.target_id or "") == PAUSE_LABELS[row.category]
        return (
            "label",
            "Saved as a label. "
            + (
                f"The coaching on this result already treats the pause as {reading}."
                if taken_in
                else f"The next coaching written for this result treats the pause as {reading}."
            )
            + " The pause stays in every pause figure.",
        )

    if row.setting in ADAPTIVE:
        setting = ADAPTIVE[row.setting]
        way = "raising" if row.direction > 0 else "lowering"
        if row.used_by_version is not None:
            version = versions.get(row.used_by_version)
            if version is None or version.cause == "reset":
                return "used", "Set aside when the settings were reset to the defaults."
            if version.undone_by is not None:
                return (
                    "used",
                    (
                        f"Counted in the adjustment of version {version.version}, which is no "
                        "longer in effect. It is not counted again."
                    ),
                )
            return "used", f"Counted in version {version.version}. {version.reason}"
        counted = tallies[setting.name]
        if row.id not in {report.feedback_id for report in counted.reports}:
            return (
                "report",
                (
                    f"Saved. {_lower(setting.label).capitalize()} has changed since this result "
                    "was made, and this report is about the old value, so it no longer counts."
                ),
            )
        if not current.adaptive:
            return (
                "report",
                (
                    f"Saved as a report for {way} {_lower(setting.label)}. Automatic adjustment "
                    "is switched off, so nothing changes."
                ),
            )
        value = current.values[setting.name]
        return (
            "report",
            (
                f"Counts towards {way} {_lower(setting.label)}. "
                f"{store.waiting_text(setting, value, counted)}"
            ),
        )

    reason = row.features.get("no_vote")
    if reason in NO_VOTE_MESSAGES:
        return "recorded", NO_VOTE_MESSAGES[reason].format(
            pause_seconds=f"{(row.features.get('pause_ms') or 0) / 1000:.1f} s",
            break_seconds=f"{(row.features.get('segment_break_ms') or 0) / 1000:.1f} s",
            silence_ms=row.features.get("silence_ms"),
            unheard=UNHEARD[on_reference],
        )
    if row.category in WPM_CATEGORIES:
        return (
            "recorded",
            (
                "Saved. No figure is changed by this: WPM changes only when the words or the "
                "speaking time are corrected. The review shows what went into it."
            ),
        )
    if row.category == "transcript_wrong":
        if "revision" in row.features:
            return (
                "recorded",
                (
                    f"You corrected this phrase. Revision {row.features['revision']} uses your "
                    "words; this result is unchanged."
                ),
            )
        said = "as they are said in the recording" if on_reference else "as you said them"
        return (
            "recorded",
            f"Saved. Nothing is worked out again until you supply the words {said}.",
        )
    return "recorded", "Saved."


def list_items(session: Session, analysis: Analysis) -> list[schemas.FeedbackItem]:
    """Every piece of feedback on one analysis, oldest first, with what each one does."""
    rows = (
        session.execute(
            select(Feedback)
            .where(Feedback.analysis_id == analysis.id)
            .order_by(Feedback.created_at, Feedback.id)
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    current = store.active(session)
    used = {row.used_by_version for row in rows if row.used_by_version is not None}
    versions = {
        version.version: version
        for version in session.execute(
            select(CalibrationVersion).where(CalibrationVersion.version.in_(used))
        ).scalars()
    }
    tallies = {
        name: store.tally_for(session, ADAPTIVE[name], current.values[name])
        for name in {row.setting for row in rows if row.setting in ADAPTIVE}
    }
    body: schemas.AnalysisBody | None = None
    labels_used = (analysis.coaching or {}).get("labelsUsed") or {}
    on_reference = analysis.role == REFERENCE

    items = []
    for row in rows:
        effect, message = _message(row, current, versions, tallies, labels_used, on_reference)
        review = None
        if row.category in WPM_CATEGORIES:
            body = body or schemas.AnalysisBody.model_validate(analysis.result)
            review = wpm_review.review(
                body, row.target_id, WPM_CATEGORIES[row.category], on_reference
            )
        items.append(
            schemas.FeedbackItem(
                id=row.id,
                analysis_id=row.analysis_id,
                category=row.category,
                target_kind=row.target_kind,
                target_id=row.target_id,
                at_seconds=row.at_seconds,
                note=row.note,
                created_at=row.created_at,
                calibration_version=row.calibration_version,
                features=row.features,
                effect=effect,
                setting=row.setting,
                direction=row.direction,
                message=message,
                review=review,
            )
        )
    return items
