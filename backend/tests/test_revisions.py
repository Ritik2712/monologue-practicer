"""Later results made from the same recording: corrected transcripts and fresh analyses."""

import os

from app import uploads
from tests.conftest import wav_bytes
from tests.test_feedback import recording
from tests.test_feedback_api import give, missed_pauses


def correct(client, analysis_id: str, **texts: str):
    """Corrects phrases given as seg_1="the real words"."""
    corrections = [
        {"segmentId": name.replace("_", "-"), "text": text} for name, text in texts.items()
    ]
    return client.post(f"/api/analyses/{analysis_id}/transcript", json={"corrections": corrections})


def kept_files(data_dir) -> list[str]:
    folder = data_dir / uploads.RETAINED_DIR
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


# --- Correcting the transcript -----------------------------------------------------------


def test_a_corrected_transcript_becomes_a_new_revision_with_wpm_worked_out_again(
    client, store_result
):
    analysis_id = store_result(recording())
    before = client.get(f"/api/analyses/{analysis_id}").json()

    response = correct(client, analysis_id, seg_1="phrase one has four")

    assert response.status_code == 201
    revision = response.json()
    assert revision["analysisId"] != analysis_id
    assert (revision["revision"], revision["revisionReason"]) == (2, "transcript_corrected")
    first = revision["segments"][0]
    # 4 words in the phrase's own 4 seconds: 60 WPM. It was 6 words, 90 WPM.
    assert (first["transcript"], first["wordCount"], first["segmentWpm"]) == (
        "phrase one has four",
        4,
        60.0,
    )
    assert revision["metrics"]["totalWordCount"]["value"] == 16
    assert revision["metrics"]["speechActiveWpm"]["value"] == 80.0  # 16 words in 12 s
    assert "transcript_corrected" in [warning["code"] for warning in revision["warnings"]]
    # Nothing measured from the sound moved.
    assert revision["pauses"] == before["pauses"]
    assert revision["metrics"]["pauseCount"] == before["metrics"]["pauseCount"]
    assert revision["settings"] == before["settings"]


def test_the_result_that_was_corrected_stays_exactly_as_it_was(client, store_result):
    analysis_id = store_result(recording())
    before = client.get(f"/api/analyses/{analysis_id}").json()

    revision = correct(client, analysis_id, seg_1="only three words").json()

    after = client.get(f"/api/analyses/{analysis_id}").json()
    listed = after.pop("revisions")
    before.pop("revisions")
    assert after == before
    # Each of the two now lists the other, oldest first, with the reason it exists.
    assert listed == revision["revisions"]
    assert [(item["analysisId"], item["revision"], item["reason"]) for item in listed] == [
        (analysis_id, 1, None),
        (revision["analysisId"], 2, "transcript_corrected"),
    ]


def test_a_revision_gets_coaching_from_the_rules_and_says_the_model_was_not_asked(
    client, store_result
):
    # The Thomas Shelby profile wants a held silence, and this take has none: an issue
    # that is still there after the words are corrected.
    analysis_id = store_result(recording(speech_active_wpm=230.0, profile="thomas_shelby"))

    revision = correct(client, analysis_id, seg_1="short now").json()

    coaching = revision["coaching"]
    assert (coaching["source"], coaching["notice"]["code"]) == ("rules", "not_asked")
    assert coaching["corrections"]
    # 14 words in 12 s of speaking: the coaching reads the corrected figure, not the old one.
    assert "You spoke at 70 WPM" in coaching["summary"][0]["text"]


def test_both_revisions_appear_in_the_history(client, store_result):
    analysis_id = store_result(recording())
    revision_id = correct(client, analysis_id, seg_2="two words").json()["analysisId"]

    items = client.get("/api/analyses").json()["items"]

    assert {(item["analysisId"], item["revision"], item["revisionReason"]) for item in items} == {
        (analysis_id, 1, None),
        (revision_id, 2, "transcript_corrected"),
    }
    assert {item["originalFilename"] for item in items} == {"take.wav"}


def test_a_correction_is_recorded_as_feedback_on_the_result_it_corrected(client, store_result):
    analysis_id = store_result(recording())

    correct(client, analysis_id, seg_1="phrase one", seg_2="phrase number 2 has six words")

    items = client.get(f"/api/analyses/{analysis_id}/feedback").json()["items"]
    # The second phrase came out the same, so only the first is on record.
    [item] = items
    assert (item["category"], item["targetId"], item["effect"]) == (
        "transcript_wrong",
        "seg-1",
        "recorded",
    )
    assert item["features"] == {"words": 6, "corrected_words": 2, "revision": 2}
    assert item["message"].startswith("You corrected this phrase. Revision 2 uses your words")


def test_flagging_the_transcript_without_supplying_words_recalculates_nothing(client, store_result):
    analysis_id = store_result(recording())
    before = client.get(f"/api/analyses/{analysis_id}").json()

    update = give(client, analysis_id, "transcript_wrong", "seg-1")

    assert client.get(f"/api/analyses/{analysis_id}").json() == before
    assert "until you supply the words" in update["items"][0]["message"]
    assert len(client.get("/api/analyses").json()["items"]) == 1


def test_pause_labels_come_along_to_the_revision_but_reports_do_not(client, store_result):
    analysis_id = store_result(recording(pauses=(0.6, 3.0)))
    give(client, analysis_id, "pause_intentional", "pause-2", note="the big beat")
    give(client, analysis_id, "pause_false", "pause-1")

    revision = correct(client, analysis_id, seg_1="phrase one").json()

    copied = client.get(f"/api/analyses/{revision['analysisId']}/feedback").json()
    assert [(i["category"], i["targetId"], i["note"]) for i in copied["items"]] == [
        ("pause_intentional", "pause-2", "the big beat")
    ]
    # The one report is still counted once, on the result it was made about.
    assert copied["calibration"]["pendingReportCount"] == 1
    assert revision["coaching"]["labelsUsed"] == {"pause-2": "intentional"}


def test_correcting_a_revision_makes_revision_three(client, store_result):
    analysis_id = store_result(recording())
    second = correct(client, analysis_id, seg_1="phrase one").json()

    third = correct(client, second["analysisId"], seg_2="phrase two").json()

    assert third["revision"] == 3
    assert [item["revision"] for item in third["revisions"]] == [1, 2, 3]
    assert [s["transcript"] for s in third["segments"]][:2] == ["phrase one", "phrase two"]


def test_corrections_that_change_nothing_or_name_no_phrase_are_refused(client, store_result):
    analysis_id = store_result(recording())
    reference_id = store_result(recording(), role="reference", title="The original")

    same = correct(client, analysis_id, seg_1=" phrase number 1  has six words ")
    unknown = correct(client, analysis_id, seg_9="anything")
    reference = correct(client, reference_id, seg_1="anything")
    missing = correct(client, "nope", seg_1="anything")
    empty = client.post(f"/api/analyses/{analysis_id}/transcript", json={"corrections": []})

    assert (same.status_code, same.json()["detail"]["code"]) == (400, "nothing_changed")
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "unknown_target")
    assert (reference.status_code, reference.json()["detail"]["code"]) == (409, "not_a_take")
    assert missing.json()["detail"]["code"] == "analysis_not_found"
    assert empty.json()["detail"]["code"] == "invalid_request"
    assert len(client.get("/api/analyses").json()["items"]) == 1


def test_a_kept_recording_is_shared_with_the_revision_and_each_can_be_deleted_alone(
    client, store_result, data_dir
):
    analysis_id = store_result(recording(), retain_audio=True)

    revision_id = correct(client, analysis_id, seg_1="phrase one").json()["analysisId"]

    assert kept_files(data_dir) == sorted([f"{analysis_id}.wav", f"{revision_id}.wav"])
    folder = data_dir / uploads.RETAINED_DIR
    # Two names for one file on disk: the revision costs no extra space.
    assert os.path.samefile(folder / f"{analysis_id}.wav", folder / f"{revision_id}.wav")
    assert client.get(f"/api/analyses/{revision_id}/audio").status_code == 200

    client.delete(f"/api/analyses/{analysis_id}/audio")

    assert kept_files(data_dir) == [f"{revision_id}.wav"]
    assert client.get(f"/api/analyses/{revision_id}/audio").status_code == 200
    assert client.get(f"/api/analyses/{revision_id}").json()["audioRetained"] is True


def test_deleting_the_first_result_leaves_its_revision_readable(client, store_result):
    analysis_id = store_result(recording())
    revision_id = correct(client, analysis_id, seg_1="phrase one").json()["analysisId"]

    client.delete(f"/api/analyses/{analysis_id}")

    revision = client.get(f"/api/analyses/{revision_id}").json()
    assert [item["analysisId"] for item in revision["revisions"]] == [revision_id]
    assert revision["segments"][0]["transcript"] == "phrase one"


# --- Analysing a kept recording again ----------------------------------------------------


def upload(client, **form) -> str:
    return client.post(
        "/api/analyses",
        files={"audio": ("take.wav", wav_bytes(9.0), "audio/wav")},
        data=form,
    ).json()["jobId"]


def test_analysing_again_makes_a_new_revision_with_the_settings_in_force_now(
    client, store_result, make_worker, data_dir
):
    job_id = upload(client, retainAudio="true", profile="joker", language="hi")
    make_worker().process_next_job()
    first_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]
    first = client.get(f"/api/analyses/{first_id}").json()
    missed_pauses(client, store_result)  # moves the minimum pause to 400 ms: version 2

    response = client.post(f"/api/analyses/{first_id}/reanalysis")

    assert response.status_code == 202
    job = response.json()
    assert (job["kind"], job["role"], job["sourceAnalysisId"]) == ("analysis", "take", first_id)
    make_worker().process_next_job()
    second_id = client.get(f"/api/jobs/{job['jobId']}").json()["analysisId"]
    second = client.get(f"/api/analyses/{second_id}").json()

    assert second_id != first_id
    assert (second["revision"], second["revisionReason"]) == (2, "reanalysed")
    assert (second["profile"], second["language"]["code"]) == ("joker", "hi")
    assert (second["settings"]["calibration_version"], second["settings"]["min_pause_ms"]) == (
        2,
        400,
    )
    # The earlier result still says it was made with version 1, and has not changed.
    again = client.get(f"/api/analyses/{first_id}").json()
    assert again["settings"] == first["settings"]
    assert again["metrics"] == first["metrics"]
    assert [(r["revision"], r["calibrationVersion"]) for r in again["revisions"]] == [
        (1, 1),
        (2, 2),
    ]
    # Each revision has its own recording, and the upload made for the job is gone.
    assert kept_files(data_dir) == sorted([f"{first_id}.wav", f"{second_id}.wav"])
    assert not list((data_dir / uploads.UPLOADS_DIR).iterdir())


def test_a_reference_can_be_measured_again_and_stays_a_reference(client, store_result, make_worker):
    job_id = upload(client, retainAudio="true", role="reference", title="The original")
    make_worker().process_next_job()
    first_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]
    missed_pauses(client, store_result)  # the minimum pause is now 400 ms

    job = client.post(f"/api/analyses/{first_id}/reanalysis").json()
    make_worker().process_next_job()
    second = client.get(
        f"/api/analyses/{client.get(f'/api/jobs/{job["jobId"]}').json()['analysisId']}"
    ).json()

    assert (job["role"], second["role"], second["title"]) == (
        "reference",
        "reference",
        "The original",
    )
    assert (second["revision"], second["settings"]["min_pause_ms"]) == (2, 400)
    # A reference is someone else's performance: still no coaching.
    assert second["coaching"] is None
    listed = client.get("/api/analyses", params={"role": "reference"}).json()["items"]
    assert [(item["revision"], item["settings"]["min_pause_ms"]) for item in listed] == [
        (2, 400),
        (1, 500),
    ]
    assert client.get("/api/analyses").json()["total"] == 2  # only the two stored takes


def test_asking_twice_does_not_queue_two_analyses(client, make_worker):
    job_id = upload(client, retainAudio="true")
    make_worker().process_next_job()
    analysis_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]

    first = client.post(f"/api/analyses/{analysis_id}/reanalysis")
    second = client.post(f"/api/analyses/{analysis_id}/reanalysis")

    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["jobId"] == second.json()["jobId"]


def test_analysing_again_needs_the_recording_to_have_been_kept(client, make_worker):
    job_id = upload(client)
    make_worker().process_next_job()
    analysis_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]

    refused = client.post(f"/api/analyses/{analysis_id}/reanalysis")

    assert (refused.status_code, refused.json()["detail"]["code"]) == (409, "audio_not_kept")
    assert client.post("/api/analyses/nope/reanalysis").json()["detail"]["code"] == (
        "analysis_not_found"
    )


def test_a_cancelled_reanalysis_leaves_the_kept_recording_alone(client, make_worker, data_dir):
    job_id = upload(client, retainAudio="true")
    make_worker().process_next_job()
    analysis_id = client.get(f"/api/jobs/{job_id}").json()["analysisId"]
    job = client.post(f"/api/analyses/{analysis_id}/reanalysis").json()

    client.post(f"/api/jobs/{job['jobId']}/cancel")

    assert kept_files(data_dir) == [f"{analysis_id}.wav"]
    assert client.get(f"/api/analyses/{analysis_id}/audio").status_code == 200
    assert not list((data_dir / uploads.UPLOADS_DIR).iterdir())
