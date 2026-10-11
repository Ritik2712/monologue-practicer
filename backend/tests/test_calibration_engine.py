"""The rules that decide when feedback moves a setting. Pure arithmetic, no database."""

from datetime import UTC, datetime, timedelta

import pytest

from app.calibration import engine
from app.calibration.registry import ADAPTIVE, MIN_PAUSE, REVERSAL_REPORTS, WINDOW

START = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)
PITCH_PRIORITY = ADAPTIVE["priority_pitch_variation"]


def report(
    number: int,
    direction: int,
    evidence: float | None = None,
    *,
    recording: str = "a",
    setting=MIN_PAUSE,
    own_take: bool = True,
) -> engine.Report:
    return engine.Report(
        feedback_id=f"fb-{number}",
        setting=setting.name,
        direction=direction,
        evidence=evidence,
        recording_id=recording,
        created_at=START + timedelta(minutes=number),
        own_take=own_take,
    )


def missed(
    number: int, gap_ms: float, recording: str = "a", own_take: bool = True
) -> engine.Report:
    """ "A pause was missed": the detector heard a silence of `gap_ms`, under the minimum."""
    return report(number, -1, gap_ms, recording=recording, own_take=own_take)


def false_pause(number: int, pause_ms: float, recording: str = "a") -> engine.Report:
    """ "That was not a pause": a detected pause of `pause_ms`."""
    return report(number, 1, pause_ms, recording=recording)


def decide(reports, current=500.0, setting=MIN_PAUSE, last_direction=0) -> float | None:
    counted = engine.tally(setting, current, reports, last_direction)
    return engine.propose(setting, current, counted)


# --- How much feedback it takes ----------------------------------------------------------


@pytest.mark.parametrize("count", [1, 2])
def test_one_or_two_reports_never_move_a_setting(count):
    reports = [missed(i, 400, recording=f"rec-{i}") for i in range(count)]

    assert decide(reports) is None


def test_three_reports_from_a_single_recording_are_not_enough():
    """One odd recording must not retune the app for every later one."""
    reports = [missed(i, 400, recording="same") for i in range(3)]

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert (counted.lower_count, counted.recordings, counted.enough) == (3, 1, False)
    assert decide(reports) is None


def test_three_agreeing_reports_from_two_recordings_move_it():
    reports = [missed(0, 400, "a"), missed(1, 400, "a"), missed(2, 400, "b")]

    assert decide(reports) == 400


def test_reports_on_reference_recordings_alone_move_nothing():
    """A film clip is a different kind of sound from the user's own microphone. However
    many reports it gathers, the settings wait for one of the user's own takes to agree."""
    reports = [missed(i, 400, f"reference-{i % 2}", own_take=False) for i in range(6)]

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert (counted.lower_count, counted.recordings, counted.take_reports) == (6, 2, 0)
    assert counted.enough is False
    assert decide(reports) is None


def test_one_report_on_an_own_take_lets_the_reports_on_references_count():
    reports = [
        missed(0, 400, "reference", own_take=False),
        missed(1, 420, "reference", own_take=False),
        missed(2, 410, "my-take"),
    ]

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert (counted.take_reports, counted.enough) == (1, True)
    assert decide(reports) == 400


def test_a_take_report_pointing_the_other_way_does_not_stand_in_for_one_that_agrees():
    reports = [missed(i, 400, f"reference-{i % 2}", own_take=False) for i in range(4)]
    reports.append(false_pause(4, 600, "my-take"))

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert (counted.direction, counted.take_reports, counted.enough) == (-1, 0, False)


def test_reports_that_disagree_too_much_change_nothing():
    """Three say lower and two say raise: 60% agreement, under the 75% that is needed."""
    reports = [missed(i, 400, f"r{i}") for i in range(3)]
    reports += [false_pause(3, 600, "x"), false_pause(4, 600, "y")]

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert counted.agreement == pytest.approx(0.6)
    assert decide(reports) is None


def test_one_dissenting_report_in_four_is_outvoted():
    reports = [missed(i, 400, f"r{i}") for i in range(3)] + [false_pause(3, 600, "x")]

    assert decide(reports) == 400


def test_a_tie_points_nowhere():
    reports = [missed(0, 400, "a"), missed(1, 400, "b")]
    reports += [false_pause(2, 600, "c"), false_pause(3, 600, "d")]

    counted = engine.tally(MIN_PAUSE, 500, reports)

    assert (counted.direction, counted.enough) == (0, False)


def test_only_the_most_recent_reports_are_looked_at():
    """Old opinions fade: twelve early "raise" reports do not outweigh ten recent "lower" ones."""
    old = [false_pause(i, 600, f"old-{i}") for i in range(12)]
    recent = [missed(100 + i, 400, f"new-{i}") for i in range(WINDOW)]

    counted = engine.tally(MIN_PAUSE, 500, old + recent)

    assert (counted.raise_count, counted.lower_count) == (0, WINDOW)


# --- How far it moves --------------------------------------------------------------------


@pytest.mark.parametrize(
    "gaps, expected",
    [
        # The typical missed silence was 420 ms: 400 ms is the highest value that catches it.
        ([380, 420, 450], 400),
        # Just under the minimum: one step of 50 ms is enough.
        ([470, 480, 490], 450),
        # Far under it: still no more than 100 ms in one adjustment.
        ([260, 300, 320], 400),
        # A silence exactly on the grid counts as a pause at that value.
        ([400, 400, 400], 400),
    ],
)
def test_lowering_the_minimum_pause_is_steered_by_the_silences_reported(gaps, expected):
    reports = [missed(i, gap, f"r{i}") for i, gap in enumerate(gaps)]

    assert decide(reports) == expected


@pytest.mark.parametrize(
    "pauses, expected",
    [
        # The typical false pause was 560 ms: 600 ms is the lowest value that drops it.
        ([520, 560, 610], 600),
        ([510, 520, 530], 550),
        ([700, 720, 750], 600),
        # A pause exactly on the grid is still a pause there, so the value goes past it.
        ([550, 550, 550], 600),
    ],
)
def test_raising_the_minimum_pause_is_steered_by_the_pauses_reported(pauses, expected):
    reports = [false_pause(i, pause, f"r{i}") for i, pause in enumerate(pauses)]

    assert decide(reports) == expected


def test_no_adjustment_is_larger_than_the_allowed_step():
    for setting in ADAPTIVE.values():
        for direction in (-1, 1):
            moved = engine.next_value(setting, setting.default, direction, [1.0, 5000.0])
            assert abs(moved - setting.default) <= setting.max_step + 1e-9, setting.name


def test_a_setting_never_leaves_its_allowed_range():
    """Fed nothing but agreeing reports for ever, each setting stops at its bound."""
    for setting in ADAPTIVE.values():
        for direction, bound in ((-1, setting.minimum), (1, setting.maximum)):
            value = setting.default
            for _ in range(50):
                value = engine.next_value(
                    setting, value, direction, [0.0 if direction < 0 else 1e6]
                )
                assert setting.minimum <= value <= setting.maximum, setting.name
            assert value == bound, setting.name


def test_at_its_bound_a_setting_stays_put_however_many_reports_arrive():
    reports = [missed(i, 200, f"r{i}") for i in range(6)]

    assert decide(reports, current=MIN_PAUSE.minimum) is None


def test_values_stay_on_the_grid_without_drifting():
    value = 1.0
    for expected in (0.8, 0.6, 0.4, 0.4):
        value = engine.next_value(PITCH_PRIORITY, value, -1, [])
        assert value == expected


# --- Which reports still count -----------------------------------------------------------


def test_a_missed_pause_that_would_now_be_caught_no_longer_counts():
    """The minimum pause is 400 ms now. A silence of 420 ms needs no further lowering."""
    answered, standing = missed(0, 420), missed(1, 380)

    assert not engine.still_applies(MIN_PAUSE, 400, answered)
    assert engine.still_applies(MIN_PAUSE, 400, standing)


def test_a_false_pause_that_would_no_longer_be_reported_no_longer_counts():
    answered, standing = false_pause(0, 560), false_pause(1, 640)

    assert not engine.still_applies(MIN_PAUSE, 600, answered)
    assert engine.still_applies(MIN_PAUSE, 600, standing)


def test_a_rating_of_a_correction_always_counts_whatever_the_priority_is_now():
    rating = report(0, -1, setting=PITCH_PRIORITY)

    assert engine.still_applies(PITCH_PRIORITY, 1.0, rating)
    assert engine.still_applies(PITCH_PRIORITY, 0.6, rating)


def test_a_report_without_a_measured_silence_cannot_move_the_minimum_pause():
    assert not engine.still_applies(MIN_PAUSE, 500, report(0, -1, None))


def test_reports_answered_by_an_earlier_change_cannot_trigger_another():
    """All three silences are 420 ms or more, so at 400 ms there is nothing left to fix."""
    reports = [missed(i, gap, f"r{i}") for i, gap in enumerate([420, 440, 460])]

    assert decide(reports, current=500) == 400
    assert decide(reports, current=400) is None


# --- Not flip-flopping -------------------------------------------------------------------


def test_moving_a_setting_back_the_way_it_came_takes_more_reports():
    """It was just lowered. Three reports to raise it again are not enough; five are."""
    three = [false_pause(i, 420, f"r{i}") for i in range(3)]
    five = [false_pause(i, 420, f"r{i}") for i in range(REVERSAL_REPORTS)]

    assert decide(three, current=400, last_direction=-1) is None
    assert decide(five, current=400, last_direction=-1) == 450
    # Going further the same way needs only the usual three.
    onward = [missed(i, 320, f"r{i}") for i in range(3)]
    assert decide(onward, current=400, last_direction=-1) == 300


# --- Other settings ----------------------------------------------------------------------


def test_a_priority_moves_one_step_at_a_time():
    not_useful = [report(i, -1, setting=PITCH_PRIORITY, recording=f"r{i}") for i in range(3)]

    assert decide(not_useful, current=1.0, setting=PITCH_PRIORITY) == 0.8
    assert decide(not_useful, current=0.8, setting=PITCH_PRIORITY) == 0.6


def test_the_speech_detection_threshold_is_not_adjustable():
    """Measured on the real detector, it changes almost nothing inside its safe range and
    swallows real pauses outside it, so no report is allowed to move it."""
    assert "vad_threshold" not in ADAPTIVE
    assert sorted(name for name in ADAPTIVE if not name.startswith("priority_")) == ["min_pause_ms"]


def test_useful_ratings_cancel_not_useful_ones():
    ratings = [report(i, -1, setting=PITCH_PRIORITY, recording=f"r{i}") for i in range(3)]
    ratings += [report(10 + i, 1, setting=PITCH_PRIORITY, recording=f"u{i}") for i in range(2)]

    assert decide(ratings, current=1.0, setting=PITCH_PRIORITY) is None


def test_a_priority_already_at_normal_cannot_be_raised_further():
    useful = [report(i, 1, setting=PITCH_PRIORITY, recording=f"r{i}") for i in range(4)]

    assert decide(useful, current=1.0, setting=PITCH_PRIORITY) is None


@pytest.mark.parametrize("reports, label", [(3, "low"), (4, "low"), (5, "medium"), (8, "high")])
def test_confidence_grows_only_with_the_number_of_agreeing_reports(reports, label):
    assert engine.confidence(reports) == label
