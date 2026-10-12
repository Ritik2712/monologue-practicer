"""The voice goal through the API: offered, stored with the job and the result, and kept."""

from sqlalchemy.orm.attributes import flag_modified

from app.coaching.coach import Coach
from app.models import Analysis
from app.pipeline.runner import PipelineDeps
from app.worker import Worker
from tests.conftest import (
    fake_vad,
    steady_pitch,
    steady_resonance,
    wav_bytes,
)

# A tone where the scripted speech is and silence elsewhere. With sound all the way through,
# the background would be as loud as the "voice" and resonance would rightly be withheld.
SPEECH = [(0.5, 4.5), (6.0, 8.0)]


def submit(client, **form) -> dict:
    return client.post(
        "/api/analyses",
        files={"audio": ("take.wav", wav_bytes(9.0, sounding=SPEECH), "audio/wav")},
        data=form,
    )


def analyse(client, worker, **form) -> dict:
    job = submit(client, **form).json()
    worker.process_next_job()
    analysis_id = client.get(f"/api/jobs/{job['jobId']}").json()["analysisId"]
    return client.get(f"/api/analyses/{analysis_id}").json()


def voiced_worker(session_factory, data_dir, clock, transcriber, *, pitch_hz=200.0, spacing=1000.0):
    """A worker that hears a steady voice: 200 Hz, formants 1000 Hz apart, unless told otherwise."""

    def pitch(samples, segments):
        track = steady_pitch(samples, segments)
        return type(track)(track.times, track.hz * (pitch_hz / 200.0))

    deps = PipelineDeps(
        transcriber=transcriber,
        detect_speech=fake_vad(SPEECH),
        measure_pitch=pitch,
        measure_resonance=steady_resonance(spacing),
    )
    return Worker(session_factory, deps, data_dir=data_dir, clock=clock, coach=Coach(None))


def test_the_form_is_offered_the_three_goals(client):
    options = client.get("/api/analysis-options").json()

    assert [goal["id"] for goal in options["voiceGoals"]] == ["none", "lower", "higher"]
    assert options["voiceGoals"][0] == {"id": "none", "label": "No goal", "note": None}
    assert options["voiceGoals"][1]["label"] == "Keep my voice lower"
    assert "not who is speaking" in options["voiceGoalNote"]


def test_a_recording_is_submitted_with_no_goal_unless_one_is_chosen(client, make_worker):
    assert submit(client).json()["voiceGoal"] == "none"
    assert submit(client, voiceGoal="higher").json()["voiceGoal"] == "higher"


def test_an_unknown_goal_is_refused(client):
    response = submit(client, voiceGoal="deeper")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"


def test_the_result_says_where_the_voice_sat_and_keeps_the_goal(
    client, session_factory, data_dir, clock, transcriber
):
    worker = voiced_worker(session_factory, data_dir, clock, transcriber)
    result = analyse(client, worker, voiceGoal="lower")

    voice = result["voiceRange"]
    assert voice["goal"] == "lower"
    assert voice["pitch"] == {
        "valueHz": 200.0,
        "band": "higher",
        "percent": 31,
        "quality": "measured",
    }
    assert voice["resonance"]["band"] == "lower"
    assert voice["marker"] == "mixed"
    assert voice["bands"]["pitch_neutral_from_hz"] == 145.0
    assert result["segments"][0]["voice"]["marker"] == "mixed"

    # The coaching follows the goal: the pitch left the lower range, the resonance did not.
    kinds = {f["id"]: (f["kind"], f["role"]) for f in result["coaching"]["findings"]}
    assert ("voice_pitch", "issue") in kinds.values()
    assert ("voice_resonance", "strength") in kinds.values()
    assert result["coaching"]["corrections"][0]["title"] == "Keep your pitch in the lower range"


def test_the_same_recording_with_no_goal_is_measured_the_same_and_not_judged(
    client, session_factory, data_dir, clock, transcriber
):
    worker = voiced_worker(session_factory, data_dir, clock, transcriber)
    aimed = analyse(client, worker, voiceGoal="lower")
    plain = analyse(client, worker)

    assert plain["voiceRange"]["goal"] == "none"
    assert {**plain["voiceRange"], "goal": "lower"} == aimed["voiceRange"]
    assert plain["metrics"] == aimed["metrics"]
    roles = {f["kind"]: f["role"] for f in plain["coaching"]["findings"]}
    assert (roles["voice_pitch"], roles["voice_resonance"]) == ("context", "context")
    assert all("range" not in c["title"] for c in plain["coaching"]["corrections"])


def test_a_reference_is_measured_but_never_has_a_goal(
    client, session_factory, data_dir, clock, transcriber
):
    worker = voiced_worker(session_factory, data_dir, clock, transcriber)
    job = submit(client, role="reference", voiceGoal="lower").json()
    assert job["voiceGoal"] == "none"
    worker.process_next_job()
    reference = client.get(
        f"/api/analyses/{client.get('/api/jobs/' + job['jobId']).json()['analysisId']}"
    ).json()

    assert reference["voiceRange"]["goal"] == "none"
    assert reference["voiceRange"]["pitch"]["band"] == "higher"


def test_analysing_again_and_correcting_the_words_keep_the_goal_and_the_voice(
    client, session_factory, data_dir, clock, transcriber
):
    worker = voiced_worker(session_factory, data_dir, clock, transcriber)
    first = analyse(client, worker, voiceGoal="higher", retainAudio="true")

    again = client.post(f"/api/analyses/{first['analysisId']}/reanalysis").json()
    assert again["voiceGoal"] == "higher"
    worker.process_next_job()
    second = client.get(
        f"/api/analyses/{client.get('/api/jobs/' + again['jobId']).json()['analysisId']}"
    ).json()
    assert second["voiceRange"] == first["voiceRange"]

    corrected = client.post(
        f"/api/analyses/{first['analysisId']}/transcript",
        json={"corrections": [{"segmentId": "seg-2", "text": "say my name"}]},
    ).json()
    # The words changed; the sound, and so where the voice sat, did not.
    assert corrected["voiceRange"] == first["voiceRange"]
    assert corrected["segments"][1]["voice"] == first["segments"][1]["voice"]


def test_a_result_stored_before_this_was_measured_still_reads(client, make_worker, session):
    job = submit(client).json()
    make_worker().process_next_job()
    analysis_id = client.get(f"/api/jobs/{job['jobId']}").json()["analysisId"]
    stored = session.get(Analysis, analysis_id)
    # What an earlier version wrote: no voice range, and segments without a voice.
    del stored.result["voiceRange"]
    for segment in stored.result["segments"]:
        del segment["voice"]
    flag_modified(stored, "result")
    session.commit()

    result = client.get(f"/api/analyses/{analysis_id}").json()
    assert result["voiceRange"] is None
    assert result["segments"][0]["voice"] is None
    # Its coaching can still be written, with nothing said about the voice range.
    assert client.post(f"/api/analyses/{analysis_id}/coaching").status_code == 202
    make_worker().process_next_job()
    assert client.get(f"/api/analyses/{analysis_id}").status_code == 200
