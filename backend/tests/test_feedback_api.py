"""Feedback and calibration through the API: what is stored, what moves, and what never does."""

import pytest

from app.calibration.registry import ADAPTIVE, DEFAULT_VALUES
from app.pipeline.runner import PipelineDeps
from app.worker import Worker
from tests.conftest import fake_vad, make_words, no_pitch, no_resonance
from tests.test_feedback import recording


def give(client, analysis_id: str, category: str, target: str | None = None, **extra) -> dict:
    response = client.post(
        f"/api/analyses/{analysis_id}/feedback",
        json={"category": category, "targetId": target, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def values(calibration: dict) -> dict[str, float]:
    return {setting["name"]: setting["value"] for setting in calibration["settings"]}


def setting(calibration: dict, name: str) -> dict:
    return next(item for item in calibration["settings"] if item["name"] == name)


# Three silences of 0.4 s inside the first phrase: each can be reported once.
SILENCES = ((0.5, 0.9), (1.5, 1.9), (2.5, 2.9))


def missed_pauses(client, store_result, count=3, recordings=2) -> tuple[list[str], dict]:
    """Reports 0.4 s silences as missed pauses, spread over several recordings."""
    ids = [store_result(recording(silences=SILENCES)) for _ in range(recordings)]
    last = {}
    for number in range(count):
        silence = SILENCES[(number // recordings) % len(SILENCES)]
        last = give(
            client, ids[number % recordings], "pause_missed", "seg-1", atSeconds=silence[0] + 0.2
        )
    return ids, last


# --- Storing -----------------------------------------------------------------------------


def test_feedback_is_stored_with_what_was_measured_and_the_version_it_is_about(
    client, store_result
):
    analysis_id = store_result(recording())

    saved = give(client, analysis_id, "pause_false", "pause-1", note="  I was mid-word  ")

    [item] = saved["items"]
    assert item["analysisId"] == analysis_id
    assert (item["category"], item["targetKind"], item["targetId"]) == (
        "pause_false",
        "pause",
        "pause-1",
    )
    assert item["note"] == "I was mid-word"
    assert item["calibrationVersion"] == 1
    assert item["features"] == {"pause_ms": 600, "min_pause_ms": 500}
    assert (item["effect"], item["setting"], item["direction"]) == ("report", "min_pause_ms", 1)
    assert "1 of the 3 reports needed for raising it" in item["message"]
    # It is there again when the page is opened later.
    assert client.get(f"/api/analyses/{analysis_id}/feedback").json()["items"] == saved["items"]


def test_saying_something_else_about_the_same_pause_replaces_what_was_said(client, store_result):
    analysis_id = store_result(recording())

    give(client, analysis_id, "pause_false", "pause-1")
    saved = give(client, analysis_id, "pause_intentional", "pause-1")

    assert [item["category"] for item in saved["items"]] == ["pause_intentional"]
    assert saved["calibration"]["pendingReportCount"] == 0


def test_the_same_feedback_again_only_changes_its_note(client, store_result):
    analysis_id = store_result(recording())

    first = give(client, analysis_id, "pause_accidental", "pause-1", note="lost my place")
    kept = give(client, analysis_id, "pause_accidental", "pause-1")
    changed = give(client, analysis_id, "pause_accidental", "pause-1", note="forgot the line")
    cleared = give(client, analysis_id, "pause_accidental", "pause-1", note="")

    assert [update["items"][0]["note"] for update in (first, kept, changed, cleared)] == [
        "lost my place",
        "lost my place",
        "forgot the line",
        None,
    ]
    assert {update["items"][0]["id"] for update in (first, kept, changed, cleared)} == {
        first["items"][0]["id"]
    }


def test_feedback_can_be_taken_back(client, store_result):
    analysis_id = store_result(recording())
    saved = give(client, analysis_id, "pause_false", "pause-1")

    after = client.delete(f"/api/feedback/{saved['items'][0]['id']}")

    assert after.status_code == 200
    assert after.json()["items"] == []
    assert after.json()["calibration"]["feedbackCount"] == 0
    assert client.delete("/api/feedback/nope").json()["detail"]["code"] == "feedback_not_found"


def test_a_mistake_in_how_a_reference_was_measured_can_be_reported(client, store_result):
    reference_id = store_result(recording(), role="reference", title="The original")

    saved = give(client, reference_id, "pause_false", "pause-1", note="music under the line")

    [item] = saved["items"]
    assert (item["effect"], item["setting"], item["direction"]) == ("report", "min_pause_ms", 1)
    assert item["features"] == {"pause_ms": 600, "min_pause_ms": 500}
    assert item["note"] == "music under the line"
    # It counts, and the message says what is still missing before anything can move.
    assert "1 of the 3 reports needed for raising it" in item["message"]
    assert "a take of your own" in item["message"]


@pytest.mark.parametrize(
    ("category", "target"),
    [("pause_intentional", "pause-1"), ("pause_accidental", "pause-1"), ("coaching_useful", "f1")],
)
def test_a_reference_has_no_coaching_so_it_takes_no_labels_and_no_ratings(
    client, store_result, category, target
):
    reference_id = store_result(recording(), role="reference", title="The original")

    refused = client.post(
        f"/api/analyses/{reference_id}/feedback",
        json={"category": category, "targetId": target},
    )

    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "not_for_reference"
    assert client.get(f"/api/analyses/{reference_id}/feedback").json()["items"] == []


def test_reports_on_references_alone_never_move_a_setting(client, store_result):
    references = [
        store_result(recording(silences=SILENCES), role="reference", title=f"Clip {number}")
        for number in (1, 2)
    ]
    for number in range(4):
        update = give(
            client,
            references[number % 2],
            "pause_missed",
            "seg-1",
            atSeconds=SILENCES[number // 2][0] + 0.2,
        )

    calibration = update["calibration"]
    assert update["adjustments"] == []
    assert values(calibration) == DEFAULT_VALUES
    pause = setting(calibration, "min_pause_ms")
    assert pause["pending"] == {
        "raiseCount": 0,
        "lowerCount": 4,
        "recordings": 2,
        "needed": 3,
        "takeReports": 0,
    }
    assert "4 of the 3 reports needed for lowering it" in pause["status"]
    assert "All of them are about reference recordings" in pause["status"]


def test_a_report_on_an_own_take_lets_the_reports_on_references_count(client, store_result):
    reference_id = store_result(recording(silences=SILENCES), role="reference", title="Clip")
    take_id = store_result(recording(silences=SILENCES))
    for silence in SILENCES[:2]:
        waiting = give(client, reference_id, "pause_missed", "seg-1", atSeconds=silence[0] + 0.2)
    assert waiting["adjustments"] == []

    update = give(client, take_id, "pause_missed", "seg-1", atSeconds=SILENCES[0][0] + 0.2)

    [change] = update["adjustments"]
    assert (change["setting"], change["oldValue"], change["newValue"]) == (
        "min_pause_ms",
        500,
        400,
    )
    assert (change["agreeingCount"], change["recordingCount"]) == (3, 2)


def test_the_wpm_review_of_a_reference_does_not_speak_of_what_you_said(client, store_result):
    reference_id = store_result(recording(), role="reference", title="The original")

    saved = give(client, reference_id, "wpm_too_high", "seg-2")

    [item] = saved["items"]
    texts = " ".join(check["text"] for check in item["review"]["checks"])
    assert "A word that was not said" in texts
    assert "what is said in the recording" in texts
    assert "If the speaker was still speaking" in texts
    assert "you said" not in texts and "you were" not in texts


def test_bad_feedback_is_refused_in_the_usual_error_shape(client, store_result):
    analysis_id = store_result(recording())
    url = f"/api/analyses/{analysis_id}/feedback"

    unknown_pause = client.post(url, json={"category": "pause_false", "targetId": "pause-9"})
    unknown_category = client.post(url, json={"category": "be_nicer"})
    long_note = client.post(url, json={"category": "wpm_too_high", "note": "x" * 281})
    no_analysis = client.post("/api/analyses/nope/feedback", json={"category": "wpm_too_high"})

    assert (unknown_pause.status_code, unknown_pause.json()["detail"]["code"]) == (
        404,
        "unknown_target",
    )
    assert unknown_category.json()["detail"]["code"] == "invalid_request"
    assert long_note.json()["detail"]["code"] == "invalid_request"
    assert no_analysis.json()["detail"]["code"] == "analysis_not_found"


def test_deleting_an_analysis_deletes_the_feedback_given_on_it(client, store_result):
    analysis_id = store_result(recording())
    give(client, analysis_id, "pause_false", "pause-1", note="private note")

    client.delete(f"/api/analyses/{analysis_id}")

    assert client.get("/api/calibration").json()["feedbackCount"] == 0


def test_a_report_no_setting_can_answer_is_saved_and_says_why(client, store_result):
    """A 1.2 s "pause" that was really speech, and a missed pause where no silence was heard."""
    analysis_id = store_result(recording())

    give(client, analysis_id, "pause_false", "pause-2")
    update = give(client, analysis_id, "pause_missed", "seg-1", atSeconds=3.4)

    messages = {item["category"]: item for item in update["items"]}
    assert {item["effect"] for item in update["items"]} == {"recorded"}
    assert "The detector heard no speech for 1.2 s there" in messages["pause_false"]["message"]
    assert "too quiet for the detector" in messages["pause_false"]["message"]
    assert "heard speech straight through" in messages["pause_missed"]["message"]
    assert update["calibration"]["pendingReportCount"] == 0
    assert update["adjustments"] == []


# --- Before there is enough to go on -----------------------------------------------------


def test_a_fresh_install_says_it_is_still_calibrating_and_shows_every_value(client):
    calibration = client.get("/api/calibration").json()

    assert (calibration["version"], calibration["adaptive"], calibration["state"]) == (
        1,
        True,
        "calibrating",
    )
    assert calibration["summary"].startswith("Still calibrating")
    assert values(calibration) == DEFAULT_VALUES
    assert calibration["canUndo"] is False
    pause = setting(calibration, "min_pause_ms")
    assert (pause["value"], pause["minimum"], pause["maximum"], pause["unit"]) == (
        500,
        250,
        800,
        "ms",
    )
    assert pause["confidence"] == "none"
    # Every adjustable setting has explicit bounds, and its default lies inside them.
    for item in calibration["settings"]:
        assert item["minimum"] <= item["default"] <= item["maximum"], item["name"]
    # The thresholds feedback never touches are shown too, including the 5 s long silence.
    fixed = {item["name"]: item["value"] for item in calibration["fixed"]}
    assert fixed["vad_threshold"] == 0.5
    assert (fixed["long_silence_ms"], fixed["min_segment_ms"], fixed["wpm_outlier"]) == (
        5000,
        2000,
        180,
    )
    assert [change["cause"] for change in calibration["changes"]] == ["defaults"]
    assert calibration["rules"] == {
        "minReports": 3,
        "minRecordings": 2,
        "minTakeReports": 1,
        "minAgreement": 0.75,
        "window": 10,
        "reversalReports": 5,
    }


def test_two_reports_change_nothing_and_the_app_does_not_claim_to_have_learned(
    client, store_result
):
    _, update = missed_pauses(client, store_result, count=2)

    calibration = update["calibration"]
    assert update["adjustments"] == []
    assert (calibration["version"], calibration["state"]) == (1, "calibrating")
    assert values(calibration) == DEFAULT_VALUES
    assert calibration["pendingReportCount"] == 2
    pause = setting(calibration, "min_pause_ms")
    assert pause["pending"] == {
        "raiseCount": 0,
        "lowerCount": 2,
        "recordings": 2,
        "needed": 3,
        "takeReports": 2,
    }
    assert "2 of the 3 reports needed for lowering it" in pause["status"]


def test_three_reports_from_one_recording_are_not_enough(client, store_result):
    _, update = missed_pauses(client, store_result, count=3, recordings=1)

    assert update["adjustments"] == []
    pause = setting(update["calibration"], "min_pause_ms")
    assert "from 1 of the 2 recordings needed" in pause["status"]
    assert pause["value"] == 500


# --- An adjustment -----------------------------------------------------------------------


def test_three_agreeing_reports_from_two_recordings_move_only_the_minimum_pause(
    client, store_result
):
    ids, update = missed_pauses(client, store_result)

    [adjustment] = update["adjustments"]
    assert (adjustment["version"], adjustment["cause"], adjustment["setting"]) == (
        2,
        "auto",
        "min_pause_ms",
    )
    assert (adjustment["oldValue"], adjustment["newValue"]) == (500, 400)
    assert adjustment["reason"] == (
        "Minimum pause lowered from 500 ms to 400 ms after 3 reports of a pause that was "
        "missed, from 2 recordings. The silences reported were around 400 ms long."
    )
    assert (adjustment["reportCount"], adjustment["agreeingCount"], adjustment["confidence"]) == (
        3,
        3,
        "low",
    )

    calibration = update["calibration"]
    assert (calibration["version"], calibration["state"]) == (2, "adjusted")
    # Only the intended setting moved. Every other one is exactly where it was.
    assert values(calibration) == {**DEFAULT_VALUES, "min_pause_ms": 400}
    pause = setting(calibration, "min_pause_ms")
    assert (pause["changed"], pause["supportingReports"], pause["confidence"]) == (True, 3, "low")
    assert calibration["pendingReportCount"] == 0
    assert calibration["canUndo"] is True
    assert "small sample" in calibration["summary"]
    # Each report now says what became of it.
    item = client.get(f"/api/analyses/{ids[0]}/feedback").json()["items"][0]
    assert item["effect"] == "used"
    assert item["message"].startswith("Counted in version 2. Minimum pause lowered")


def test_reports_that_disagree_leave_the_setting_alone(client, store_result):
    ids, _ = missed_pauses(client, store_result, count=2)
    give(client, ids[0], "pause_false", "pause-1")
    update = give(client, ids[1], "pause_false", "pause-1")

    assert update["adjustments"] == []
    assert "they cancel out" in setting(update["calibration"], "min_pause_ms")["status"]


def test_taking_back_a_dissenting_report_lets_the_rest_act(client, store_result):
    """Three say lower and two say raise: too much disagreement. Remove one, and it is 3 to 1."""
    ids = [store_result(recording(silences=SILENCES)) for _ in range(2)]
    dissent = [give(client, i, "pause_false", "pause-1")["items"][0]["id"] for i in ids]
    update = {}
    for analysis_id, silence in ((ids[0], 0), (ids[1], 0), (ids[0], 1)):
        at = SILENCES[silence][0] + 0.2
        update = give(client, analysis_id, "pause_missed", "seg-1", atSeconds=at)
    assert update["adjustments"] == []
    assert "disagree too much" in setting(update["calibration"], "min_pause_ms")["status"]

    after = client.delete(f"/api/feedback/{dissent[0]}").json()

    assert [adjustment["newValue"] for adjustment in after["adjustments"]] == [400]
    assert "1 report pointed the other way" in after["adjustments"][0]["reason"]


def test_each_adjustment_needs_fresh_reports_so_a_setting_moves_gradually(client, store_result):
    """After one adjustment the same reports are spent: nothing moves again by itself."""
    ids, _ = missed_pauses(client, store_result)

    again = give(client, ids[0], "pause_missed", "seg-1", atSeconds=2.7)

    # The silence was 400 ms and the minimum is 400 ms now, so this report is answered.
    assert again["adjustments"] == []
    assert again["calibration"]["version"] == 2
    latest = next(i for i in again["items"] if i["features"]["silence_start_seconds"] == 2.5)
    assert "no longer counts" in latest["message"]


def test_the_minimum_pause_never_goes_below_its_bound(client, store_result):
    """Report after report of very short silences: it stops at 250 ms and stays there."""
    silences = ((1.0, 1.26), (2.0, 2.26), (3.0, 3.26))
    update = {}
    for round_number in range(6):
        floor = max(250, 500 - 100 * round_number)
        ids = [
            store_result(recording(silences=silences, settings={"min_pause_ms": floor}))
            for _ in range(2)
        ]
        for number, at in enumerate((1.1, 2.1, 3.1)):
            update = give(client, ids[number % 2], "pause_missed", "seg-1", atSeconds=at)

    calibration = update["calibration"]
    assert setting(calibration, "min_pause_ms")["value"] == 250
    assert [c["newValue"] for c in reversed(calibration["changes"]) if c["cause"] == "auto"] == [
        400,
        300,
        250,
    ]
    assert all(
        ADAPTIVE[name].minimum <= value <= ADAPTIVE[name].maximum
        for name, value in values(calibration).items()
    )


def test_rating_corrections_moves_only_the_priority_of_that_kind(client, store_result):
    update = {}
    for number in range(3):
        analysis_id = store_result(recording(speech_active_wpm=230.0))
        coaching = client.get(f"/api/analyses/{analysis_id}").json()["coaching"]
        pace = next(f["id"] for f in coaching["findings"] if f["kind"] == "pace")
        update = give(client, analysis_id, "coaching_not_useful", pace)
        assert len(update["adjustments"]) == (1 if number == 2 else 0)

    assert values(update["calibration"]) == {**DEFAULT_VALUES, "priority_pace": 0.8}
    assert update["adjustments"][0]["reason"] == (
        "Corrections about overall pace moved down the list (priority from 1.0 to 0.8) after 3 "
        "ratings of “not useful”, from 3 recordings."
    )


# --- Undo, reset, off --------------------------------------------------------------------


def test_undo_puts_the_value_back_and_the_same_reports_cannot_bring_the_change_back(
    client, store_result
):
    ids, _ = missed_pauses(client, store_result)

    undone = client.post("/api/calibration/undo").json()

    assert (undone["version"], undone["state"], undone["canUndo"]) == (3, "calibrating", False)
    assert values(undone) == DEFAULT_VALUES
    latest, adjustment = undone["changes"][0], undone["changes"][1]
    assert (latest["cause"], latest["oldValue"], latest["newValue"]) == ("undo", 400, 500)
    assert adjustment["undone"] is True
    # The spent reports stay spent: nothing re-applies the change behind the user's back.
    assert undone["pendingReportCount"] == 0
    item = client.get(f"/api/analyses/{ids[0]}/feedback").json()["items"][0]
    assert "no longer in effect" in item["message"]
    # With nothing left to undo, the request is refused rather than silently ignored.
    assert client.post("/api/calibration/undo").json()["detail"]["code"] == "nothing_to_undo"


def test_undo_walks_back_one_adjustment_at_a_time(client, store_result):
    missed_pauses(client, store_result)
    for number in range(3):
        analysis_id = store_result(recording(speech_active_wpm=230.0))
        coaching = client.get(f"/api/analyses/{analysis_id}").json()["coaching"]
        pace = next(f["id"] for f in coaching["findings"] if f["kind"] == "pace")
        give(client, analysis_id, "coaching_not_useful", pace)

    first = client.post("/api/calibration/undo").json()
    second = client.post("/api/calibration/undo").json()

    assert values(first) == {**DEFAULT_VALUES, "min_pause_ms": 400}
    assert values(second) == DEFAULT_VALUES


def test_reset_returns_every_setting_to_its_default_and_starts_counting_again(client, store_result):
    ids, _ = missed_pauses(client, store_result)
    give(client, ids[0], "pause_false", "pause-1")  # one report still waiting

    reset = client.post("/api/calibration/reset").json()

    assert values(reset) == DEFAULT_VALUES
    assert (reset["state"], reset["canUndo"], reset["pendingReportCount"]) == (
        "calibrating",
        False,
        0,
    )
    assert reset["changes"][0]["cause"] == "reset"
    # The feedback itself is kept; it has just stopped counting.
    assert reset["feedbackCount"] == 4
    items = client.get(f"/api/analyses/{ids[0]}/feedback").json()["items"]
    messages = {item["category"]: item["message"] for item in items}
    assert messages["pause_false"] == "Set aside when the settings were reset to the defaults."
    assert "no longer in effect" in messages["pause_missed"]
    assert client.post("/api/calibration/reset").json()["detail"]["code"] == "already_default"


def test_while_switched_off_feedback_is_saved_but_nothing_moves(client, store_result):
    off = client.put("/api/calibration/adaptive", json={"enabled": False}).json()
    assert off["adaptive"] is False
    assert off["summary"].startswith("Automatic adjustment is switched off")

    _, update = missed_pauses(client, store_result)

    assert update["adjustments"] == []
    assert values(update["calibration"]) == DEFAULT_VALUES
    assert update["calibration"]["pendingReportCount"] == 3
    assert "switched off" in update["items"][-1]["message"]
    assert (
        "would move if automatic adjustment were switched on"
        in setting(update["calibration"], "min_pause_ms")["status"]
    )

    # Switching it back on acts on what built up meanwhile.
    on = client.put("/api/calibration/adaptive", json={"enabled": True}).json()
    assert values(on) == {**DEFAULT_VALUES, "min_pause_ms": 400}


# --- Results stay traceable --------------------------------------------------------------


@pytest.fixture
def worker_with_a_short_gap(session_factory, data_dir, clock):
    """A scripted recording with a 0.45 s gap in the speech, and 12 + 6 words around it."""

    def build() -> Worker:
        from tests.conftest import FakeTranscriber

        transcriber = FakeTranscriber(make_words(0.5, 4.5, 12) + make_words(4.95, 7.0, 6))
        deps = PipelineDeps(
            transcriber=transcriber,
            detect_speech=fake_vad([(0.5, 4.5), (4.95, 7.0)]),
            measure_pitch=no_pitch,
            measure_resonance=no_resonance,
        )
        return Worker(session_factory, deps, data_dir=data_dir, clock=clock)

    return build


def analysed(client, worker) -> dict:
    from tests.conftest import wav_bytes

    job_id = client.post(
        "/api/analyses", files={"audio": ("take.wav", wav_bytes(9.0), "audio/wav")}
    ).json()["jobId"]
    worker.process_next_job()
    return client.get(
        f"/api/analyses/{client.get(f'/api/jobs/{job_id}').json()['analysisId']}"
    ).json()


def test_an_analysis_records_the_calibration_that_made_it_and_keeps_its_short_silences(
    client, worker_with_a_short_gap
):
    result = analysed(client, worker_with_a_short_gap())

    assert result["settings"]["calibration_version"] == 1
    assert result["settings"]["min_pause_ms"] == 500
    # At 500 ms the 0.45 s gap is not a pause. It is kept on record inside its phrase.
    assert [segment["id"] for segment in result["segments"]] == ["seg-1"]
    assert result["pauses"] == []
    assert result["shortSilences"] == [
        {"startSeconds": 4.5, "endSeconds": 4.95, "durationSeconds": 0.45, "segmentId": "seg-1"}
    ]


def test_after_an_adjustment_new_analyses_use_it_and_old_ones_stay_as_they_were(
    client, store_result, worker_with_a_short_gap
):
    before = analysed(client, worker_with_a_short_gap())
    missed_pauses(client, store_result)  # the minimum pause is now 400 ms: version 2

    after = analysed(client, worker_with_a_short_gap())

    assert (after["settings"]["calibration_version"], after["settings"]["min_pause_ms"]) == (
        2,
        400,
    )
    # The 0.45 s gap in the same recording now counts as a pause. It is shorter than the
    # segment break, so it is a pause inside the phrase and does not cut it in two.
    assert [segment["id"] for segment in after["segments"]] == ["seg-1"]
    assert len(after["stretches"]) == 2
    assert [(pause["durationSeconds"], pause["insideSegment"]) for pause in after["pauses"]] == [
        (0.45, True)
    ]
    assert after["segments"][0]["pauseCount"] == 1
    assert after["shortSilences"] == []
    # The earlier result is untouched and still says which version produced it.
    again = client.get(f"/api/analyses/{before['analysisId']}").json()
    assert again == before
    assert again["settings"]["calibration_version"] == 1
    # The history shows the settings of each, so a mismatch can be pointed out.
    listed = {
        item["analysisId"]: item["settings"]["min_pause_ms"]
        for item in client.get("/api/analyses").json()["items"]
    }
    assert (listed[before["analysisId"]], listed[after["analysisId"]]) == (500, 400)


def test_a_comparison_says_so_when_the_two_were_analysed_with_different_settings(
    client, store_result
):
    take_id = store_result(recording(settings={"min_pause_ms": 400, "calibration_version": 2}))
    same_id = store_result(recording())
    reference_id = store_result(recording(), role="reference", title="The original")

    mismatched = client.get(f"/api/analyses/{take_id}/comparison/{reference_id}").json()
    matched = client.get(f"/api/analyses/{same_id}/comparison/{reference_id}").json()

    assert mismatched["settingsNote"].startswith(
        "These two were analysed with different settings: the minimum pause was 400 ms for "
        "your take and 500 ms for the reference."
    )
    assert matched["settingsNote"] is None


# --- A label is not a measurement --------------------------------------------------------


def test_labelling_a_pause_changes_nothing_that_was_measured(client, store_result):
    analysis_id = store_result(recording(pauses=(0.6, 3.0)))
    before = client.get(f"/api/analyses/{analysis_id}").json()

    update = give(client, analysis_id, "pause_intentional", "pause-2")
    give(client, analysis_id, "pause_accidental", "pause-1")

    after = client.get(f"/api/analyses/{analysis_id}").json()
    assert after == before
    assert [pause["durationSeconds"] for pause in after["pauses"]] == [0.6, 3.0]
    assert after["metrics"]["pauseCount"]["value"] == 2
    assert update["items"][0]["effect"] == "label"
    assert "stays in every pause figure" in update["items"][0]["message"]
    # A label never counts towards a setting.
    assert update["calibration"]["pendingReportCount"] == 0


def test_labels_shape_the_coaching_when_it_is_written_again(client, store_result, make_worker):
    """No language model is set up here, so the rewrite comes from the templates: allowed,
    because coaching that takes the labels in is an improvement on coaching that does not."""
    analysis_id = store_result(recording(pauses=(0.6, 3.0), profile="thomas_shelby"))
    before = client.get(f"/api/analyses/{analysis_id}").json()
    held = next(f for f in before["coaching"]["findings"] if f["kind"] == "held_silence")
    assert "The longest pause is 3 seconds" in held["statement"]
    assert held["role"] == "strength"

    give(client, analysis_id, "pause_accidental", "pause-2")
    job = client.post(f"/api/analyses/{analysis_id}/coaching").json()
    make_worker().process_next_job()

    assert client.get(f"/api/jobs/{job['jobId']}").json()["status"] == "succeeded"
    after = client.get(f"/api/analyses/{analysis_id}").json()
    coaching = after["coaching"]
    # The label now says that the coaching has taken it in.
    [label] = client.get(f"/api/analyses/{analysis_id}/feedback").json()["items"]
    assert "already treats the pause as a slip" in label["message"]
    assert coaching["labelsUsed"] == {"pause-2": "accidental"}
    by_kind = {finding["kind"]: finding for finding in coaching["findings"]}
    # The 3-second pause is no longer praised as a held silence ...
    assert by_kind["held_silence"]["statement"].startswith(
        "Leaving out the 1 pause you marked as accidental, the longest pause is 0.6 seconds"
    )
    assert by_kind["held_silence"]["role"] == "issue"
    # ... and getting through that spot becomes something to work on.
    assert by_kind["accidental_pauses"]["role"] == "issue"
    assert "3 seconds at 0:08.6" in by_kind["accidental_pauses"]["statement"]
    assert any(
        correction["title"] == "Carry on through the place you stopped"
        for correction in coaching["corrections"]
    )
    # The measurements are exactly what they were: the pause is still counted, at full length.
    for key in ("pauses", "metrics", "segments", "words"):
        assert after[key] == before[key], key
    assert after["metrics"]["longestPauseSeconds"] == before["metrics"]["longestPauseSeconds"]


def test_without_new_labels_a_rewrite_still_needs_the_language_model(
    client, store_result, make_worker
):
    analysis_id = store_result(recording(pauses=(0.6, 3.0), profile="thomas_shelby"))
    job = client.post(f"/api/analyses/{analysis_id}/coaching").json()

    make_worker().process_next_job()

    assert client.get(f"/api/jobs/{job['jobId']}").json()["error"]["code"] == "ai_off"


# --- WPM ---------------------------------------------------------------------------------


def test_saying_the_wpm_looks_wrong_changes_no_number_and_shows_what_went_into_it(
    client, store_result
):
    analysis_id = store_result(recording())
    before = client.get(f"/api/analyses/{analysis_id}").json()

    update = give(client, analysis_id, "wpm_too_low", "seg-1")

    assert client.get(f"/api/analyses/{analysis_id}").json() == before
    assert update["adjustments"] == []
    assert update["calibration"]["pendingReportCount"] == 0
    [item] = update["items"]
    assert item["effect"] == "recorded"
    assert "No figure is changed by this" in item["message"]
    review = item["review"]
    assert (review["target"], review["words"], review["speakingSeconds"], review["wpm"]) == (
        "Segment 1",
        6,
        4.0,
        90.0,
    )
    assert review["formula"] == "6 words ÷ 4.00 s of speaking × 60 = 90.0 WPM."
    # Words, speaking time, word timing: the three things a WPM figure rests on.
    assert [(check["label"], check["action"]) for check in review["checks"]] == [
        ("The words", "correct_transcript"),
        ("The speaking time", "report_missed_pause"),
        ("Word timing", None),
    ]
    assert "2 silences too short to count as a pause, 0.50 s in all" in review["checks"][1]["text"]
    assert review["checks"][0]["text"].startswith("6 words were counted in this phrase.")
