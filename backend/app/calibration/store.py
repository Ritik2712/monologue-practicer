"""The calibration as it is stored: reading the version in force, and changing it.

Versions are only ever added. Undoing an adjustment or resetting to the defaults writes a
new version too, so a version number never means two different things and every analysis
stays traceable to the values that produced it.
"""

import statistics
from dataclasses import dataclass, replace
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.calibration import engine
from app.calibration.registry import (
    ADAPTIVE,
    CORRECTION_KINDS,
    DEFAULT_VALUES,
    FIXED,
    MIN_AGREEMENT,
    MIN_PAUSE,
    MIN_RECORDINGS,
    MIN_REPORTS,
    PRIORITY_PREFIX,
    REVERSAL_REPORTS,
    WINDOW,
    Adaptive,
    show,
)
from app.coaching.settings import DEFAULT_COACHING_SETTINGS, CoachingSettings
from app.models import CalibrationState, CalibrationVersion, Feedback, utcnow
from app.pipeline.settings import DEFAULT_SETTINGS, AnalysisSettings

# How many entries of the history the calibration screen is given.
HISTORY_LIMIT = 30

RESET_REASON = "Reset to the defaults. Reports that were waiting were set aside."
DEFAULTS_REASON = "The defaults the app starts with."


@dataclass(frozen=True)
class Active:
    """The calibration in force: what new analyses and new coaching are made with."""

    version: int
    # False when the user has switched automatic adjustment off.
    adaptive: bool
    values: dict[str, float]

    def _moved(self) -> dict[str, float]:
        return {
            name: value for name, value in self.values.items() if value != ADAPTIVE[name].default
        }

    def analysis_settings(self, base: AnalysisSettings = DEFAULT_SETTINGS) -> AnalysisSettings:
        """`base` with every value that calibration has moved put in its place."""
        moved = self._moved()
        changes: dict[str, float | int] = {"calibration_version": self.version}
        if MIN_PAUSE.name in moved:
            changes[MIN_PAUSE.name] = int(moved[MIN_PAUSE.name])
        return replace(base, **changes)

    def coaching_settings(
        self, base: CoachingSettings = DEFAULT_COACHING_SETTINGS
    ) -> CoachingSettings:
        priorities = tuple(
            sorted(
                (name.removeprefix(PRIORITY_PREFIX), value)
                for name, value in self._moved().items()
                if name.startswith(PRIORITY_PREFIX)
            )
        )
        return replace(base, calibration_version=self.version, priorities=priorities)


# --- Reading -----------------------------------------------------------------------------


def _ensure(session: Session) -> None:
    """Creates version 1 (the defaults) and the on/off row if this database has neither."""
    has_version = session.execute(select(CalibrationVersion.version).limit(1)).first()
    has_state = session.get(CalibrationState, 1)
    if has_version and has_state:
        return
    now = utcnow()
    if not has_version:
        session.add(
            CalibrationVersion(
                version=1,
                created_at=now,
                cause="defaults",
                values=dict(DEFAULT_VALUES),
                reason=DEFAULTS_REASON,
            )
        )
    if not has_state:
        session.add(CalibrationState(id=1, adaptive_enabled=True, updated_at=now))
    try:
        session.commit()
    except IntegrityError:
        # The API and the worker both start here; the other one got there first.
        session.rollback()


def _latest(session: Session) -> CalibrationVersion:
    _ensure(session)
    return session.execute(
        select(CalibrationVersion).order_by(CalibrationVersion.version.desc()).limit(1)
    ).scalar_one()


def _values(row: CalibrationVersion) -> dict[str, float]:
    # A version stored before a setting became adjustable does not list it: use its default.
    stored = {name: float(value) for name, value in row.values.items() if name in ADAPTIVE}
    return {**DEFAULT_VALUES, **stored}


def active(session: Session) -> Active:
    latest = _latest(session)
    state = session.get(CalibrationState, 1)
    return Active(
        version=latest.version,
        adaptive=state.adaptive_enabled if state else True,
        values=_values(latest),
    )


def pending_reports(session: Session, setting: str) -> list[engine.Report]:
    """The reports about one setting that no adjustment has counted yet."""
    rows = session.execute(
        select(Feedback).where(Feedback.setting == setting, Feedback.used_by_version.is_(None))
    ).scalars()
    return [
        engine.Report(
            feedback_id=row.id,
            setting=setting,
            direction=row.direction,
            evidence=row.evidence,
            recording_id=row.recording_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


def last_direction(session: Session, setting: str) -> int:
    """Which way the setting moved in its latest adjustment that is still in effect."""
    row = session.execute(
        select(CalibrationVersion)
        .where(
            CalibrationVersion.cause == "auto",
            CalibrationVersion.setting == setting,
            CalibrationVersion.undone_by.is_(None),
        )
        .order_by(CalibrationVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None or row.old_value is None or row.new_value is None:
        return 0
    return 1 if row.new_value > row.old_value else -1


def tally_for(session: Session, setting: Adaptive, value: float) -> engine.Tally:
    return engine.tally(
        setting,
        value,
        pending_reports(session, setting.name),
        last_direction(session, setting.name),
    )


# --- Changing ----------------------------------------------------------------------------


def _reason(setting: Adaptive, old: float, new: float, counted: engine.Tally) -> str:
    agreeing = counted.agreeing
    count = len(agreeing)
    recordings = f"from {counted.recordings} recordings"
    moved = f"from {show(setting, old)} to {show(setting, new)}"
    up = new > old

    if setting.name == MIN_PAUSE.name:
        said = "that a detected pause was not a pause" if up else "of a pause that was missed"
        typical = statistics.median(r.evidence for r in agreeing if r.evidence is not None)
        text = (
            f"Minimum pause {'raised' if up else 'lowered'} {moved} after {count} reports "
            f"{said}, {recordings}. The silences reported were around {typical:.0f} ms long."
        )
    else:
        about = CORRECTION_KINDS.get(setting.name.removeprefix(PRIORITY_PREFIX), "this")
        text = (
            f"Corrections about {about} moved {'back up' if up else 'down'} the list "
            f"(priority {moved}) after {count} ratings of "
            f"“{'useful' if up else 'not useful'}”, {recordings}."
        )
    others = len(counted.reports) - count
    if others:
        text += f" {others} {'report' if others == 1 else 'reports'} pointed the other way."
    return text


def evaluate(session: Session, now: datetime) -> list[CalibrationVersion]:
    """Moves every setting whose reports are enough. Returns the versions this created.

    Called after any change to the stored feedback. Does nothing while automatic
    adjustment is switched off.
    """
    current = active(session)
    if not current.adaptive:
        return []
    values = dict(current.values)
    created: list[CalibrationVersion] = []
    for name, setting in ADAPTIVE.items():
        counted = tally_for(session, setting, values[name])
        new_value = engine.propose(setting, values[name], counted)
        if new_value is None:
            continue
        row = CalibrationVersion(
            created_at=now,
            cause="auto",
            values={**values, name: new_value},
            setting=name,
            old_value=values[name],
            new_value=new_value,
            reason=_reason(setting, values[name], new_value, counted),
            report_count=len(counted.reports),
            agreeing_count=len(counted.agreeing),
            recording_count=counted.recordings,
        )
        session.add(row)
        session.flush()
        # Every report waiting on this setting is now used up, whichever way it pointed:
        # the next adjustment has to be earned by fresh reports made under the new value.
        session.execute(
            update(Feedback)
            .where(Feedback.setting == name, Feedback.used_by_version.is_(None))
            .values(used_by_version=row.version)
        )
        values[name] = new_value
        created.append(row)
    session.commit()
    return created


def _undoable(session: Session) -> CalibrationVersion | None:
    return session.execute(
        select(CalibrationVersion)
        .where(CalibrationVersion.cause == "auto", CalibrationVersion.undone_by.is_(None))
        .order_by(CalibrationVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()


def undo_last(session: Session, now: datetime) -> CalibrationVersion | None:
    """Puts back the value the most recent adjustment replaced. None if there is none.

    The reports behind the undone adjustment stay used up, so the same reports can never
    bring it straight back.
    """
    target = _undoable(session)
    if target is None or target.setting not in ADAPTIVE:
        return None
    setting = ADAPTIVE[target.setting]
    values = active(session).values
    row = CalibrationVersion(
        created_at=now,
        cause="undo",
        values={**values, setting.name: target.old_value},
        setting=setting.name,
        old_value=values[setting.name],
        new_value=target.old_value,
        reason=(
            f"Undone by you: {setting.label[0].lower()}{setting.label[1:]} put back from "
            f"{show(setting, values[setting.name])} to {show(setting, target.old_value)} "
            f"(the adjustment of version {target.version})."
        ),
    )
    session.add(row)
    session.flush()
    target.undone_by = row.version
    session.commit()
    return row


def reset(session: Session, now: datetime) -> CalibrationVersion | None:
    """Back to the defaults, with the report counts starting again. None if already there."""
    current = active(session)
    waiting = session.execute(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.setting.is_not(None), Feedback.used_by_version.is_(None))
    ).scalar_one()
    if current.values == DEFAULT_VALUES and not waiting and _undoable(session) is None:
        return None
    row = CalibrationVersion(
        created_at=now, cause="reset", values=dict(DEFAULT_VALUES), reason=RESET_REASON
    )
    session.add(row)
    session.flush()
    session.execute(
        update(CalibrationVersion)
        .where(CalibrationVersion.cause == "auto", CalibrationVersion.undone_by.is_(None))
        .values(undone_by=row.version)
    )
    session.execute(
        update(Feedback)
        .where(Feedback.setting.is_not(None), Feedback.used_by_version.is_(None))
        .values(used_by_version=row.version)
    )
    session.commit()
    return row


def set_adaptive(session: Session, enabled: bool, now: datetime) -> list[CalibrationVersion]:
    """Switches automatic adjustment on or off. Returns any adjustments switching on made."""
    _ensure(session)
    state = session.get(CalibrationState, 1)
    state.adaptive_enabled = enabled
    state.updated_at = now
    session.commit()
    return evaluate(session, now) if enabled else []


# --- Describing --------------------------------------------------------------------------


def to_change(row: CalibrationVersion) -> schemas.CalibrationChange:
    setting = ADAPTIVE.get(row.setting or "")
    return schemas.CalibrationChange(
        version=row.version,
        created_at=row.created_at,
        cause=row.cause,
        setting=row.setting,
        label=setting.label if setting else None,
        unit=setting.unit if setting else None,
        old_value=row.old_value,
        new_value=row.new_value,
        reason=row.reason or "",
        report_count=row.report_count,
        agreeing_count=row.agreeing_count,
        recording_count=row.recording_count,
        confidence=engine.confidence(row.agreeing_count) if row.cause == "auto" else None,
        undone=row.undone_by is not None,
    )


def waiting_text(
    setting: Adaptive, value: float, counted: engine.Tally, adaptive: bool = True
) -> str:
    """Where the reports about one setting stand, in a sentence."""
    if not counted.reports:
        return "No reports are waiting."
    larger = max(counted.raise_count, counted.lower_count)
    smaller = min(counted.raise_count, counted.lower_count)
    if counted.direction == 0:
        return (
            f"{counted.raise_count} {_reports(counted.raise_count)} towards raising it and "
            f"{counted.lower_count} towards lowering it: they cancel out, so it stays."
        )
    way = "raising" if counted.direction > 0 else "lowering"
    text = f"{larger} of the {counted.needed} reports needed for {way} it"
    if counted.recordings < MIN_RECORDINGS:
        text += f", from {counted.recordings} of the {MIN_RECORDINGS} recordings needed"
    text += "."
    if smaller:
        text += f" {smaller} {_reports(smaller)} the other way."
    if counted.enough:
        if engine.propose(setting, value, counted) is None:
            bound = "highest" if counted.direction > 0 else "lowest"
            return f"{text} It is already at its {bound} allowed value, so it stays."
        if not adaptive:
            return f"{text} It would move if automatic adjustment were switched on."
    elif larger >= counted.needed and counted.agreement < MIN_AGREEMENT:
        text += " The reports disagree too much to act on."
    return text


def _reports(count: int) -> str:
    return "report points" if count == 1 else "reports point"


def describe(session: Session) -> schemas.Calibration:
    """Everything the calibration screen shows."""
    current = active(session)
    rows = (
        session.execute(select(CalibrationVersion).order_by(CalibrationVersion.version.desc()))
        .scalars()
        .all()
    )
    in_effect = [row for row in rows if row.cause == "auto" and row.undone_by is None]

    settings: list[schemas.CalibratedSetting] = []
    for name, setting in ADAPTIVE.items():
        value = current.values[name]
        counted = tally_for(session, setting, value)
        supporting = sum(row.agreeing_count for row in in_effect if row.setting == name)
        changed = value != setting.default
        where = (
            f"Changed from its default of {show(setting, setting.default)}."
            if changed
            else "At its default."
        )
        settings.append(
            schemas.CalibratedSetting(
                name=name,
                group=setting.group,
                label=setting.label,
                description=setting.description,
                unit=setting.unit,
                digits=setting.digits,
                value=value,
                default=setting.default,
                minimum=setting.minimum,
                maximum=setting.maximum,
                step=setting.step,
                changed=changed,
                pending=schemas.PendingReports(
                    raise_count=counted.raise_count,
                    lower_count=counted.lower_count,
                    recordings=counted.recordings,
                    needed=counted.needed,
                ),
                supporting_reports=supporting,
                confidence=engine.confidence(supporting) if changed else "none",
                status=f"{where} {waiting_text(setting, value, counted, current.adaptive)}",
            )
        )

    feedback_count = session.execute(select(func.count()).select_from(Feedback)).scalar_one()
    pending = session.execute(
        select(func.count())
        .select_from(Feedback)
        .where(Feedback.setting.is_not(None), Feedback.used_by_version.is_(None))
    ).scalar_one()
    moved = [setting for setting in settings if setting.changed]
    if not current.adaptive:
        summary = (
            "Automatic adjustment is switched off. Feedback is still saved, and the settings "
            "stay exactly as they are until you switch it back on."
        )
    elif not moved:
        summary = (
            "Still calibrating: every setting is at its default. A setting moves only after "
            f"{MIN_REPORTS} reports that agree, from at least {MIN_RECORDINGS} different "
            f"recordings. Reports waiting: {pending}."
        )
    else:
        supporting = sum(setting.supporting_reports for setting in moved)
        summary = (
            f"{len(moved)} {'setting has' if len(moved) == 1 else 'settings have'} moved from "
            f"the defaults, on the strength of {supporting} reports. Each is listed below "
            "with its reason. That is a small sample: treat the values as provisional."
        )

    return schemas.Calibration(
        version=current.version,
        adaptive=current.adaptive,
        state="adjusted" if moved else "calibrating",
        summary=summary,
        feedback_count=feedback_count,
        pending_report_count=pending,
        settings=settings,
        fixed=[
            schemas.FixedSetting(name=name, label=label, value=value, unit=unit)
            for name, label, value, unit in FIXED
        ],
        changes=[to_change(row) for row in rows[:HISTORY_LIMIT]],
        can_undo=bool(in_effect),
        rules=schemas.CalibrationRules(
            min_reports=MIN_REPORTS,
            min_recordings=MIN_RECORDINGS,
            min_agreement=MIN_AGREEMENT,
            window=WINDOW,
            reversal_reports=REVERSAL_REPORTS,
        ),
    )
