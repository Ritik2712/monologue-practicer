"""Monologues: a reference recording, and the takes recorded for it."""

from sqlalchemy import func, select

from app.models import Analysis, Feedback, Job
from tests.conftest import wav_bytes


def submit(client, **form) -> dict:
    """Uploads a recording and returns the job, without running it."""
    return client.post(
        "/api/analyses",
        files={"audio": (form.pop("filename", "take.wav"), wav_bytes(9.0), "audio/wav")},
        data=form,
    ).json()


def analyse(client, make_worker, **form) -> str:
    """Uploads a recording, runs it, and returns the analysis ID."""
    job_id = submit(client, **form)["jobId"]
    make_worker().process_next_job()
    return client.get(f"/api/jobs/{job_id}").json()["analysisId"]


def add_monologue(client, make_worker, title: str = "The one who knocks", **form) -> str:
    return analyse(client, make_worker, role="reference", title=title, **form)


def take_ids(client, monologue: str | None = None) -> list[str]:
    query = "" if monologue is None else f"?monologue={monologue}"
    return [item["analysisId"] for item in client.get(f"/api/analyses{query}").json()["items"]]


def monologues(client) -> list[dict]:
    return client.get("/api/monologues").json()["items"]


def files_in(data_dir, folder: str) -> list[str]:
    path = data_dir / folder
    return sorted(item.name for item in path.iterdir()) if path.is_dir() else []


# --- A reference recording is a monologue ------------------------------------------------


def test_there_are_no_monologues_at_first(client):
    assert monologues(client) == []


def test_adding_a_reference_recording_makes_a_monologue(client, make_worker, clock):
    reference = add_monologue(client, make_worker, retainAudio="true")

    (monologue,) = monologues(client)
    assert monologue["monologueId"] == reference
    assert monologue["referenceId"] == reference
    assert monologue["title"] == "The one who knocks"
    assert monologue["createdAt"] == clock().isoformat().replace("+00:00", "Z")
    assert monologue["durationSeconds"] == 9.0
    assert monologue["audioRetained"] is True
    assert (monologue["revision"], monologue["revisionCount"]) == (1, 1)
    assert (monologue["takeCount"], monologue["lastTakeAt"]) == (0, None)
    assert monologue["settings"]["min_pause_ms"] == 500


def test_a_take_of_your_own_is_not_a_monologue(client, make_worker):
    analyse(client, make_worker)

    assert monologues(client) == []


# --- A take recorded for a monologue -----------------------------------------------------


def test_a_take_recorded_for_a_monologue_is_listed_under_it(client, make_worker, clock):
    reference = add_monologue(client, make_worker)
    clock.advance(minutes=5)
    job = submit(client, monologueId=reference)
    assert job["monologueId"] == reference
    make_worker().process_next_job()
    take = client.get(f"/api/jobs/{job['jobId']}").json()["analysisId"]
    free = analyse(client, make_worker)

    assert client.get(f"/api/analyses/{take}").json()["monologueId"] == reference
    assert client.get(f"/api/analyses/{free}").json()["monologueId"] is None
    assert take_ids(client, reference) == [take]
    # The General Practice history: only what belongs to no monologue.
    assert take_ids(client, "none") == [free]
    # Without the filter every take is listed, as before monologues existed.
    assert set(take_ids(client)) == {take, free}

    (monologue,) = monologues(client)
    assert monologue["takeCount"] == 1
    assert monologue["lastTakeAt"] is not None
    listed = client.get(f"/api/analyses?monologue={reference}").json()
    assert (listed["total"], listed["items"][0]["monologueId"]) == (1, reference)


def test_the_monologue_is_not_kept_inside_the_measured_result(client, make_worker, session):
    reference = add_monologue(client, make_worker)
    take = analyse(client, make_worker, monologueId=reference)

    stored = session.get(Analysis, take)
    assert stored.monologue_id == reference
    assert "monologueId" not in stored.result


def test_a_reference_is_never_recorded_for_a_monologue(client, make_worker):
    first = add_monologue(client, make_worker)
    second = analyse(client, make_worker, role="reference", title="Another", monologueId=first)

    assert client.get(f"/api/analyses/{second}").json()["monologueId"] is None
    assert {item["monologueId"] for item in monologues(client)} == {first, second}


def test_an_unknown_monologue_is_refused_and_nothing_is_stored(client, make_worker, data_dir):
    free = analyse(client, make_worker)

    for wrong in ("no-such-monologue", free):
        response = client.post(
            "/api/analyses",
            files={"audio": ("take.wav", wav_bytes(9.0), "audio/wav")},
            data={"monologueId": wrong},
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "monologue_not_found"
    assert files_in(data_dir, "uploads") == []
    assert client.get("/api/analyses?monologue=no-such-monologue").status_code == 404
    assert client.delete(f"/api/analyses?monologue={free}").status_code == 404
    assert take_ids(client) == [free]


# --- Revisions ---------------------------------------------------------------------------


def test_a_corrected_reference_is_still_the_same_monologue(client, make_worker, clock):
    reference = add_monologue(client, make_worker)
    before = analyse(client, make_worker, monologueId=reference)
    clock.advance(minutes=1)
    corrected = client.post(
        f"/api/analyses/{reference}/transcript",
        json={"corrections": [{"segmentId": "seg-2", "text": "say my name"}]},
    ).json()["analysisId"]
    clock.advance(minutes=1)
    # A take can name the monologue by either revision of its reference.
    after = analyse(client, make_worker, monologueId=corrected)

    (monologue,) = monologues(client)
    assert monologue["monologueId"] == reference
    # Takes are now compared with the corrected words.
    assert monologue["referenceId"] == corrected
    assert (monologue["revision"], monologue["revisionCount"]) == (2, 2)
    assert monologue["takeCount"] == 2
    assert take_ids(client, corrected) == take_ids(client, reference) == [after, before]


def test_a_corrected_or_reanalysed_take_stays_with_its_monologue(client, make_worker, clock):
    reference = add_monologue(client, make_worker)
    take = analyse(client, make_worker, monologueId=reference, retainAudio="true")
    clock.advance(minutes=1)
    corrected = client.post(
        f"/api/analyses/{take}/transcript",
        json={"corrections": [{"segmentId": "seg-2", "text": "say my name"}]},
    ).json()
    clock.advance(minutes=1)
    again = client.post(f"/api/analyses/{take}/reanalysis").json()
    assert again["monologueId"] == reference
    make_worker().process_next_job()
    reanalysed = client.get(f"/api/jobs/{again['jobId']}").json()["analysisId"]

    assert corrected["monologueId"] == reference
    assert take_ids(client, reference) == [reanalysed, corrected["analysisId"], take]
    assert take_ids(client, "none") == []
    # Three results of one recording are one take.
    assert monologues(client)[0]["takeCount"] == 1


# --- Order -------------------------------------------------------------------------------


def test_the_monologue_practised_most_recently_comes_first(client, make_worker, clock):
    older = add_monologue(client, make_worker, title="Older")
    clock.advance(hours=1)
    newer = add_monologue(client, make_worker, title="Newer")
    assert [item["monologueId"] for item in monologues(client)] == [newer, older]

    clock.advance(hours=1)
    analyse(client, make_worker, monologueId=older)

    assert [item["monologueId"] for item in monologues(client)] == [older, newer]


# --- Clearing ----------------------------------------------------------------------------


def test_clearing_the_general_history_leaves_every_monologue_take(client, make_worker, data_dir):
    reference = add_monologue(client, make_worker)
    take = analyse(client, make_worker, monologueId=reference, retainAudio="true")
    analyse(client, make_worker, retainAudio="true")

    cleared = client.delete("/api/analyses?monologue=none").json()

    assert cleared["deletedAnalyses"] == 1
    assert take_ids(client) == [take]
    assert len(files_in(data_dir, "audio")) == 1
    assert client.get(f"/api/analyses/{take}/audio").status_code == 200


def test_the_takes_of_one_monologue_can_be_cleared_on_their_own(client, make_worker):
    first = add_monologue(client, make_worker, title="First")
    second = add_monologue(client, make_worker, title="Second")
    analyse(client, make_worker, monologueId=first)
    kept = analyse(client, make_worker, monologueId=second)
    free = analyse(client, make_worker)

    cleared = client.delete(f"/api/analyses?monologue={first}").json()

    assert cleared["deletedAnalyses"] == 1
    assert set(take_ids(client)) == {kept, free}
    assert len(monologues(client)) == 2


# --- Deleting a monologue ----------------------------------------------------------------


def test_deleting_a_monologue_removes_its_reference_its_takes_and_their_recordings(
    client, make_worker, data_dir, session, clock
):
    reference = add_monologue(client, make_worker, retainAudio="true")
    clock.advance(minutes=1)
    corrected = client.post(
        f"/api/analyses/{reference}/transcript",
        json={"corrections": [{"segmentId": "seg-2", "text": "say my name"}]},
    ).json()["analysisId"]
    take = analyse(client, make_worker, monologueId=reference, retainAudio="true")
    client.post(f"/api/analyses/{take}/feedback", json={"category": "wpm_too_high"})
    other = add_monologue(client, make_worker, title="Another", retainAudio="true")
    other_take = analyse(client, make_worker, monologueId=other)
    free = analyse(client, make_worker)

    # Either revision of the reference names the monologue.
    response = client.delete(f"/api/monologues/{corrected}")

    assert response.status_code == 200
    assert response.json() == {"deletedReferences": 2, "deletedTakes": 1}
    assert [item["monologueId"] for item in monologues(client)] == [other]
    assert set(take_ids(client)) == {other_take, free}
    for gone in (reference, corrected, take):
        assert client.get(f"/api/analyses/{gone}").status_code == 404
    # Only the other monologue's recording is left on disk.
    assert len(files_in(data_dir, "audio")) == 1
    assert session.execute(select(func.count()).select_from(Feedback)).scalar_one() == 0
    remaining_jobs = session.execute(select(Job.analysis_id)).scalars().all()
    assert set(remaining_jobs) == {other, other_take, free}


def test_deleting_an_unknown_monologue_is_a_404(client, make_worker):
    free = analyse(client, make_worker)

    for wrong in ("no-such-monologue", free):
        response = client.delete(f"/api/monologues/{wrong}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "monologue_not_found"
    assert take_ids(client) == [free]


def test_a_monologue_is_not_deleted_while_a_take_of_it_is_still_waiting(
    client, make_worker, data_dir
):
    reference = add_monologue(client, make_worker)
    waiting = submit(client, monologueId=reference)

    response = client.delete(f"/api/monologues/{reference}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "monologue_busy"
    assert len(monologues(client)) == 1
    assert len(files_in(data_dir, "uploads")) == 1

    make_worker().process_next_job()
    take = client.get(f"/api/jobs/{waiting['jobId']}").json()["analysisId"]
    assert client.delete(f"/api/monologues/{reference}").json() == {
        "deletedReferences": 1,
        "deletedTakes": 1,
    }
    assert client.get(f"/api/analyses/{take}").status_code == 404


def test_a_failed_take_holding_its_recording_goes_with_the_monologue(
    client, make_worker, data_dir, transcriber
):
    reference = add_monologue(client, make_worker)
    failed = submit(client, monologueId=reference)
    transcriber.error = RuntimeError("the speech model broke")
    make_worker().process_next_job()
    assert client.get(f"/api/jobs/{failed['jobId']}").json()["canRetry"] is True
    assert len(files_in(data_dir, "uploads")) == 1

    assert client.delete(f"/api/monologues/{reference}").status_code == 200

    assert files_in(data_dir, "uploads") == []
    assert client.get(f"/api/jobs/{failed['jobId']}").status_code == 404


# --- A reference deleted on its own ------------------------------------------------------


def test_takes_are_freed_when_the_last_revision_of_their_reference_is_deleted(
    client, make_worker, clock
):
    reference = add_monologue(client, make_worker)
    clock.advance(minutes=1)
    corrected = client.post(
        f"/api/analyses/{reference}/transcript",
        json={"corrections": [{"segmentId": "seg-2", "text": "say my name"}]},
    ).json()["analysisId"]
    take = analyse(client, make_worker, monologueId=reference)

    # One revision is left, so the monologue is still there, under the same ID.
    assert client.delete(f"/api/analyses/{reference}").status_code == 204
    (monologue,) = monologues(client)
    assert (monologue["monologueId"], monologue["referenceId"]) == (reference, corrected)
    assert (monologue["takeCount"], monologue["revisionCount"]) == (1, 1)
    assert take_ids(client, reference) == [take]

    # With the last one gone, the take is an ordinary take and can still be found.
    assert client.delete(f"/api/analyses/{corrected}").status_code == 204
    assert monologues(client) == []
    assert take_ids(client, "none") == [take]
    assert client.get(f"/api/analyses/{take}").json()["monologueId"] is None


def test_clearing_the_references_frees_every_take(client, make_worker):
    reference = add_monologue(client, make_worker)
    take = analyse(client, make_worker, monologueId=reference)

    client.delete("/api/analyses?role=reference")

    assert monologues(client) == []
    assert take_ids(client, "none") == [take]


def test_a_take_whose_monologue_went_while_it_waited_is_stored_as_a_free_take(client, make_worker):
    reference = add_monologue(client, make_worker)
    waiting = submit(client, monologueId=reference)
    assert client.delete(f"/api/analyses/{reference}").status_code == 204

    make_worker().process_next_job()

    take = client.get(f"/api/jobs/{waiting['jobId']}").json()["analysisId"]
    assert client.get(f"/api/analyses/{take}").json()["monologueId"] is None
    assert take_ids(client, "none") == [take]
