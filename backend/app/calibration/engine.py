"""The rules that decide when feedback moves a setting, and to what value.

Pure arithmetic: no database, no clock. Given the reports about one setting and its current
value, these functions say whether it moves. The rules are deliberately cautious:

- one report never moves anything; it takes several that agree, from more than one recording;
- one adjustment moves a setting by a small, bounded amount, and uses up the reports behind it;
- a setting never leaves its allowed range;
- moving a setting back the way it just came takes more reports than moving it on.
"""

import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.calibration.registry import (
    MIN_AGREEMENT,
    MIN_PAUSE,
    MIN_RECORDINGS,
    MIN_REPORTS,
    REVERSAL_REPORTS,
    WINDOW,
    Adaptive,
)

Confidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Report:
    """One piece of feedback that speaks for moving one setting one way."""

    feedback_id: str
    setting: str
    # +1 speaks for raising the setting, -1 for lowering it.
    direction: int
    # The measurement behind the report, e.g. the length in ms of the silence it is about.
    evidence: float | None
    recording_id: str
    created_at: datetime


def still_applies(setting: Adaptive, current: float, report: Report) -> bool:
    """Whether a report still says something about the value the setting has now.

    A report is about one recording as it was analysed at the time. Once the setting has
    moved, some earlier reports are already answered: a silence of 420 ms reported as a
    missed pause needs no further lowering once the minimum pause is 400 ms.
    """
    if setting.name == MIN_PAUSE.name:
        if report.evidence is None:
            return False
        if report.direction < 0:
            # A missed pause: still missed only if the silence is under today's minimum.
            return report.evidence < current
        # A false pause: still reported only if the silence reaches today's minimum.
        return report.evidence >= current
    return True


@dataclass(frozen=True)
class Tally:
    """Where the reports about one setting stand."""

    # The reports looked at: the most recent ones that still apply.
    reports: tuple[Report, ...]
    raise_count: int
    lower_count: int
    # The way most reports point: +1, -1, or 0 when there are none or they are tied.
    direction: int
    # Share of the reports that point that way.
    agreement: float
    # Different recordings behind the larger side.
    recordings: int
    # Reports the larger side needs before the setting can move.
    needed: int

    @property
    def agreeing(self) -> tuple[Report, ...]:
        return tuple(report for report in self.reports if report.direction == self.direction)

    @property
    def enough(self) -> bool:
        return (
            self.direction != 0
            and len(self.agreeing) >= self.needed
            and self.agreement >= MIN_AGREEMENT
            and self.recordings >= MIN_RECORDINGS
        )


def tally(
    setting: Adaptive, current: float, reports: list[Report], last_direction: int = 0
) -> Tally:
    """Counts the reports about one setting.

    `last_direction` is the way the setting moved in its latest adjustment that is still in
    effect (0 if there is none).
    """
    applicable = [report for report in reports if still_applies(setting, current, report)]
    applicable.sort(key=lambda report: (report.created_at, report.feedback_id))
    window = tuple(applicable[-WINDOW:])
    raising = sum(1 for report in window if report.direction > 0)
    lowering = len(window) - raising
    direction = 0 if raising == lowering else (1 if raising > lowering else -1)
    larger = max(raising, lowering)
    reversing = last_direction != 0 and direction == -last_direction
    return Tally(
        reports=window,
        raise_count=raising,
        lower_count=lowering,
        direction=direction,
        agreement=larger / len(window) if window else 0.0,
        recordings=len({r.recording_id for r in window if r.direction == direction}),
        needed=REVERSAL_REPORTS if reversing else MIN_REPORTS,
    )


def next_value(setting: Adaptive, current: float, direction: int, evidence: list[float]) -> float:
    """The value one adjustment in `direction` leads to. Equal to `current` at a bound.

    Most settings move by exactly one step. The minimum pause is steered by what was
    measured: it moves to the grid value that would have got the typical reported silence
    right, but never by more than `max_step` at a time.
    """
    target = current + direction * setting.step
    if setting.name == MIN_PAUSE.name and evidence:
        typical = statistics.median(evidence)
        # Lowering: the highest value that still counts the typical missed silence as a
        # pause. Raising: the lowest value that no longer counts the typical false pause.
        wanted = (math.floor(typical / setting.step) + (1 if direction > 0 else 0)) * setting.step
        nearest = current + direction * setting.step
        furthest = current + direction * setting.max_step
        target = min(max(wanted, min(nearest, furthest)), max(nearest, furthest))
    return setting.clamp(target)


def propose(setting: Adaptive, current: float, counted: Tally) -> float | None:
    """The new value for a setting, or None if it should stay where it is."""
    if not counted.enough:
        return None
    evidence = [r.evidence for r in counted.agreeing if r.evidence is not None]
    value = next_value(setting, current, counted.direction, evidence)
    return None if math.isclose(value, current) else value


def confidence(agreeing_reports: int) -> Confidence:
    """How much weight an adjustment carries, judged only by how many reports agreed."""
    if agreeing_reports >= 8:
        return "high"
    return "medium" if agreeing_reports >= 5 else "low"
