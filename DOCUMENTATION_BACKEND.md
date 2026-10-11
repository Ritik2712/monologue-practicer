# Monologue Coach — Backend Documentation

The Python side of the app: the API, the database, the job queue, and the worker that does
the slow work: measuring the audio and getting the coaching written.

- Start with [DOCUMENTATION.md](DOCUMENTATION.md) for the big picture and the glossary.
- **What** is measured in the audio, how the coaching is produced and checked, and why those
  methods were chosen, is in [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md). This file
  covers **how the work is organised**: requests, jobs, files and tables.
- The browser side is in [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md).

Everything described here is built.

**Last updated:** end of Phase 6 (feedback, calibration and revisions: nine new endpoints,
three new tables, four new columns).

## Contents

1. [The three programs](#1-the-three-programs)
2. [Folder structure](#2-folder-structure)
3. [The API list](#3-the-api-list)
4. [Background jobs (and why there is no Celery)](#4-background-jobs-and-why-there-is-no-celery)
   - [4a. Feedback, calibration and revisions](#4a-feedback-calibration-and-revisions)
5. [The database](#5-the-database)
6. [Audio files on disk](#6-audio-files-on-disk)
7. [Settings](#7-settings)
8. [What is and is not written to logs](#8-what-is-and-is-not-written-to-logs)
9. [Backend decisions](#9-backend-decisions)
10. [Tests](#10-tests)

## 1. The three programs

The backend folder contains three things you run. They share one database file and one
data folder, and never talk to each other directly. A fourth program, **Ollama**, is not part
of this project: you install and start it yourself, and only the worker talks to it.

| Program | Command (from `backend/`) | What it does | Runs for |
| --- | --- | --- | --- |
| **API** | `uv run uvicorn app.main:app --reload --port 8000` | Answers the browser's requests. Never does slow work. | As long as you use the app |
| **Worker** | `uv run python -m app.worker` | Takes jobs from the queue one at a time: analyses the audio, then gets the coaching written. | As long as you use audio analysis |
| **Model download** | `uv run python -m app.speech_model download` | Fetches the speech model. The only step that uses the internet. | Once |

```
   Browser
      │  HTTP
      ▼
 ┌─────────┐   reads / writes    ┌───────────────────────┐   reads / writes   ┌──────────┐
 │   API   │ ──────────────────▶ │  SQLite database      │ ◀───────────────── │  Worker  │
 └─────────┘                     │  jobs, analyses,      │                    └──────────┘
      │                          │  worker_state         │                         │
      │  saves upload            └───────────────────────┘        reads, deletes  │
      ▼                                                                            ▼
 ┌──────────────────────────────────────────────────────────────────────────────────────┐
 │  data folder:   uploads/  (waiting to be analysed)      audio/  (kept on request)     │
 └──────────────────────────────────────────────────────────────────────────────────────┘

                                              Worker ── text (transcript + measurements) ──▶ Ollama
                                              Worker ◀── the wording of the coaching ─────── (localhost:11434)
```

The API never calls Ollama. It learns whether the AI model is available the same way it
learns whether the worker is alive: the worker writes it into the database.

Since Phase 6 the database also holds the user's **feedback** and the **calibration** (the
few settings feedback may adjust). The API writes both. The worker only reads the
calibration, once, at the start of each job. Section 4a explains how.

## 2. Folder structure

The generated `.venv/` folder (the private Python environment) is left out.

```
backend/
├── pyproject.toml        Dependencies and tool settings (pytest, ruff)
├── uv.lock               Exact dependency versions (written by uv, not by hand)
├── .python-version       Pins Python 3.12 for this folder
├── alembic.ini           Settings for database migrations
├── app/
│   ├── main.py           Builds the API: CORS, upload size guard, error format, routes
│   ├── config.py         Reads settings from environment variables
│   ├── db.py             Opens the SQLite database
│   ├── dependencies.py   Things endpoints are handed: a database session, the data folder, the time
│   ├── models.py         The database tables, as Python classes
│   ├── schemas.py        The shapes of all JSON sent and received
│   ├── job_queue.py      Every change to a job's status
│   ├── history.py        Listing and deleting stored analyses
│   ├── feedback.py       Saving feedback, and working out what each piece of it does
│   ├── revisions.py      Later results of one recording: corrected transcripts, fresh analyses
│   ├── transcript_correction.py   Works word counts and WPM out again from corrected words
│   ├── wpm_review.py     Lays out what went into a WPM figure the user says looks wrong
│   ├── profiles.py       The delivery profiles and language choices, as text
│   ├── uploads.py        Creating, moving and deleting audio files
│   ├── worker.py         The worker program
│   ├── llm.py            Talks to the local AI model (Ollama). The only file that does
│   ├── speech_model.py   Finds or downloads the speech model
│   ├── routes/
│   │   ├── health.py     GET /api/health
│   │   ├── analyses.py   Submit, read, list and delete analyses; kept audio; form options;
│   │   │                 ask for coaching to be written again
│   │   ├── jobs.py       GET /api/jobs/{id}, POST …/cancel, POST …/retry
│   │   └── feedback.py   Feedback on an analysis; the calibration: read, undo, reset, on/off
│   ├── calibration/      The settings feedback may adjust (explained in the science document)
│   │   ├── registry.py       Which settings are adjustable, and how far
│   │   ├── engine.py         The rules that decide when a setting moves. No database
│   │   └── store.py          Reads the calibration in force, and writes new versions of it
│   ├── comparison/       Setting a take against a reference (explained in the science document)
│   │   ├── compare.py        Pause by pause, phrase by phrase, the biggest differences
│   │   ├── align.py          Lines up the words of the two recordings
│   │   └── settings.py       The thresholds the comparison uses
│   ├── coaching/         Turning measurements into advice (explained in the science document)
│   │   ├── coach.py          Runs the steps below in order; falls back to templates
│   │   ├── findings.py       Measurements -> plain statements of fact, each with a role
│   │   ├── rules.py          Template coaching, used when the AI model cannot be
│   │   ├── prompt.py         What is sent to the AI model, and the shape of its answer
│   │   ├── grounding.py      Checks the model's wording against the measurements
│   │   └── settings.py       The bands behind words such as "fast" and "even"
│   └── pipeline/         The audio analysis itself (explained in the science document)
│       ├── runner.py         Runs the stages in order and assembles the result
│       ├── audio.py          Decodes any audio file to one standard format
│       ├── vad.py            Finds where speech is
│       ├── transcribe.py     Speech to words with timestamps
│       ├── segmentation.py   Speech regions -> segments and pauses
│       ├── metrics.py        Words per minute and pause statistics
│       ├── acoustics.py      Loudness, pitch, emphasis candidates
│       ├── fillers.py        Hesitation sounds
│       ├── waveform.py       The outline of the sound wave, for drawing only
│       ├── settings.py       The thresholds (0.5 s pause, 5 s long silence…)
│       └── errors.py         Errors with a code and a message safe to show
├── migrations/
│   ├── env.py            Tells the migration tool where the database is
│   └── versions/
│       ├── 0001_jobs_analyses_and_worker_state.py   Creates the three tables
│       ├── 0002_coaching.py                         Adds the four coaching columns
│       ├── 0003_references_and_waveforms.py         Adds role, title and the waveform outline
│       └── 0004_feedback_and_calibration.py         Adds feedback, calibration and revisions
├── tests/                See section 10
└── data/                 Created on first run; not in git
    ├── monologue_coach.db    The database
    ├── uploads/              Audio waiting to be analysed
    └── audio/                Audio kept at the user's request
```

Which file to open for which question:

| Question | File |
| --- | --- |
| What does endpoint X do? | `app/routes/` |
| What does the JSON look like? | `app/schemas.py` |
| When can a job be cancelled or retried? | `app/job_queue.py` |
| What does the worker do with a job? | `app/worker.py` |
| How is a number such as WPM calculated? | `app/pipeline/` (and the science document) |
| Why did the coaching say that? | `app/coaching/findings.py` for the facts, `app/coaching/rules.py` for template wording |
| What exactly is sent to the AI model? | `app/coaching/prompt.py` |
| What stops the AI model inventing numbers? | `app/coaching/grounding.py`, `app/coaching/coach.py` |
| How is Ollama called? | `app/llm.py` |
| How is a take compared with a reference? | `app/comparison/compare.py`, `app/comparison/align.py` |
| What is drawn in the waveform picture? | `app/pipeline/waveform.py` |
| When is an audio file deleted? | `app/uploads.py`, `app/job_queue.py`, `app/history.py` |
| Which setting does a piece of feedback count towards? | `app/feedback.py` (`classify`) |
| When does feedback move a setting, and by how much? | `app/calibration/engine.py` |
| Which settings can move at all, and within what range? | `app/calibration/registry.py` |
| What do undo and reset do? | `app/calibration/store.py` |
| How is WPM worked out again after a transcript correction? | `app/transcript_correction.py` |
| How does a recording get a second result? | `app/revisions.py` |
| What do the delivery profiles say? | `app/profiles.py` |
| What columns does a table have? | `app/models.py` |

## 3. The API list

An **API endpoint** is an address the frontend can send a request to. Each one has a method
(`GET` to read, `POST` to create or do something) and a path. While the API is running, an
interactive version of this list is at `http://localhost:8000/docs`.

### Built

| Method | Path | What it does | Defined in |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Is the API up, can it reach the database, is a worker alive, is the speech model present, is the AI model available | `routes/health.py` |
| `POST` | `/api/analyses` | Accepts a recording (a take or a reference), queues a job, answers at once with the job | `routes/analyses.py` |
| `GET` | `/api/jobs/{jobId}` | Where a job has got to. Made to be polled | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/cancel` | Asks for a job to stop | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/retry` | Puts a failed job back in the queue | `routes/jobs.py` |
| `GET` | `/api/analyses/{analysisId}` | The stored result of a finished analysis, with its coaching | `routes/analyses.py` |
| `POST` | `/api/analyses/{analysisId}/coaching` | Queues a job that has the AI model write this analysis's coaching again | `routes/analyses.py` |
| `GET` | `/api/analysis-options` | What the form offers: profiles, languages, upload limits | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/comparison/{referenceId}` | Sets an analysis against a reference recording | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/waveform` | The outline of the recording's sound wave, for drawing | `routes/analyses.py` |
| `GET` | `/api/analyses` | Past takes, newest first, with their headline numbers; or the reference recordings with `?role=reference` | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}` | Deletes one analysis (take or reference), its kept recording and its job | `routes/analyses.py` |
| `DELETE` | `/api/analyses` | Clears the history of takes; or the references with `?role=reference` | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/audio` | The recording itself, if it was kept | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}/audio` | Deletes only the kept recording | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/feedback` | The feedback given on one analysis, with what each piece does, and the calibration | `routes/feedback.py` |
| `POST` | `/api/analyses/{analysisId}/feedback` | Saves one piece of feedback. Adjusts a setting if this completes a run of reports that agree | `routes/feedback.py` |
| `DELETE` | `/api/feedback/{feedbackId}` | Takes one piece of feedback back | `routes/feedback.py` |
| `GET` | `/api/calibration` | The settings in force: every value, its range, what changed it and why | `routes/feedback.py` |
| `POST` | `/api/calibration/undo` | Puts back the value the most recent adjustment replaced | `routes/feedback.py` |
| `POST` | `/api/calibration/reset` | Returns every setting to its default | `routes/feedback.py` |
| `PUT` | `/api/calibration/adaptive` | Switches automatic adjustment on or off | `routes/feedback.py` |
| `POST` | `/api/analyses/{analysisId}/transcript` | Stores a new revision of a take with corrected words, with WPM worked out again | `routes/analyses.py` |
| `POST` | `/api/analyses/{analysisId}/reanalysis` | Queues a fresh analysis of the kept recording, with the settings in force now | `routes/analyses.py` |

Submitting, jobs, results and coaching are tested in `tests/test_api.py`; lists, deleting,
kept audio, references, waveforms and the comparison in `tests/test_history_api.py`;
feedback and calibration in `tests/test_feedback_api.py`; corrected transcripts and fresh
analyses in `tests/test_revisions.py`.

### `GET /api/health`

```json
{ "status": "ok", "database": "ok", "worker": "running", "speechModel": "ready",
  "coach": "ready", "coachModel": "llama3.1:8b" }
```

- `status` and `database` describe the API itself.
- `worker` is `running` if a worker has reported in during the last 15 seconds.
- `speechModel` is what the worker last reported: `ready`, `missing`, or `unknown` if no
  worker has ever started. The API does not check the model itself, so that it never has to
  load the heavy speech libraries.
- `coach` is what the worker last found out about the AI model, and `coachModel` is its name:

| `coach` | Meaning |
| --- | --- |
| `ready` | Ollama is running and has the model installed |
| `not_running` | Ollama did not answer |
| `model_missing` | Ollama is running but the model is not installed in it |
| `not_local` | `OLLAMA_BASE_URL` points at another machine, which is refused |
| `off` | AI coaching is switched off with `AI_COACHING=off` |
| `unknown` | No worker has ever started |

`coach` never makes `status` anything but `ok`. Coaching is optional: without the AI model
an analysis still succeeds and its coaching comes from templates.

### `POST /api/analyses`

Sent as a form (`multipart/form-data`), because it carries a file.

| Field | Required | Values | Meaning |
| --- | --- | --- | --- |
| `audio` | yes | a file | The recording |
| `profile` | no | `walter_white`, `joker`, `thomas_shelby`, `custom` (default) | The delivery profile. Stored now, used for coaching in Phase 4 |
| `language` | no | `auto` (default), `en`, `hi`, `hinglish` | What language to expect |
| `retainAudio` | no | `true` / `false` (default) | Keep the recording after analysis |
| header `Idempotency-Key` | no | any text up to 128 characters | See below |

What happens, in order (nothing here is slow):

1. If the `Idempotency-Key` was used before, the earlier job is returned and the new upload
   is ignored.
2. The file type is checked by its extension or content type.
3. The file is copied to `data/uploads/<jobId>.<ext>`, counting bytes as it goes.
4. The file's header is opened to confirm it really contains audio and to read its length.
5. A row is added to the `jobs` table with status `queued`.
6. The job is returned.

| Answer | When |
| --- | --- |
| `202 Accepted` + the job | A new job was queued |
| `200 OK` + the earlier job | The same `Idempotency-Key` was sent before |
| `400` `empty_file` | The file has no content |
| `413` `file_too_large` | Bigger than `MAX_UPLOAD_MB` (50 MB) |
| `413` `audio_too_long` | Longer than `MAX_AUDIO_MINUTES` (10 minutes) |
| `415` `unsupported_type` | Not an audio file type |
| `415` `unreadable_audio` / `no_audio_stream` | Named like audio but cannot be decoded |
| `422` `invalid_request` | A field is missing or has a value that is not allowed |

Whenever a request is refused, the uploaded file is deleted before answering.

**Takes and references.** Two more optional fields say what the recording is for:

| Field | Values | Meaning |
| --- | --- | --- |
| `role` | `take` (default) or `reference` | A take is one of your own attempts. A reference is a recording to compare takes with |
| `title` | Text, up to 120 characters kept | The name a reference is listed under. If empty, the file's name without its ending. Ignored for a take |

A reference is checked, queued and measured exactly like a take. The differences are that it
gets no coaching (its job ends after `measuring_audio`), it is listed separately, and
clearing the history of takes does not touch it.

**The `Idempotency-Key`.** "Idempotent" means doing something twice has the same effect as
doing it once. The browser makes up a random key for each recording it submits. If the
button is clicked twice, or the request is sent again after a network hiccup, the same key
arrives twice and only one job is created. A new recording must use a new key.

### `GET /api/jobs/{jobId}`

```json
{
  "jobId": "104a71305a78446ea62279bb51bdf7c2",
  "kind": "analysis",
  "status": "running",
  "stage": "transcribing",
  "cancelRequested": false,
  "error": null,
  "analysisId": null,
  "canRetry": false,
  "canCancel": true,
  "queuePosition": null,
  "workerAlive": true,
  "attempt": 1,
  "createdAt": "2026-10-10T19:29:13.815636Z",
  "startedAt": "2026-10-10T19:29:15.102000Z",
  "finishedAt": null
}
```

| Field | Meaning |
| --- | --- |
| `kind` | `analysis` (measure a recording) or `coaching` (only write an existing analysis's coaching again) |
| `status` | `queued`, `running`, `succeeded`, `failed` or `cancelled` |
| `stage` | Only while running: `preparing_audio`, `detecting_speech`, `transcribing`, `measuring_audio`, `generating_feedback`. A coaching job only ever has the last one |
| `cancelRequested` | `true` between asking a running job to stop and the worker actually stopping |
| `error` | Only when failed: `{ code, message, retryable }` |
| `analysisId` | Where to fetch the result. An analysis job has it once it has succeeded; a coaching job has it from the start |
| `canRetry`, `canCancel` | Whether those buttons should be offered right now |
| `queuePosition` | Only while queued: how many jobs are ahead |
| `workerAlive` | `false` means no worker is running, so nothing will progress |
| `attempt` | How many times a worker has started this job |

There is no percentage. The pipeline cannot honestly say it is "40% done", so it reports the
stage it is in and nothing more.

### `POST /api/jobs/{jobId}/cancel`

| Job is… | Result |
| --- | --- |
| `queued` | Cancelled immediately; its audio is deleted |
| `running` | Marked `cancelRequested`. Still `running` until the worker reaches a safe stopping point, then `cancelled` |
| `failed` | Stays `failed`; the audio that was being kept for a retry is deleted |
| `cancelled` | No change (asking twice is harmless) |
| `succeeded` | `409` `already_finished` |

### `POST /api/jobs/{jobId}/retry`

Only for a `failed` job whose error is marked `retryable` and whose audio is still stored.
The same job goes back to `queued` with the same `jobId`. Otherwise it answers `409` with
`not_failed`, `not_retryable` or `audio_gone`. A failed coaching job is never retryable this
way; asking for the coaching again simply creates a new job.

### `GET /api/analyses/{analysisId}`

The complete result: transcript, segments, pauses, words, metrics, loudness timeline,
warnings, and the settings that produced it. Its contents are described in the science
document. The measurements are stored once and never changed.

Since Phase 5 the result also says what the recording is: `role` (`take` or `reference`)
and, for a reference, its `title`. A reference's result has the same shape as a take's.

The result also carries `coaching`, which is stored separately and can be written again
(it is always empty for a reference):

```json
"coaching": {
  "source": "ai",
  "model": "llama3.1:8b",
  "notice": null,
  "summary": [ { "label": "Pace", "text": "You spoke at 240 WPM while speaking…" } ],
  "findings": [
    { "id": "f1", "kind": "pace", "level": "high", "role": "issue",
      "statement": "You spoke at 240 WPM while speaking (pauses left out). That is fast: over 200 WPM.",
      "evidence": [ { "kind": "metric", "id": "speechActiveWpm", "label": "Speech-active WPM",
                      "startSeconds": null, "endSeconds": null } ] }
  ],
  "corrections": [
    { "findingId": "f1", "title": "Slow Down the Pace", "why": "…", "drill": "…",
      "practise": { "kind": "segment", "id": "seg-1", "label": "Segment 1",
                    "startSeconds": 0.0, "endSeconds": 4.1 } }
  ],
  "working": [ { "findingId": "f3", "note": "…" } ],
  "nextTake": [ "Bring your speaking pace down towards 200 WPM or below." ],
  "caveats": [ "Breaths are not detected, so nothing here is based on breathing. …" ],
  "settings": { "version": 1, "slow_wpm": 140.0, "fast_wpm": 200.0, "…": 0 },
  "generatedAt": "2026-10-11T05:29:42.511762Z",
  "modelSeconds": 20.9
}
```

| Field | Meaning |
| --- | --- |
| `source` | `ai`: worded by the local AI model. `rules`: worded by fixed templates. `none`: too little to coach on (no speech, or under three seconds) |
| `model` | The AI model's name when `source` is `ai` |
| `notice` | `{ code, message }`: why the AI model was not used, or how many of its suggestions were removed. `null` when there is nothing to say |
| `summary` | Four lines written by code: Pace, Pauses, Voice, Clarity |
| `findings` | Every fact the coaching rests on, written by code. `role` is `issue`, `strength` or `context` |
| `corrections` | At most three, most important first. Each points at one finding and one phrase to practise on |
| `working` | What already fits, each pointing at a finding |
| `nextTake` | One measurable target per correction. Always written by template |
| `caveats` | What is uncertain or was not measured. Always written by code |
| `settings` | The bands that produced the wording (see the science document) |
| `modelSeconds` | How long the AI model took, when it was used |

`coaching` is `null` only for a result stored before Phase 4, or if the coaching step broke
in a way nobody planned for (the measurements are saved regardless; see decision B26).

Since Phase 6 a result also carries:

| Field | Meaning |
| --- | --- |
| `settings.calibration_version` | Which version of the user's calibration the result was made with. 1 means the defaults. `settings.min_pause_ms` beside it is the value that version gave |
| `shortSilences` | The silences the detector heard that were too short to count as pauses: `startSeconds`, `endSeconds`, `durationSeconds` and the `segmentId` each lies inside. `null` for a result stored before Phase 6 |
| `revision`, `revisionReason` | 1 and `null` for the first analysis of a recording. A later result is 2, 3, … with `transcript_corrected` or `reanalysed` |
| `revisions` | Every result made from the same recording, oldest first: `analysisId`, `revision`, `reason`, `createdAt`, `calibrationVersion`. Looked up when the result is read, so an older result also lists the ones made after it |
| `coaching.labelsUsed` | The pause labels the coaching took into account, e.g. `{ "pause-2": "accidental" }` |

### `GET /api/analyses/{analysisId}/comparison/{referenceId}`

Sets one analysis (normally a take) against a reference recording. Worked out on the spot
from the two stored results; nothing is stored and neither result is changed, so the same
question always gets the same answer. It took 3 to 31 thousandths of a second in the runs
measured here, which is why it is an ordinary request and not a job.

```json
{
  "takeId": "b677a3f3…", "referenceId": "aa54e918…",
  "referenceTitle": "Breaking Bad: the one who knocks",
  "alignment": { "status": "matched", "matchedWords": 30, "referenceWords": 31,
                 "takeWords": 61, "coverage": 0.968,
                 "note": "97% of the reference's words were found in your take, in the same order, …" },
  "metrics": [ { "metric": "speechActiveWpm", "label": "Speech-active WPM", "unit": "WPM",
                 "digits": 1, "take": 239.6, "reference": 223.1, "difference": 16.5,
                 "estimated": false, "note": null } ],
  "pauses": [ { "status": "both", "afterWords": "…danger, Skylar, I am the danger",
                "reference": { "pauseId": "pause-1", "startSeconds": 3.102,
                               "endSeconds": 4.706, "durationSeconds": 1.604 },
                "take": { "pauseId": "pause-3", "startSeconds": 8.606,
                          "endSeconds": 11.234, "durationSeconds": 2.628 },
                "differenceSeconds": 1.02,
                "referencePlay": { "startSeconds": 1.602, "endSeconds": 6.206 },
                "takePlay": { "startSeconds": 7.106, "endSeconds": 12.734 } } ],
  "phrases": [ { "referenceSegmentId": "seg-1",
                 "text": "I am not in danger, Skylar, I am the danger.",
                 "coverage": 0.9, "comparable": true, "referenceWpm": 208.3, "takeWpm": 248.6,
                 "differenceWpm": 40.3, "differenceRatio": 0.193,
                 "referencePlay": { "startSeconds": 0.0, "endSeconds": 3.102 },
                 "takePlay": { "startSeconds": 5.14, "endSeconds": 8.34 } } ],
  "differences": [ { "kind": "pause_missing",
                     "statement": "The reference pauses for 6.1 seconds after “No”. You did not pause there.",
                     "referencePlay": { "…": 0 }, "takePlay": { "…": 0 } } ],
  "caveats": [ "Loudness itself is not compared. …" ],
  "settings": { "version": 1, "matched_coverage": 0.6, "…": 0 }
}
```

| Field | Meaning |
| --- | --- |
| `alignment` | How well the two transcripts could be lined up. `status` is `matched`, `partial`, `unmatched` or `no_words` |
| `metrics` | Fourteen whole-recording figures side by side. `difference` is take minus reference |
| `pauses` | One row per pause. `status` is `both`, `reference_only`, `take_only` or `unplaced` |
| `phrases` | One row per phrase of the reference, with the pace of the same words in the take |
| `differences` | At most five, largest first, each a sentence written by code |
| `…Play` | The stretch of each recording to play to hear that spot |
| `caveats` | What is not compared, and warnings about either recording |
| `settings` | The thresholds used |

`pauses` and `phrases` are empty when `alignment.status` is `unmatched` or `no_words`.

Errors: `404` `analysis_not_found`; `404` `reference_not_found` if the second ID is not a
reference (one of your own takes cannot stand in for one); `400` `same_recording`.

Since Phase 6 the comparison also has `settingsNote`. It is `null` when the two recordings
were analysed with the same minimum pause. Otherwise it is a sentence saying so, with both
values, because their pauses and phrases are then not cut the same way.

### `GET /api/analyses/{analysisId}/waveform`

```json
{ "durationSeconds": 17.063, "secondsPerPoint": 0.0085625,
  "minimum": [-0.012, -0.341, "…"], "maximum": [0.015, 0.402, "…"] }
```

At most 2,000 points. Each holds the lowest and highest sample of its stretch of the
recording, on a scale where 1.0 is the loudest a recording can be. It is a picture for the
screen: nothing is measured from it, and it is not part of the result returned by
`GET /api/analyses/{id}`, so a screen that never asks for it never receives it. About 21 KB
for a 17-second recording.

`404` `waveform_not_stored` for a recording analysed before Phase 5.

### `POST /api/analyses/{analysisId}/coaching`

Asks for an analysis's coaching to be written again by the AI model. No body. Like
submitting a recording, it answers at once (`202`) with a job to poll:

```json
{ "jobId": "ff51d26deeb047e39b5bbcb587121a1a", "kind": "coaching", "status": "queued",
  "analysisId": "8a890e376ab44ebd8f9c41d8d4ecc195", "…": "…" }
```

- No audio is needed: the job works from the stored measurements, so it works even when the
  recording was not kept.
- If a coaching job for this analysis is already queued or running, that job is returned
  with `200` instead of a second one being created.
- If the AI model can answer, the stored coaching is replaced. If it cannot, the job
  **fails** with the reason (`not_running`, `model_missing`, `timeout`, `ungrounded`,
  `nothing_to_correct`, …) and the coaching that was already there is left as it was.
- `404` `analysis_not_found` for an unknown ID.

### `POST /api/analyses/{analysisId}/feedback`

Saves one piece of feedback on an analysis of one of your own takes. The body is JSON:

```json
{ "category": "pause_missed", "targetId": "seg-1", "atSeconds": 2.78, "note": "a breath there" }
```

| Field | Meaning |
| --- | --- |
| `category` | One of the ten in the table below |
| `targetId` | What it is about: a pause (`pause-2`), a segment (`seg-3`), or the finding a correction is about (`f4`). Left out for the whole recording |
| `atSeconds` | Where in the recording, for a missed pause |
| `note` | Optional, up to 280 characters. Leaving it out keeps a note that is already there; an empty string clears it |

| Category | About | What it does |
| --- | --- | --- |
| `pause_intentional`, `pause_accidental` | A pause | A **label**: changes how the coaching reads the pause. Counts towards no setting |
| `pause_false` | A pause | "Not a pause: I was still speaking." A **report** towards raising the minimum pause, if the pause is shorter than 800 ms. Otherwise only recorded |
| `split_wrong` | A pause | "Too short to split the phrase here." The same |
| `pause_missed` | A segment and a time | A report towards lowering the minimum pause, if the detector heard a silence of 250 ms or more near that time. Otherwise only recorded |
| `wpm_too_high`, `wpm_too_low` | A segment, or the whole recording | Recorded. Changes no figure. The answer includes a **review** of what went into the WPM |
| `transcript_wrong` | A segment | Recorded. To have the words corrected and WPM worked out again, use the transcript endpoint below |
| `coaching_useful`, `coaching_not_useful` | A correction | A report towards raising or lowering the priority of that kind of correction |

The rules behind this table, and the reasons, are in the science document (section 15).

One row is kept per thing: feedback on the same pause replaces what was said about it
before, and sending the same category again only changes the note. The answer is everything
the screen needs to redraw:

```json
{
  "items": [
    { "id": "…", "category": "pause_missed", "targetKind": "segment", "targetId": "seg-1",
      "atSeconds": 2.78, "note": null, "calibrationVersion": 1,
      "features": { "min_pause_ms": 500, "silence_ms": 324, "silence_start_seconds": 2.618 },
      "effect": "report", "setting": "min_pause_ms", "direction": -1,
      "message": "Counts towards lowering the minimum pause. 1 of the 3 reports needed for lowering it, from 1 of the 2 recordings needed.",
      "review": null }
  ],
  "adjustments": [],
  "calibration": { "version": 1, "state": "calibrating", "…": "see GET /api/calibration" }
}
```

| Field | Meaning |
| --- | --- |
| `items` | Every piece of feedback on this analysis, oldest first |
| `features` | What was measured at the spot the feedback is about, copied from the analysis when the feedback was given |
| `effect` | `label`, `report` (waiting to count), `used` (already counted in an adjustment) or `recorded` (changes nothing by itself) |
| `setting`, `direction` | For a report: the setting it speaks for moving, and which way (+1 raise, −1 lower) |
| `message` | One sentence saying what this feedback does, worded against the calibration as it is now |
| `review` | For the WPM categories: the arithmetic, and one entry each for the words, the speaking time and the word timing |
| `adjustments` | The settings this request changed, each with its reason. Empty nearly every time |

Refusals: `404 analysis_not_found`; `404 unknown_target` (no such pause, phrase or
correction); `409 not_a_take` (feedback is not taken on a reference); `422 outside_target`
(the time is not inside the phrase); `422 invalid_request`.

`GET /api/analyses/{analysisId}/feedback` returns the same shape without saving anything.
`DELETE /api/feedback/{feedbackId}` takes one piece back and returns the same shape. An
adjustment it had already counted towards is not reversed by deleting it; that is what undo
is for.

### `GET /api/calibration`

The settings in force, and how they got there.

```json
{
  "version": 2, "adaptive": true, "state": "adjusted",
  "summary": "1 setting has moved from the defaults, on the strength of 3 reports. …",
  "feedbackCount": 5, "pendingReportCount": 0,
  "settings": [
    { "name": "min_pause_ms", "group": "analysis", "label": "Minimum pause", "unit": "ms",
      "value": 400, "default": 500, "minimum": 250, "maximum": 800, "step": 50,
      "changed": true,
      "pending": { "raiseCount": 0, "lowerCount": 0, "recordings": 0, "needed": 3 },
      "supportingReports": 3, "confidence": "low",
      "status": "Changed from its default of 500 ms. No reports are waiting." }
  ],
  "fixed": [ { "name": "long_silence_ms", "label": "A pause is a “long silence”, …", "value": 5000, "unit": "ms" } ],
  "changes": [
    { "version": 2, "cause": "auto", "setting": "min_pause_ms", "oldValue": 500, "newValue": 400,
      "reason": "Minimum pause lowered from 500 ms to 400 ms after 3 reports of a pause that was missed, from 2 recordings. The silences reported were around 356 ms long.",
      "reportCount": 3, "agreeingCount": 3, "recordingCount": 2, "confidence": "low", "undone": false },
    { "version": 1, "cause": "defaults", "reason": "The defaults the app starts with." }
  ],
  "canUndo": true,
  "rules": { "minReports": 3, "minRecordings": 2, "minAgreement": 0.75, "window": 10, "reversalReports": 5 }
}
```

| Field | Meaning |
| --- | --- |
| `version` | The version new analyses are made with |
| `adaptive` | `false` when the user has switched automatic adjustment off |
| `state` | `calibrating` while every setting is still at its default; `adjusted` otherwise |
| `settings` | The 13 adjustable settings: the minimum pause, and a priority for each of the 12 kinds of correction. Each has explicit bounds |
| `fixed` | The thresholds feedback never changes, shown so that nothing is hidden |
| `changes` | The history, newest first. `cause` is `defaults`, `auto`, `undo` or `reset` |

| Request | What it does | Refused with |
| --- | --- | --- |
| `POST /api/calibration/undo` | Adds a version that puts back the value the most recent adjustment replaced | `409 nothing_to_undo` |
| `POST /api/calibration/reset` | Adds a version with every default, and sets aside the reports that were waiting | `409 already_default` |
| `PUT /api/calibration/adaptive` with `{ "enabled": false }` | Switches automatic adjustment off. Feedback is still saved; no setting moves. Switching it on again acts on what built up | |

All three answer with the calibration in the shape above.

### `POST /api/analyses/{analysisId}/transcript`

Corrects the words of one or more phrases of a take and stores the outcome as a **new
revision**. It answers `201` with the new result, at once: there is no job, because no
audio is read.

```json
{ "corrections": [ { "segmentId": "seg-1", "text": "You clearly do not know who you are talking to" } ] }
```

Word counts and the three WPM figures are worked out again from the corrected words and
each phrase's own measured length (science document, section 15). Everything measured from
the sound is copied unchanged. The result that was corrected is not modified. The new
revision gets coaching from the fixed rules straight away, with a notice saying the AI
model has not been asked yet.

Refusals: `400 nothing_changed` (the words are the same as before); `404 unknown_target`;
`409 not_a_take`; `404 analysis_not_found`.

### `POST /api/analyses/{analysisId}/reanalysis`

Queues a fresh analysis of this result's **kept** recording, with the settings in force
now, and answers `202` with a job to poll, exactly as an upload does. The job's
`sourceAnalysisId` says which result it started from. The outcome is stored as a further
revision; the earlier result is not changed. Asking again while one is queued or running
returns that job (`200`).

Refused with `409 audio_not_kept` when the recording was not kept.

### `GET /api/analysis-options`

Everything the submission form needs, so that nothing is written twice:

```json
{
  "profiles": [
    {
      "id": "walter_white",
      "name": "Walter White",
      "summary": "Controlled and deliberate. Every phrase sounds decided in advance.",
      "targets": ["A measured, steady pace", "…"],
      "focus": [{ "metric": "paceVariation", "label": "Pace consistency", "looksFor": "…" }],
      "notMeasured": ["Clarity of consonants"]
    }
  ],
  "profileNote": "A profile is a coaching target, not a rule…",
  "languages": [{ "id": "auto", "label": "Detect automatically", "note": null }],
  "limits": { "maxUploadBytes": 52428800, "maxAudioSeconds": 600.0, "acceptedExtensions": [".aac", "…"] }
}
```

The profile texts live in `app/profiles.py`. `focus[].metric` is the JSON name of a real
metric in the result; a test fails if a profile points at a metric that does not exist.

### `GET /api/analyses`

Query parameters: `limit` (1–100, default 20), `offset` (default 0) and `role` (`take` by
default, or `reference`). Takes and references are never mixed in one list. Each item also
carries its `role`, and a reference its `title`.

```json
{ "items": [ { "analysisId": "…", "createdAt": "…", "profile": "joker", "language": "en",
               "durationSeconds": 22.5, "audioRetained": true, "originalFilename": "take2.m4a",
               "metrics": { "speechActiveWpm": { "value": 239.6, "unit": "words/minute",
                                                 "quality": "measured", "note": "…" } },
               "warningCodes": [] } ],
  "total": 14 }
```

Each item is a **summary**: eleven headline metrics, not the transcript or the word list. A
list of twenty stays small, and it is enough to recognise an attempt and to compare two of
them. The full result is one more request away.

### Deleting

| Request | Removes | Keeps |
| --- | --- | --- |
| `DELETE /api/analyses/{id}` | The result, its kept recording, the job that produced it, and the feedback given on it | Everything else, including other revisions of the same recording and any setting the feedback has already moved |
| `DELETE /api/analyses/{id}/audio` | Only the kept recording | The measurements |
| `DELETE /api/analyses` | Every take's result, kept recording and finished job, and any audio a failed take was holding for a retry | Every reference; jobs still queued or running, and their uploads |
| `DELETE /api/analyses?role=reference` | The same, for the references | Every take |

Clearing answers with what it removed: `{ "deletedAnalyses": 2, "deletedJobs": 3 }`.
The single-item deletes answer `204` with no body, or `404` (`analysis_not_found`,
`audio_not_kept`).

### `GET /api/analyses/{analysisId}/audio`

Sends the kept recording with the right content type for its format, and supports
partial requests, which is what lets the browser's player jump to a position. Answers `404`
`audio_not_kept` if the recording was never kept or has been deleted.

### Error format

Every error from every endpoint has the same shape, so the frontend needs one way to show it:

```json
{ "detail": { "code": "file_too_large", "message": "The file is larger than the 50 MB limit." } }
```

`code` is for programs and never changes; `message` is written for a person.

### Planned

Nothing. Every endpoint in the plan is built.

## 4. Background jobs (and why there is no Celery)

### The problem

Analysing audio is slow: a two-minute recording takes about half a minute here, and the AI
model then needs another 20 to 50 seconds to word the coaching. If the API did that work
while the browser waited, the page would hang and a closed tab would lose everything. The
usual fix is a **background job**:

1. The browser uploads the audio. The API saves a "job" and replies immediately with a job ID.
2. A separate program, the **worker**, picks up the job and does the slow work.
3. The browser asks "is job X done yet?" every second or two (this is called polling).
4. When it is done, the browser fetches the result.

### What Celery is

Celery is a popular Python library for exactly this. It needs a **broker**, usually Redis,
which is a separate server that holds the queue of jobs. So a Celery setup means four things
running: frontend, API, Redis, and one or more Celery workers.

### What this project uses instead

**This project does not use Celery or Redis.**

- **The queue is a database table.** A job waiting to be processed is simply a row in the
  `jobs` table whose `status` is `queued`. There is no queue server.
- **The worker is a small Python program** (`app/worker.py`) that loops: take the oldest
  queued job, run it, save the result, repeat. One job at a time.

The reasons are in decision [B2](#b2-background-jobs-a-sqlite-job-table-and-one-worker-not-celery--redis).

### The life of a job

```
                 worker takes it              pipeline finished
   ┌────────┐ ──────────────────▶ ┌─────────┐ ─────────────────▶ ┌───────────┐
   │ queued │                     │ running │                    │ succeeded │
   └────────┘ ◀────────────────── └─────────┘                    └───────────┘
     │   ▲      worker stopping,      │   │
     │   │      or it crashed and     │   │  something went wrong
     │   │      the job is recovered  │   ▼
     │   │                            │  ┌────────┐
     │   └────────── retry ───────────┼─ │ failed │
     │                                │  └────────┘
     │  cancel                        │  cancel requested,
     ▼                                ▼  then the worker stops
   ┌───────────┐ ◀────────────────────┘
   │ cancelled │
   └───────────┘
```

While a job is `running`, its `stage` says what the worker is doing:

| Stage | What is happening | Typical time for 2 minutes of audio |
| --- | --- | --- |
| `preparing_audio` | Decoding the file | under a second |
| `detecting_speech` | Finding where speech is | under a second |
| `transcribing` | Turning speech into words | about 20 seconds |
| `measuring_audio` | Loudness, pitch, pauses, rates | a few seconds |
| `generating_feedback` | Writing the coaching: findings, the AI model, checks | 20 to 50 seconds with the AI model (it does not depend much on the recording's length); under a second from templates |

**Two roles.** An analysis job is for a `take` or a `reference`. A reference job runs the
first four stages and stops: it has no `generating_feedback` stage and never calls the AI
model. On this machine a 133-second reference took 24.6 seconds; the same recording as a
take, with AI coaching, took 72.8.

**Two kinds of job.** Everything above describes an `analysis` job. A `coaching` job is the
small one created by `POST /api/analyses/{id}/coaching`: it has no audio, goes straight to
`generating_feedback`, and replaces only the coaching of an analysis that already exists.
Both kinds sit in the same table, wait in the same queue and are run by the same worker, one
at a time, so the speech model and the AI model are never working at the same moment.

### The request and the worker, step by step

```
 Browser                API                  jobs table              Worker
    │  upload audio      │                       │                      │
    ├───────────────────▶│  insert row "queued"  │                      │
    │                    ├──────────────────────▶│                      │
    │  { jobId }         │                       │   "any queued job?"  │
    │◀───────────────────┤                       │◀─────────────────────┤
    │                    │                       │   mark "running"     │
    │  status of jobId?  │                       │◀─────────────────────┤
    ├───────────────────▶│  read row             │   stage updates,     │  decode,
    │  "running:         ├──────────────────────▶│   heartbeat          │  detect speech,
    │   transcribing"    │                       │◀─────────────────────┤  transcribe,
    │◀───────────────────┤                       │   store result,      │  measure
    │  status of jobId?  │                       │   mark "succeeded"   │
    ├───────────────────▶│                       │◀─────────────────────┤
    │  "succeeded",      │                       │                      │
    │   analysisId       │                       │                      │
    │◀───────────────────┤                       │                      │
    │  GET analysis      │                       │                      │
    ├───────────────────▶│                       │                      │
```

What `Worker.process_next_job()` in `app/worker.py` does:

1. **Claim.** Ask `job_queue.claim_next_job()` for the oldest queued job. This marks it
   `running` and adds one to `attempt`. If the queue is empty, wait one second and ask again.
2. **Run.** Call `pipeline.runner.run_analysis()` on the job's audio file, handing it two
   functions:
   - `on_stage(name)` writes the current stage to the job row;
   - `check()` is called by the pipeline between steps. It looks at the job row and stops
     the run if cancellation was requested or the worker is shutting down.
3. **Coach** (takes only). Set the stage to `generating_feedback` and call
   `Coach.generate()` on the measurements. This step cannot fail the job: if the AI model is unavailable the coaching
   comes from templates, and if the step itself breaks the result is saved without coaching.
4. **Finish**, in exactly one of these ways:

| What happened | Job becomes | Audio file |
| --- | --- | --- |
| The pipeline returned a result | `succeeded`; the result and its coaching are stored in `analyses` | Deleted, or moved to `data/audio/` if `retainAudio` was set |
| Cancellation was requested | `cancelled` | Deleted |
| The worker is shutting down | `queued` again; the attempt is not counted | Kept |
| An expected failure (`PipelineError`) such as unreadable audio | `failed` with that error's code and message | Deleted, unless the error is retryable |
| Any other error | `failed` with code `unexpected_error` | Kept for a retry |

For a **coaching job**, step 2 is replaced by reading the stored measurements, and the
endings are different:

| What happened | Job becomes | Stored coaching |
| --- | --- | --- |
| The AI model answered and its answer passed the checks | `succeeded` | Replaced |
| The AI model could not be used, or nothing survived the checks | `failed` with that reason; never retryable | Left as it was |
| Cancellation was requested | `cancelled` | Left as it was |
| The worker is shutting down | `queued` again | Left as it was |
| The analysis was deleted meanwhile | `failed` with code `analysis_gone`, or simply gone with it | — |

### Cancellation is cooperative

A running job is never killed from outside. Cancelling sets a flag; the pipeline checks that
flag at **safe points** — between stages, and between each 30-second window of
transcription — and stops itself there. That is why the status stays `running` with
`cancelRequested: true` for a moment: the app does not claim a job is cancelled until it
really has stopped. Measured on two-minute recordings, that took 2.6 and 4.2 seconds. It can
take longer when the recogniser is redoing a difficult window (see the science document,
decision S9), because a window is never interrupted half-way.

During `generating_feedback` the AI model's answer arrives in small pieces, and the flag is
checked between pieces, at most once a second. Cancelling closes the connection, and Ollama
stops generating when its caller hangs up. Measured once: a coaching job cancelled 8 seconds
into the model's answer was `cancelled` within 1 second. The one stretch that cannot be
interrupted is the wait for the first piece, while Ollama loads the model and reads the
prompt (about 6 to 14 seconds in the runs measured here).

### Heartbeats: how anyone knows the worker is alive

Every 3 seconds, a small background thread in the worker writes the current time into:

- the `worker_state` table → the API uses it for `worker` in the health check and for
  `workerAlive` in every job status. The same row carries what the worker knows about the
  speech model and the AI model. The worker asks Ollama "which models are installed?" at
  most every 15 seconds, a request that costs Ollama nothing;
- the `heartbeat_at` column of the job it is working on → proof that the job still has a
  worker.

If the heartbeat is more than 15 seconds old, the API reports the worker as not running.

### What happens if the worker crashes

A crashed worker cannot update anything, so its job is left saying `running`. Two things
stop that from stranding the page:

- **Straight away:** job statuses report `workerAlive: false`, so the page can say "the
  worker is not running" instead of spinning forever.
- **When a worker starts again:** before taking new work, it looks for jobs still marked
  `running`. Since only one worker may run, any such job has lost its worker.

| The orphaned job… | Becomes |
| --- | --- |
| had a cancel request | `cancelled` |
| still has what it needs (its audio; for a coaching job, its analysis) and has been started fewer than `MAX_JOB_ATTEMPTS` (2) times | `queued` again |
| has already used its attempts, or has lost its audio or its analysis | `failed` with code `worker_stopped` |

The attempt limit matters: if one particular recording is what crashes the worker, it must
not be retried forever.

A running worker repeats this check every minute for jobs whose heartbeat is over 30
seconds old.

### Only one worker

When a worker starts, it reads `worker_state`. If another worker has reported in during the
last 15 seconds and that process still exists, the new one prints "Another worker is already
running" and exits.

### Stopping the worker

`Ctrl+C` once: the worker finishes the step it is on, puts its job back in the queue (without
using up an attempt) and exits. `Ctrl+C` twice: it stops at once; the job is recovered the
next time a worker starts, as after a crash.

### Housekeeping

At start-up and once a minute the worker also:

- deletes audio that was kept for a retry more than `FAILED_AUDIO_RETENTION_HOURS` (24) ago;
- deletes files in `data/uploads/` that no job refers to and that are over an hour old
  (left behind if the API stopped between saving a file and creating its job).

### Which function does what

| Function (all in `app/job_queue.py`) | Called by | Purpose |
| --- | --- | --- |
| `create_job` | `POST /api/analyses` | Insert a queued job |
| `create_coaching_job` | `POST /api/analyses/{id}/coaching` | Insert a queued coaching job, or return the one already in progress |
| `find_by_idempotency_key` | `POST /api/analyses` | Detect a repeated submission |
| `to_status` | every job endpoint | Build the JSON status |
| `request_cancel` | `POST …/cancel` | Cancel now, or set the flag |
| `retry_job` | `POST …/retry` | Put a failed job back in the queue |
| `claim_next_job` | worker | Take the oldest queued job |
| `set_stage`, `touch_job` | worker | Report progress and heartbeat |
| `is_cancel_requested` | worker (`check`) | Read the cancel flag |
| `complete_job`, `fail_job`, `finish_cancelled`, `release_job` | worker | The four ways a run ends |
| `complete_coaching_job` | worker | Replace an analysis's coaching and mark the coaching job succeeded |
| `recover_orphaned_jobs` | worker | Deal with jobs a dead worker left behind |
| `expire_failed_audio` | worker | Delete audio kept too long |
| `report_worker`, `worker_alive` | worker / API | The worker's own heartbeat |

## 4a. Feedback, calibration and revisions

Phase 6 added three things that are not jobs but lean on the job machinery in places. This
section explains how the work is organised. *Why* a report counts towards a setting, and
the arithmetic of an adjustment, are in the science document (section 15).

### Three words

| Word | Meaning |
| --- | --- |
| **Feedback** | One thing the user said about one analysis: "this pause was accidental", "a pause was missed here", "this correction was not useful". One row in the `feedback` table |
| **Calibration** | The current values of the settings feedback may adjust. One row in `calibration_versions` per state it has ever been in; the newest row is the one in force |
| **Revision** | A later result made from a recording that already has one: after a transcript correction, or a fresh analysis with new settings. A new row in `analyses`, next to the earlier one |

### Saving feedback is one ordinary request

Feedback never waits in the queue. Saving it is a few thousandths of a second of work, so
the API does all of it before it answers:

```
POST /api/analyses/{id}/feedback
        │
        ▼
 1. feedback.classify()       What is this about, what was measured there, and which
        │                     setting (if any) does it speak for moving, and which way?
        ▼                     Decided by ordinary code from the stored analysis.
 2. feedback.save()           One row. Feedback on the same thing replaces the old row.
        │
        ▼
 3. calibration.evaluate()    For every adjustable setting: are there now enough reports
        │                     that agree? If so, write a new calibration version and mark
        ▼                     those reports as used. Nearly always: nothing to do.
 4. answer                    The feedback on this analysis, any adjustment just made,
                              and the calibration as it now stands.
```

Step 1 never changes the analysis. Step 3 never changes an analysis either: an adjustment
only affects recordings analysed *afterwards*.

### Calibration versions are only ever added

```
version 1   defaults                 min pause 500 ms
version 2   auto                     min pause 400 ms     "lowered after 3 reports …"
version 3   undo  (of version 2)     min pause 500 ms
version 4   reset                    every default
```

Nothing in this table is ever edited or deleted, apart from one mark: an adjustment that
has been undone or reset away has `undone_by` set to the version that did it. Because a
version number never means two different things, an analysis that says "made with version
2" can always be explained, however much has changed since.

Whether automatic adjustment is switched on is not a version. It is a single yes/no row in
`calibration_state`: switching it off changes no value, so no result could differ by it.

### How the worker picks the calibration up

The worker never writes calibration. When it claims an analysis job it reads the newest
version once, and uses it for the whole job:

```python
active = calibration.active(session)                 # version 2, min pause 400 ms
analysis_settings = active.analysis_settings(base)   # the pipeline's thresholds
coaching_settings = active.coaching_settings(base)   # the bands and the priorities
```

`analysis_settings` is the usual `AnalysisSettings` with the minimum pause replaced and
`calibration_version` set. The pipeline copies its settings into the result it produces, as
it always has, so the version and the value it gave travel inside the result. A change made
while a job is running affects the next job, not that one.

### Which reports are waiting

A report is waiting to count while its `used_by_version` is empty. When a setting is
adjusted, **every** report waiting on that setting is marked with the new version's
number, whichever way it pointed. Those reports are spent. This is what makes a setting
move one small step at a time: the next step has to be earned by new reports. Undoing the
adjustment does not un-spend them, so the same reports can never bring it straight back.

### A revision is a new row; nothing is overwritten

Every result has a `root_id`: the ID of the first result made from its recording. Results
that share a root are one family, numbered by `revision`.

| How it is made | What happens | Job? |
| --- | --- | --- |
| **Transcript corrected** (`POST …/transcript`) | The API copies the stored result, works the word-based figures out again (`transcript_correction.py`), writes coaching from the fixed rules, and stores it all as a new row. Pause labels are copied to the new row; reports are not, so none is counted twice | No. No audio is read, so it takes a few thousandths of a second |
| **Analysed again** (`POST …/reanalysis`) | The API copies the kept recording into `uploads/` and queues an ordinary analysis job whose `source_analysis_id` points at the result it came from. The worker runs it like any other job. When it finishes, the new row joins the family | Yes: the same queue, polling, cancellation and crash recovery as an upload |

A revision appears in the history as its own row, marked with its number and reason. The
earlier results stay readable, and stay exactly as they were.

### Which function does what

| Function | File | Does |
| --- | --- | --- |
| `classify` | `feedback.py` | Decides what a piece of feedback is about and what it counts towards |
| `save`, `delete`, `list_items` | `feedback.py` | Stores feedback; lists it with what each piece does |
| `pause_labels`, `copy_pause_labels` | `feedback.py` | The labels on an analysis's pauses, for the coaching and for a revision |
| `tally`, `propose`, `next_value` | `calibration/engine.py` | Counts the reports about a setting and works out its new value. No database |
| `active` | `calibration/store.py` | The calibration in force |
| `evaluate` | `calibration/store.py` | Moves every setting whose reports are enough |
| `undo_last`, `reset`, `set_adaptive` | `calibration/store.py` | The three controls on the calibration screen |
| `describe` | `calibration/store.py` | Everything `GET /api/calibration` returns |
| `correct_transcript` | `transcript_correction.py` | A stored result with corrected words → a new result. Pure: no database, no audio |
| `create_corrected`, `create_reanalysis_job` | `revisions.py` | Store a corrected revision; queue a fresh analysis |
| `review` | `wpm_review.py` | The arithmetic and the checks shown when a WPM figure is questioned |

## 5. The database

One SQLite file: `backend/data/monologue_coach.db`, created the first time the migration
command runs. It is listed in `.gitignore`, so it is never committed.

### Tables

**`jobs`** — one row per request to analyse a recording, or to write coaching again.

| Column | Meaning |
| --- | --- |
| `id` | The job ID (32 random hexadecimal characters) |
| `kind` | `analysis` or `coaching`. Added in Phase 4; every earlier row became `analysis` |
| `role` | `take` or `reference`. Added in Phase 5; every earlier row became `take` |
| `title` | The name given to a reference. Empty for a take |
| `status`, `stage` | See section 4 |
| `cancel_requested` | The cooperative-cancel flag |
| `attempt` | Times a worker has started it |
| `idempotency_key` | Unique; blocks duplicate submissions |
| `profile`, `language_hint`, `retain_audio` | What was asked for |
| `original_filename` | The file's display name only, never a path |
| `audio_path` | Where the upload is, relative to the data folder. Empty once deleted, and always empty for a coaching job |
| `error_code`, `error_message`, `error_retryable` | Why it failed |
| `analysis_id` | The result, once succeeded. For a coaching job: the analysis it is for, from the start |
| `source_analysis_id` | For a fresh analysis of a kept recording: the result it started from. Empty otherwise. Added in Phase 6 |
| `created_at`, `updated_at`, `started_at`, `finished_at`, `heartbeat_at` | Times, stored in UTC |

**`analyses`** — one row per successful job.

| Column | Meaning |
| --- | --- |
| `id`, `job_id`, `created_at` | Identity |
| `role`, `title` | `take` or `reference`, and a reference's name. Indexed, because every list asks for one role |
| `profile`, `language`, `duration_seconds` | Copied out of the result for quick listing later |
| `schema_version` | Version of the result's JSON shape |
| `settings_version` | Version of the app's default thresholds |
| `calibration_version` | Version of the user's calibration that was in force. Added in Phase 6; every earlier row became 1, the defaults |
| `root_id` | The ID of the first result made from the same recording. A first result's root is itself. Indexed |
| `revision`, `revision_reason` | 1 and empty for a first result. 2, 3, … with `transcript_corrected` or `reanalysed` for a later one, which is always a new row and never written over an earlier one |
| `result` | The whole measured result, as JSON. Written once |
| `coaching` | The coaching for this result, as JSON. Can be replaced by a coaching job. Empty for results from before Phase 4 |
| `waveform` | The outline of the sound wave, as JSON, for drawing only. Read by no measurement. Empty for results from before Phase 5 |
| `audio_path` | Only if the recording was kept |

**`worker_state`** — a single row.

| Column | Meaning |
| --- | --- |
| `pid` | The worker's process number |
| `started_at`, `heartbeat_at` | When it started and when it last reported |
| `speech_model`, `speech_model_ready` | Which model, and whether it is on disk |
| `coach_model`, `coach_status` | Which AI model, and what the worker last found: `ready`, `not_running`, `model_missing`, `not_local` or `off` |

**`feedback`** — one row per thing the user said about an analysis. Added in Phase 6.

| Column | Meaning |
| --- | --- |
| `id`, `created_at`, `updated_at` | Identity and times |
| `analysis_id` | The analysis it is about. Deleting the analysis deletes the row |
| `recording_id` | The root of that analysis, so reports can be counted per recording however many revisions it has |
| `slot` | What it is about, e.g. `pause:pause-2`. Unique per analysis: one row per thing |
| `category`, `target_kind`, `target_id`, `at_seconds` | What was said, and about what |
| `note` | The optional note, up to 280 characters |
| `calibration_version` | The calibration version that produced the analysis it is about |
| `features` | What was measured at that spot, as JSON, copied when the feedback was given |
| `setting`, `direction`, `evidence` | For a report: the setting it speaks for moving, which way, and the measurement behind it (a length in milliseconds). Empty for a label or a record |
| `used_by_version` | The calibration version that counted this report. Empty while it is waiting |

**`calibration_versions`** — one row per state the adjustable settings have been in. Rows
are only ever added.

| Column | Meaning |
| --- | --- |
| `version` | 1, 2, 3 … The highest is the calibration in force |
| `created_at`, `cause` | When, and why it exists: `defaults`, `auto`, `undo` or `reset` |
| `values` | Every adjustable setting and its value in this version, as JSON |
| `setting`, `old_value`, `new_value` | What changed, for `auto` and `undo` |
| `reason` | The sentence shown to the user, written when the version was made |
| `report_count`, `agreeing_count`, `recording_count` | How many reports were looked at, how many agreed, from how many recordings |
| `undone_by` | The later version that undid this adjustment or reset it away. Empty while it is in effect |

**`calibration_state`** — a single row: `adaptive_enabled`, and when it last changed.

### Migrations

Tables are never created by hand. Every change to the structure is a **migration**: a
numbered script in `migrations/versions/`. Running `uv run alembic upgrade head` applies any
that have not run yet, so every copy of the database ends up with the same structure.

To change a table: edit `app/models.py`, then run
`uv run alembic revision --autogenerate -m "what changed"`, read the generated file, and run
`uv run alembic upgrade head`. The test in `tests/test_migrations.py` fails if `models.py`
and the migrations ever disagree.

| Migration | What it does |
| --- | --- |
| `0001_jobs_analyses_and_worker_state` | Creates the three tables |
| `0002_coaching` | Adds `jobs.kind`, `analyses.coaching`, `worker_state.coach_model` and `worker_state.coach_status`. Existing rows are kept: old jobs become kind `analysis`, old results simply have no coaching |
| `0003_references_and_waveforms` | Adds `role` and `title` to `jobs` and `analyses`, and `analyses.waveform`. Existing rows are kept: everything stored so far becomes a `take`, with no waveform |
| `0004_feedback_and_calibration` | Creates `feedback`, `calibration_versions` and `calibration_state`. Adds `jobs.source_analysis_id` and, to `analyses`, `calibration_version`, `root_id` and `revision_reason`. Existing rows are kept: every stored result becomes calibration version 1 and the first result of its own recording |

**After updating the code to a new phase, run `uv run alembic upgrade head` once.** Until then
the API reports `"database": "error"`, because the code expects columns the file does not
have yet.

### SQLite settings

`db.py` switches on three SQLite settings every time it connects:

| Setting | Why |
| --- | --- |
| `journal_mode=WAL` | Lets the API read while the worker writes. They are separate programs sharing one file. |
| `busy_timeout=5000` | If the file is briefly locked by the other program, wait up to 5 seconds instead of failing at once. |
| `foreign_keys=ON` | Makes SQLite enforce links between tables (it does not by default). |

## 6. Audio files on disk

All file handling is in `app/uploads.py`. Nothing else creates or deletes audio.

| Moment | What happens to the file |
| --- | --- |
| Upload accepted | Saved as `data/uploads/<jobId>.<ext>` |
| Upload refused (wrong type, too big, unreadable) | Deleted before the API answers |
| Job succeeded | Deleted — or moved to `data/audio/<analysisId>.<ext>` if `retainAudio` was set |
| Job cancelled | Deleted |
| Job failed, and a retry cannot help | Deleted |
| Job failed, but a retry could work | Kept, until the retry succeeds, the job is discarded, or 24 hours pass |
| A file no job refers to, over an hour old | Deleted by the worker's housekeeping |
| The user deletes an analysis, or only its recording | The kept file is deleted |
| A transcript is corrected and the recording was kept | The new revision gets `data/audio/<newAnalysisId>.<ext>`: a second name for the same file on disk (a hard link), which takes no extra space. Deleting either leaves the other playable. Where the disk cannot do that, the file is copied |
| A kept recording is analysed again | It is copied to `data/uploads/<jobId>.<ext>`, so that nothing the job does to its upload can touch the kept recording. When the job succeeds the copy becomes the new revision's kept recording; if it is cancelled or fails for good, the copy is deleted |
| The user clears all history | Every kept file is deleted, and any upload a failed job was holding |

Paths in the database are relative to the data folder, and `uploads.absolute()` refuses any
path that would lead outside it.

## 7. Settings

All optional. Defaults work with no `.env` file at all. They are read once, in
`app/config.py`, when a program starts.

| Variable | Default | Meaning |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///<repo>/backend/data/monologue_coach.db` | Where the database is |
| `DATA_DIR` | `<repo>/backend/data` | Where audio files go |
| `FRONTEND_ORIGINS` | none | Extra allowed origins on top of `localhost` |
| `MAX_UPLOAD_MB` | `50` | Largest upload |
| `MAX_AUDIO_MINUTES` | `10` | Longest recording |
| `WHISPER_MODEL` | `small` | Speech model |
| `WHISPER_COMPUTE_TYPE` | `int8` | How the model's numbers are held in memory |
| `FAILED_AUDIO_RETENTION_HOURS` | `24` | How long audio is kept for a retry |
| `MAX_JOB_ATTEMPTS` | `2` | Automatic restarts after a worker crash |
| `WORKER_POLL_SECONDS` | `1` | How often an idle worker looks for work |
| `LOG_LEVEL` | `INFO` | `DEBUG` adds error tracebacks |
| `AI_COACHING` | `on` | `off` never calls the AI model; coaching then always comes from templates |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama listens. Must be on this computer (`localhost`, `127.0.0.1` or `::1`); anything else is refused |
| `OLLAMA_MODEL` | `llama3.1:8b` | The AI model, as named in `ollama list`. It must already be installed |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | How long one answer from the model may take |
| `OLLAMA_CONTEXT_TOKENS` | `8192` | How much text the model takes in at once. Long transcripts are cut to fit |

The audio thresholds (what counts as a pause, and so on) are not environment variables.
They live in `app/pipeline/settings.py`, and the coaching bands (what counts as "fast" or
"even") in `app/coaching/settings.py`. Both are described in the science document.

Those two files hold the **defaults**. The few values feedback may adjust (the minimum
pause, and a priority per kind of correction) have their current value in the database, in
`calibration_versions`, and their allowed range in `app/calibration/registry.py`. They are
not in `.env` on purpose: see decision B50.

## 8. What is and is not written to logs

The worker prints lines like these, and nothing more:

```
10:58:43 INFO Worker ready. Speech model: small.
10:58:43 INFO AI coaching ready. Language model: llama3.1:8b.
10:58:48 INFO analysis job 187e5af2 started (attempt 1)
10:58:48 INFO job 187e5af2: transcribing
10:58:57 INFO job 187e5af2: generating_feedback
10:59:27 INFO job 187e5af2 succeeded in 39.0s
```

When the AI model is not used, one line says why, by code only: `language model not used:
not_running`. When its answer fails a check, a line says how many problems there were, not
what they were.

- **Never logged:** audio, transcripts, file names, file paths, the prompt sent to the AI
  model, the model's answer, or anything from feedback: not its notes, not its corrected
  words. Saving feedback and adjusting a setting write no log line at all; the record of
  an adjustment is its row in the database, which the calibration screen shows.
- **Shown to the user on failure:** a fixed message for known problems; for unknown ones
  only the step and the kind of error, for example
  `Something went wrong while transcribing (RuntimeError).` The original error text is not
  shown, because it can contain paths or fragments of the recording's content.
- **Only with `LOG_LEVEL=DEBUG`:** full error tracebacks, which include paths to code files.

## 9. Backend decisions

Each entry says what was chosen, what was considered, and what was decided against and why.

### B1. Database: SQLite, not PostgreSQL

- **Chosen:** one SQLite file.
- **What was considered:** PostgreSQL 16 is already installed and running on this machine,
  so it was a real option.
- **Why SQLite:** the app has one user on one computer. SQLite needs no server, no password
  and no setup; the whole database is one file that is easy to back up or delete. The job
  queue lives in the same file.
- **Decided against PostgreSQL:** it would add a service that must be running, a database
  to create and a password to manage, and nothing here needs what it offers (many users,
  heavy simultaneous writes). The requirements also say not to move to PostgreSQL just
  because it is available.
- **When to revisit:** if the app ever becomes multi-user or is hosted on a server.

### B2. Background jobs: a SQLite job table and one worker, not Celery + Redis

- **Chosen:** a `jobs` table plus one worker process that runs one job at a time.
- **Why:** it is the smallest thing that meets every requirement: jobs survive a restart,
  status can be polled, jobs can be cancelled, and only one heavy job runs at once, which is
  what a laptop running speech recognition can handle anyway.
- **Decided against:**
  - *Celery + Redis:* two more things to install, start and troubleshoot (Redis, the Celery
    worker). Their strengths — many workers, many machines, high volume — are not needed for
    one user and one job at a time. Redis is installed on this machine, but being available
    is not a reason to depend on it.
  - *FastAPI `BackgroundTasks`:* built in and needs nothing extra, but the tasks live only
    in memory and run inside the API. If the API restarts, running jobs vanish and the page
    would wait forever; and heavy work would slow the API down.
- **Trade-off accepted:** the worker has to be started as its own command, and the
  crash-recovery logic had to be written and tested by hand (`recover_orphaned_jobs`).
- **When to revisit:** if several analyses must run at once on several machines.

### B3. Python 3.12 in its own environment, managed by uv

- **Chosen:** `uv` creates a private Python 3.12 environment inside `backend/`.
- **Why:** the system Python here is 3.14, which is very new. Audio and machine-learning
  libraries often add support for a new Python version late, so 3.12 is the safe choice.
  (Whether 3.14 would have worked was not tested.) A private environment also means nothing
  is installed into, or removed from, the system Python.
- **Decided against:** using the system Python directly; conda (heavier, and uv was already
  installed).

### B4. CORS allows any `localhost` port, and nothing else

- **Chosen:** the backend accepts requests from pages at `http://localhost:<any port>` and
  `http://127.0.0.1:<any port>`.
- **Why:** port 3000 was already in use on this machine, so the frontend started on a
  different port and a fixed "allow port 3000" rule broke immediately.
- **Decided against:** a fixed list of ports (breaks whenever the port changes); allowing
  every origin with `*` (any website you visit could then call your local API).

### B5. Schema changes only through migrations

- **Chosen:** Alembic migrations from the first table onwards, plus a test that compares
  them with the models.
- **Why:** the structure of the database is written down in the repository and can be
  rebuilt exactly; required by the project brief.
- **Decided against:** letting the app create tables automatically at start-up
  (`create_all`), which is quick but gives no history and no safe way to change a table that
  already holds data; creating tables by hand in a database tool.

### B6. Settings from environment variables with working defaults

- **Chosen:** every setting has a default, so the app runs with no configuration.
- **Why:** nothing here is secret (SQLite has no password), and a beginner should be able to
  start the app without editing files.
- **Decided against:** a required `.env` file; hard-coding values in the code.

### B7. Status changes are "UPDATE … WHERE status = what I expect"

- **Chosen:** every status change names the status it expects to find. Claiming a job is
  "set to running **where it is still queued**".
- **Why:** two things can happen at the same instant, such as the user cancelling just as
  the worker picks the job up. With this pattern the database lets exactly one of them
  succeed, and the other is told it changed nothing and can react.
- **Decided against:** read the row, decide, then write (the classic way to get two winners);
  locks held in Python (they do not work across two separate programs).

### B8. The browser polls; the server does not push

- **Chosen:** `GET /api/jobs/{id}` every second or two.
- **Why:** a job changes state about five times in half a minute. Polling is a handful of
  tiny requests, works through refreshes, and needs no extra machinery.
- **Decided against:** WebSockets or server-sent events, which keep a connection open and
  need reconnect handling, for no visible benefit at this scale.

### B9. Cancellation is cooperative, at safe points

- **Chosen:** a flag the pipeline checks between steps.
- **Why:** it can always be honoured cleanly: files get deleted, the status gets written,
  the speech model stays loaded for the next job.
- **Decided against:** killing the worker process (loses the loaded model and needs
  recovery every time); stopping a Python thread from outside (not safely possible).
- **Trade-off accepted:** cancelling is not instant. It waits for the current step, which
  is at most one 30-second window of transcription: usually a few seconds of computing,
  more if the recogniser has to redo that window.

### B10. A heartbeat, and recovery when the worker starts

- **Chosen:** the worker reports every 3 seconds; a starting worker re-queues or fails
  whatever was left running.
- **Decided against:**
  - *No recovery:* a crash would leave jobs "running" forever.
  - *The API failing jobs that look stuck:* the API would be guessing, and a slow but healthy
    job could be failed by mistake. Instead the API only reports what it knows
    (`workerAlive`), and the worker, which knows the truth, does the recovering.
  - *Unlimited automatic restarts:* a recording that crashes the worker would loop forever.

### B11. After a failure, audio is kept only if a retry could work, and only for a day

- **Chosen:** each failure is marked retryable or not. Retryable failures (speech model
  missing, an unexpected error, a crash) keep the audio for 24 hours so Retry needs no new
  upload. Non-retryable ones (not audio, too long) delete it at once.
- **Decided against:** always deleting on failure (a three-minute performance would be lost
  because a model file was missing); keeping failed uploads indefinitely (recordings would
  pile up on disk without the user knowing).

### B12. Duplicate submissions are blocked by an idempotency key

- **Chosen:** an optional `Idempotency-Key` header with a unique constraint in the database.
- **Why:** a double click, or a request re-sent after a timeout, must not start two analyses
  of the same recording.
- **Decided against:** relying only on disabling the button in the browser, which does not
  cover re-sent requests or a second tab.

### B13. The worker never downloads anything

- **Chosen:** downloading the speech model is a separate, explicit command. The worker runs
  with the model library's offline mode switched on and only loads from disk.
- **Why:** "analysing a recording makes no network requests" is then simply true, and a
  480 MB download never starts by surprise in the middle of a job.
- **Decided against:** downloading on first use, which is convenient but hides a large
  download and makes the first job look frozen.
- **Trade-off accepted:** one more setup step. A job run without the model fails with the
  exact command to fix it, and can then be retried.

### B14. Audio is decoded in-process with PyAV, using our own small decoder

- **Chosen:** `app/pipeline/audio.py` decodes with PyAV, which is already installed as part
  of the speech library and contains FFmpeg's decoders.
- **Why:** no separate ffmpeg program has to be installed, and our decoder can stop early
  when a recording passes the length limit instead of decoding hours of audio first.
- **Decided against:**
  - *Calling the `ffmpeg` command:* works, but adds an install step and a dependency on
    whatever version is on the machine.
  - *The speech library's own `decode_audio` helper:* it failed with the PyAV version
    installed here (it passes an argument that version no longer accepts).

### B15. A result is stored as one JSON document

- **Chosen:** the whole result in one `result` column, with a few fields copied into
  ordinary columns for listing and filtering.
- **Why:** a result is always read and shown as a whole, and it must stay exactly as it was
  measured. One document guarantees that.
- **Decided against:** separate tables for segments, pauses and words. That would mean
  several tables and joins for something that is never queried piece by piece.
- **When to revisit:** if questions like "average pause across all my sessions" need to be
  answered in SQL.

### B16. Measurements are never updated in place

- **Chosen:** the `result` of an analysis row is written once. `revision` and the stored
  settings exist so that a later re-analysis becomes a new row.
- **Why:** old results must stay explainable by the settings that produced them, which the
  calibration feature in Phase 6 depends on.
- **The one exception, added in Phase 4:** the coaching, which lives in its own column and
  can be replaced (decision B25). It is an interpretation of the measurements, not a
  measurement.

### B17. One worker, one job at a time

- **Chosen:** no concurrency.
- **Why:** speech recognition already uses every CPU core. Two jobs at once would each run
  at less than half speed and double the memory in use.
- **Decided against:** a pool of workers. Nothing in the design prevents it later, since
  claiming a job is already safe against two takers (B7).

### B18. Upload size is checked twice

- **Chosen:** once from the size the request declares, before reading it, and again by
  counting bytes while saving.
- **Why:** the first check refuses a huge upload without receiving it; the second cannot be
  fooled by a request that lies about, or omits, its size.

### B19. JSON uses camelCase, Python uses snake_case

- **Chosen:** `start_seconds` in Python is sent as `startSeconds`, converted automatically
  by the classes in `schemas.py`.
- **Why:** each language keeps its own convention, and the JSON matches the contract in the
  project brief.

### B20. Profile texts are served by the backend

- **Chosen:** the delivery profiles are defined once, in `app/profiles.py`, and sent to the
  screen by `GET /api/analysis-options`.
- **Why:** the same descriptions are handed to the AI model for coaching. One source
  means the screen and the coaching cannot say different things.
- **Decided against:** writing the texts into the frontend as well.

### B21. The history list sends summaries

- **Chosen:** eleven headline metrics per item.
- **Why:** a full result includes every word with its timing; twenty of those would be a
  large response for a list that shows two numbers per row.
- **Decided against:** sending full results (heavy); sending only IDs and dates (the screen
  would need one request per row, and could not compare attempts without more).

### B22. Deleting an analysis deletes its job too

- **Chosen:** the result, its recording and the job row go together.
- **Why:** a "succeeded" job pointing at a result that no longer exists would be a lie
  waiting to be read.

### B23. Clearing history leaves work in progress alone

- **Chosen:** queued and running jobs, and their uploads, survive a clear.
- **Why:** "clear my history" should not silently cancel the analysis you are waiting for.
- **Decided against:** wiping every table (simpler, but it would pull an upload out from
  under a running worker).

### B24. The AI model is called from the worker, as the last stage

- **Chosen:** coaching is one more stage (`generating_feedback`) of the job the worker is
  already running.
- **Why:** the model takes 20 to 50 seconds. That is slow work, and slow work belongs in
  the worker (B2). It also keeps the "one heavy thing at a time" rule (B17): the speech
  model and the AI model never run together, which matters on a laptop where each wants
  several gigabytes of memory.
- **Decided against:**
  - *Calling the model from an API request*: a request held open for most of a minute, lost
    if the tab closes, and able to run at the same moment as a transcription.
  - *A separate job that the browser has to start after the analysis*: two round trips and
    two things to wait for, for what the user sees as one action.

### B25. Coaching is stored beside the measurements, not inside them

- **Chosen:** a `coaching` column on `analyses`, separate from `result`.
- **Why:** the two have different lifetimes. Measurements are facts about a recording and
  never change (B16). Coaching is wording, and the same facts can be worded again, so it
  must be replaceable without touching, or even rewriting, the measurements.
- **Decided against:**
  - *Putting coaching inside the `result` JSON*: every rewrite would rewrite the whole
    measured document, and "never changed" would stop being checkable.
  - *A table of coaching versions*: nothing needs the old wording once there is new
    wording, and it would have to be cleaned up.

### B26. Coaching can never cost the user their measurements

- **Chosen:** three layers. If the AI model is unavailable or its answer is rejected, the
  coaching comes from templates and the job still succeeds. If the coaching step itself
  raises an error nobody planned for, it is caught and the result is saved with no
  coaching. Only cancellation and shutdown stop the job.
- **Why:** by the time coaching starts, the expensive and unrepeatable part is done: a
  recording made in the browser and not kept cannot be measured again. Losing it to a
  failure in an optional step would be the worst outcome available.
- **Decided against:** failing the job when the AI model fails, which is the simplest thing
  to write and reports the problem loudly, but throws away finished work. The problem is
  reported instead as a `notice` on the coaching.

### B27. "Write the coaching again" is a job of its own kind, in the same queue

- **Chosen:** a `kind` column on `jobs`. A `coaching` job has no audio, works from the
  stored measurements, and reuses everything a job already has: the queue, polling,
  cancellation, heartbeats, crash recovery.
- **Why:** the most likely reason for template coaching is that Ollama simply was not
  running. Without this, the only way to get AI coaching afterwards would be to upload the
  recording again, and a recording made in the browser may no longer exist.
- **Decided against:**
  - *An endpoint that calls the model and waits*: see B24.
  - *A second queue or table for coaching jobs*: a second copy of the queue logic, and a
    way for the two heavy models to run at once.
  - *Re-running the whole analysis*: needs the audio, and repeats half a minute of work
    whose result cannot differ.

### B28. A coaching job fails rather than falling back to templates

- **Chosen:** in an analysis job, no AI model means template coaching. In a coaching job, it
  means the job fails and nothing changes.
- **Why:** the user pressed a button that says "ask the AI model". Replacing AI coaching
  with templates, or templates with the same templates, and calling that success would be
  untrue. Failing with the reason ("Ollama is not running") tells them what to fix.
- **Consequence:** such a failure is never marked retryable. Trying again is a new job.

### B29. Asking twice does not queue the AI model twice

- **Chosen:** if a coaching job for an analysis is already queued or running, the endpoint
  returns that job (`200`) instead of creating another.
- **Why:** each answer costs most of a minute of full CPU. A double click must not double it.
- **Decided against:** an idempotency key, as uploads use (B12). There the browser has to
  say which upload is which; here the analysis ID already identifies the work.

### B30. The worker reports on the AI model; the API does not look for itself

- **Chosen:** the worker checks Ollama at most every 15 seconds and writes the answer into
  `worker_state`; the health endpoint reads it from there.
- **Why:** it is the same arrangement as for the speech model, and it reports the view of
  the program that will actually make the call.
- **Decided against:** the API calling Ollama on every health check. Simpler to read, but it
  adds an outgoing request to an endpoint the page polls every ten seconds, and the API's
  answer could differ from what the worker will find.

### B31. Ollama is called with the HTTP library the project already had

- **Chosen:** `httpx`, already installed (it is what FastAPI's test client uses), called
  from one file, `app/llm.py`, behind a three-member interface: a name, `status()` and
  `complete_json()`.
- **Why:** one HTTP request does not need a framework. Keeping it behind a small interface
  means a different way of calling a model could be added later as one more class, which is
  the seam the project brief asks for.
- **Decided against:**
  - *LiteLLM*: ruled out for now by the brief. It is a layer for switching between many
    providers, most of them cloud services this project must not use.
  - *The `ollama` Python package*: a new dependency for what is two HTTP calls.
  - *LangChain or similar*: far more machinery than one prompt and one answer need.

### B32. A reference is an analysis with a role, not a new kind of thing

- **Chosen:** one `role` column on `jobs` and `analyses`. A reference is uploaded through
  the same endpoint, waits in the same queue, runs through the same pipeline and is stored
  in the same table as a take.
- **Why:** the brief's condition for comparing with a reference is that it is measured "using
  the same local pipeline". Making it literally the same code path is the surest way to
  keep that true: there is no second place where a threshold could drift. Everything a job
  already has (cancel, retry, recovery, clean-up) works for references with no new code.
- **Decided against:**
  - *A separate `references` table and upload endpoint*: a second copy of the upload,
    validation and storage logic, for rows with the same columns.
  - *A flag on the take saying "this one is the reference"*: a reference is reused across
    many takes and days; it is not a property of one take.

### B33. A reference gets no coaching

- **Chosen:** the worker skips `generating_feedback` for a reference.
- **Why:** coaching tells the speaker what to change for the next take. The speaker of a
  reference is someone else, and there is no next take. It also saves the half-minute the
  AI model would have taken.

### B34. The comparison is worked out on request and never stored

- **Chosen:** `GET …/comparison/{referenceId}` computes it from the two stored results each
  time.
- **Why:** it takes a few thousandths of a second, so nothing is gained by keeping it; and
  a stored comparison could go stale when its thresholds change, while a computed one
  always reflects the current ones and says which they were.
- **Decided against:**
  - *A background job*, as analysis and coaching use: far too heavy for work this quick.
  - *Storing it with the take*: a take can be compared with any number of references.
  - *Working it out in the browser*: the arithmetic would then exist twice, in two
    languages, once it is needed anywhere else.

### B35. The waveform outline is made by the worker and stored in its own column

- **Chosen:** computed during analysis from the audio the worker has already decoded,
  stored in `analyses.waveform`, served by its own endpoint.
- **Why:** see science decision S45 for why the worker and not the browser. Its own column
  and endpoint keep two promises: the measured `result` contains nothing that is only a
  picture, and a screen with the waveform switched off never downloads it.
- **This replaces a decision recorded earlier.** The Phase 3 documents said the waveform
  would be drawn in the browser from audio already loaded there. That was written before
  working out the memory it needs for a long recording and what happens when the recording
  was not kept.
- **Decided against:** putting it inside `result` (sent with every result, wanted or not);
  computing it on request from the kept audio (impossible when the audio was not kept).

### B36. Takes and references are listed and cleared separately

- **Chosen:** every list and every "clear" is for one role, takes by default.
- **Why:** "clear my history" means the takes. A reference is something added once and
  used for weeks; losing it to a history clear would be a nasty surprise. The default also
  means that every screen and script written before Phase 5 keeps seeing only takes.
- **Decided against:** one mixed list with a filter in the browser.

### B37. Only a reference can be compared against

- **Chosen:** the second ID in the comparison address must have the role `reference`.
- **Why:** comparing one of your takes with another is already offered, as the "earlier
  attempt" table, which is a different comparison: figures only, no lining up of words. Mixing
  the two would blur which recording is the target.

### B38. Feedback is saved, and acted on, inside one ordinary request

- **Chosen:** `POST …/feedback` classifies the feedback, saves it, checks whether any
  setting should now move, and answers with the outcome. No job, no queue.
- **Why:** all of it is a few database reads and a little arithmetic: milliseconds. The
  queue exists for work that takes seconds or minutes. Doing it at once also means the
  screen can say "1 of the 3 reports needed" in the same breath as "saved".
- **Decided against:** *a calibration job run by the worker*, which would add a delay and a
  second writer of calibration for nothing; and *adjusting on a timer*, which would make
  it impossible to say which piece of feedback caused a change.

### B39. Calibration versions are only ever added

- **Chosen:** every change writes a new row: an adjustment, an undo, a reset. Undo does not
  delete the adjustment it reverses; it adds a version that puts the old value back.
- **Why:** each analysis stores the version it was made with. If versions could be edited
  or removed, "made with version 2" would stop meaning anything the moment version 2
  changed. The brief requires results to stay traceable to their settings.
- **Decided against:** *one row of current values, updated in place*: simpler, and no way
  to explain an old result or to show a history. *Deleting the row on undo*: version
  numbers would be reused for different values.

### B40. One row per thing: saying something else replaces what was said

- **Chosen:** each piece of feedback has a `slot` naming what it is about
  (`pause:pause-2`, `wpm:seg-3`, `missed:seg-1@2.62`), unique per analysis. New feedback in
  the same slot replaces the old row; the same category again only updates the note.
- **Why:** a pause cannot be both intentional and "not a pause". And clicking twice, or
  changing one's mind back and forth, must not manufacture several reports out of one
  observation.
- **Detail:** a missed pause is slotted by the *silence* it turned out to be about, not by
  the time the user marked. So the same silence marked at three slightly different times
  is one report.

### B41. A report counts once, and undo does not give it back

- **Chosen:** an adjustment marks every report waiting on its setting as used
  (`used_by_version`). Undoing or resetting leaves them used. Rewording a used report in
  the same direction keeps it used.
- **Why:** otherwise an undone adjustment would be re-applied by the very next piece of
  feedback, from the same reports the user has just overruled.
- **Decided against:** *un-spending reports on undo*, for that reason; and *spending only
  the reports that agreed*, which would leave the dissenting ones to tip a later count
  they were already weighed in.

### B42. The worker reads the calibration when a job starts, and the result carries it

- **Chosen:** the newest version is read once per job. Its number and the minimum pause it
  gave are part of the settings the pipeline copies into every result.
- **Why:** a result should be explainable from the result alone. The version is in its own
  JSON, and also in a column so it can be listed without opening the JSON.
- **Decided against:** *reading the calibration at each stage*: a change halfway through a
  job would give a result made with two different settings.

### B43. What a piece of feedback "does" is worked out when it is read

- **Chosen:** the sentence shown beside each piece of feedback ("counts towards…", "counted
  in version 2…", "no longer counts") is built from the current state each time the list
  is requested. It is not stored.
- **Why:** it changes without the feedback changing: when another report arrives, when a
  setting moves, on undo, on reset. A stored sentence would go stale.
- **Stored instead:** the facts it is built from: the category, what was measured, the
  setting and direction, and which version used it.

### B44. Deleting an analysis deletes its feedback, but not what the feedback did

- **Chosen:** feedback rows go with their analysis (a database rule: `ON DELETE CASCADE`).
  A setting they had already moved stays moved, and its history entry stays.
- **Why:** the rows hold the user's notes and corrected words, and deleting a recording's
  result should take those with it. But a calibration version records only numbers and a
  sentence about counts, and removing it would break the trail for every other result made
  with it. To take an adjustment back there is undo.

### B45. A corrected transcript is stored by the API at once, as a new row

- **Chosen:** no job. The API works the figures out again and stores a new analysis row
  with the same job ID as the result it came from.
- **Why:** nothing here touches audio or a model. It is arithmetic on a few hundred words.
- **Decided against:**
  - *Overwriting the stored result*: against B16, and it would destroy the record of what
    the recogniser actually heard.
  - *Storing only the corrections and applying them every time the result is read*: every
    reader of a result (the comparison, the coaching, the history) would need to know
    about corrections.
  - *Running the AI model as part of the request*: half a minute inside an HTTP request.
    The revision gets rule-based coaching, and "write the coaching again" asks the model.

### B46. Analysing again is an ordinary job on its own copy of the recording

- **Chosen:** the kept file is copied into `uploads/` and a normal analysis job is queued
  with `source_analysis_id` set. Everything else is the code path an upload takes.
- **Why:** the worker deletes or moves a job's audio when the job ends, on success, failure
  and cancellation alike. Pointing a job at the kept file itself would put the user's kept
  recording in the path of all three.
- **Decided against:** *working pauses out again from stored data without the audio*. The
  phrases would change, and loudness and pitch per phrase need the sound.
- **Cost accepted:** needs the recording to have been kept. Without it the endpoint says so.

### B47. A corrected revision shares its recording through a hard link

- **Chosen:** the new revision's audio file is a second name for the same bytes on disk.
- **Why:** the audio is identical, so a copy would double the space for nothing. With two
  names, each result still owns "its" file: deleting one result's recording cannot break
  the other, and no code has to count who else is using a file.
- **Decided against:** *both rows pointing at one path*: deleting the recording from one
  result would silently remove it from the other, or need reference counting everywhere a
  file is deleted.
- **Not used for analysing again**, where the file lands in `uploads/` first: the
  housekeeping that removes stray uploads goes by a file's age, and a hard link has the
  age of the original.

### B48. Results of one recording are tied together by a root, and listed separately

- **Chosen:** `root_id` on every result. The history lists each revision as its own row,
  marked "Revision 2: transcript corrected". Reading any one of them returns the list of
  all of them.
- **Why:** each revision is a complete result that can be opened, compared and deleted
  like any other, so nothing else in the app needed to learn about revisions.
- **Decided against:** *a separate `recordings` table with results under it*: the right
  shape for a larger app, and a rewrite of every list and delete here.

### B49. Feedback is taken on takes only

- **Chosen:** feedback on a reference recording is refused (`409 not_a_take`).
- **Why:** calibration is meant to fit the app to *the user's own* recordings: their
  microphone, their room, their way of speaking. A film clip is a different kind of sound,
  often with music, and reports about it would pull the settings the wrong way.
- **Still possible:** a reference can be analysed again with the current settings, so that
  it and the takes are cut the same way.

### B50. Adjustable settings live in the database, not in `.env`

- **Chosen:** defaults in code, allowed ranges in `calibration/registry.py`, current
  values in `calibration_versions`.
- **Why:** an environment variable is read once at start-up, has no history, and is not
  recorded with a result. A value that changes while the app runs, must be undoable, and
  must be traceable from every result needs all three.

### B51. A coaching job may fall back to the rules when pause labels have changed

- **Refines B28.** A coaching job still fails rather than replace coaching with the same
  templates. The exception: if the user has labelled pauses since the stored coaching was
  written, coaching from the rules that takes the labels in *is* an improvement, so the job
  succeeds with it when the AI model cannot answer.
- **How it is told:** the stored coaching records the labels it used (`labelsUsed`); the
  worker compares them with the labels now on the analysis.

### Decisions already made for later phases

None. Every phase in the plan is built.

## 10. Tests

Run with the command in the README. Current result: **595 pass**, 1 skipped (the opt-in
real-speech test, which also passes when run). 159 of them are new in Phase 6.

| Test file | Tests | What it proves |
| --- | --- | --- |
| `test_segmentation.py` | 25 | Segments and pauses from speech regions; threshold edges; long silences; word assignment. Short silences: every gap is either a pause or a short silence, never both; what counts follows the minimum pause in force; settings stored with an older result can still be read |
| `test_metrics.py` | 23 | WPM with pauses excluded and included; reliability flags; typical pace and faster/slower; pause statistics; no division by zero |
| `test_audio_and_acoustics.py` | 20 | Decoding, length limit, clipping, loudness in dB, pitch, emphasis candidates, hesitation sounds |
| `test_pipeline.py` | 24 | The whole pipeline with scripted speech: numbers, warnings, no-speech, garbled transcripts, cancellation |
| `test_job_queue.py` | 25 | Every status change: claim order, duplicates, cancel, fail, retry, expiry, crash recovery, liveness |
| `test_worker.py` | 31 | Real jobs end to end: success, clean-up, failure messages, cancel mid-job, graceful stop, recovery. Coaching as the last stage; an unavailable model or a crash in coaching never failing the analysis; coaching jobs succeeding, failing, being cancelled, handed back and recovered. A reference measured like a take with no coaching stage and no call to the AI model; the waveform stored beside the measurements, and the measurements identical with and without it |
| `test_api.py` | 35 | Submitting, polling, cancel, retry, every refusal, the full upload → poll → result journey. Coaching in the result; writing it again; asking twice; the old coaching surviving a failure; health reporting the AI model |
| `test_history_api.py` | 22 | Form options, the history list and paging, kept-audio playback and deletion, deleting one analysis, clearing history without touching work in progress. References: submitted with a title, listed and cleared separately from takes. The waveform served only on request. The comparison endpoint and every refusal |
| `test_comparison.py` | 26 | Pauses matched, missing, extra and unplaced; a recording against a copy of itself showing no difference even with word times pushed into the pauses; phrase pace over the same words; whole-recording rows; the biggest differences in order and in words; different passages compared only as wholes; neither recording changed |
| `test_comparison_align.py` | 20 | Word keys, including Hindi spelling variants; dropped, added and misheard words; a repeated line matched to the right repetition; speed on a ten-minute passage |
| `test_waveform.py` | 6 | The outline's lowest and highest values, its size for long and short recordings, padding, no normalising |
| `test_migrations.py` | 2 | The migrations build exactly the tables the code expects; a database from before Phase 4 upgrades with its rows intact, each result becoming calibration version 1 and the first result of its own recording |
| `test_calibration_engine.py` | 34 | The adjustment rules with no database: one or two reports move nothing; three from one recording are not enough; disagreement and ties change nothing; only recent reports count; the minimum pause is steered by the silences reported and never moves more than 100 ms at once; **no setting ever leaves its allowed range**; a report already answered by an earlier change stops counting; moving back needs five reports; the detection threshold is not adjustable |
| `test_feedback.py` | 26 | What each kind of feedback is taken to mean: labels speak for no setting; a short false pause for raising the minimum pause; a long one for nothing; a missed pause for lowering it only where a silence of 250 ms or more was heard; one silence can be reported only once; **no feedback speaks for more than one setting** |
| `test_feedback_api.py` | 28 | Through the API: storing, replacing, noting and removing feedback; a fresh install says it is still calibrating; two reports change nothing; **three agreeing reports from two recordings move only the minimum pause**, with a reason and a confidence; each adjustment needs fresh reports; **undo, reset and switching off**; new analyses use the new value and old ones stay as they were; **labelling a pause changes no measurement**, and reaches the coaching when it is written again; saying a WPM looks wrong changes no number |
| `test_transcript_correction.py` | 20 | **Segment WPM is the corrected word count over the phrase's own length, with no correction factor**; totals recounted; untouched phrases keep every figure; everything measured from the sound identical; corrected words get times between their neighbours; hesitation sounds recounted; emphasis candidates kept only for words still there |
| `test_revisions.py` | 16 | A corrected transcript becomes revision 2 and the corrected result stays exactly as it was; both are in the history; pause labels come along and reports do not; the kept recording is shared and each copy can be deleted alone. Analysing again: a new revision with the settings in force, for takes and references; asking twice; refused without a kept recording; a cancelled one leaves the kept recording alone |
| `test_wpm_review.py` | 12 | The arithmetic shown; too high points at extra words and speech lost in a pause, too low at dropped words and silences counted as speaking; word timing is always part of it; reviewing changes nothing |
| `test_coaching_findings.py` | 45 | Every finding: its band, its wording, its role under each profile; what is left out when a measurement is missing; that statements contain no figure that is not a measurement or a band. Pause labels: an accidental pause is not praised as a held silence, an intentional one is never an issue, labels never change a measurement. Priorities move an issue down the list without removing it |
| `test_coaching_rules.py` | 64 | Template coaching: order, practice phrase, profile sentence, targets; every template under every profile fills in completely and quotes only known figures |
| `test_coaching_prompt.py` | 14 | What the model is shown and forbidden; that its answer can only name findings and phrases that exist; the size estimate staying above the model's real token counts; a long recording losing its timings before any words, then being cut to fit; the model is told which pauses the actor marked |
| `test_coaching_grounding.py` | 32 | Invented figures, times, segments and quotations are caught; copied ones pass; units in their common spellings |
| `test_coaching_coach.py` | 26 | A clean answer is used; a bad one is sent back once; what still fails is removed; nothing surviving means templates; every way the model can be unavailable; cancellation |
| `test_llm.py` | 19 | The Ollama client against a scripted server: status, streaming, cut-off answers, errors, timeouts, cancellation, refusing non-local addresses, never downloading a model |
| `test_real_speech.py` | 1 | Opt-in: the real speech detector and model on synthesised speech with known silences |

How the tests stay fast and exact: the slow parts (speech detection, transcription, pitch)
are passed into the pipeline as replaceable pieces, so most tests script them — "speech from
1 s to 5 s, twelve words" — and check numbers that can be worked out by hand. Time is a fake
clock the test moves forward. Each test gets its own temporary database and data folder.
The AI model is replaced the same way: a stand-in that returns prepared answers and records
what it was asked, so the tests never need Ollama and can script a model that invents a
number, answers in broken JSON, or is not running at all.

What was also checked by hand at the end of Phase 2, with the real API and worker running:

| Check | Result |
| --- | --- |
| Upload with no worker running | Job stays `queued`, `workerAlive: false` |
| Start the worker | Job runs through its stages and succeeds; upload file deleted |
| Same `Idempotency-Key` twice | Second answer is `200` with the first job |
| A text file named `.mp3` | Refused with `415`, nothing stored |
| A Hindi recording with `retainAudio` | Devanagari transcript; file moved to `data/audio/` |
| Cancel while transcribing | `running` + `cancelRequested`, then `cancelled` after 2.6 s; next job starts |
| Kill the worker (`kill -9`) mid-job | Job still `running`, `workerAlive` turns `false` within 18 s |
| Restart the worker | Job re-queued automatically, succeeds on attempt 2 |
| `Ctrl+C` mid-job | Job back to `queued` with attempt 0; worker exits cleanly in 3 s |
| Start a second worker | Refuses: "Another worker is already running" |

Also checked at the end of Phase 3, through the General Practice screen:

| Check | Result |
| --- | --- |
| A recording made by the browser (WebM/Opus) | Decoded and analysed; pauses within 0.05 s of the same clip as WAV |
| A kept WebM recording requested with a byte range | `206 Partial Content`, content type `audio/webm`; the player can seek |
| Delete only the recording | File gone; `audioRetained` false; measurements unchanged |
| Clear all history with 14 analyses | All analyses, kept files and finished jobs removed |
| Kill the worker during a job started from the screen | Restarted worker re-queues it; the screen follows it to completion |

Also checked at the end of Phase 4, with the real worker and the real `llama3.1:8b` in
Ollama 0.40 on an Apple M2 with 16 GB of memory:

| Check | Result |
| --- | --- |
| Start the worker with Ollama running | Logs "AI coaching ready"; health shows `"coach": "ready"` |
| Analyse a 22-second English recording | Stages run through `generating_feedback`; succeeded in 39.0 s, of which the AI model took 29.8 s |
| Analyse an 8-second Hindi recording | Succeeded in 41.3 s (model 24.8 s); the drills quote the Devanagari lines |
| Analyse a 133-second English recording | Succeeded in 76.2 s (model 49.2 s); three corrections, each on a different phrase |
| Ask for the coaching again | A `coaching` job; succeeded in 20.9 s; measurements byte-for-byte unchanged |
| Ask twice in a row | Second answer is `200` with the first job |
| Cancel a coaching job 8 s in | `cancelled` within 1 s; stored coaching unchanged |
| Worker started with Ollama unreachable | Logs a warning with what to do; health shows `"coach": "not_running"` |
| Analyse with Ollama unreachable | Succeeded in 9.1 s; coaching `source` is `rules`, `notice.code` is `not_running` |
| Ask for the coaching again with Ollama unreachable | Job `failed` with `not_running`; stored coaching unchanged |
| Memory the model holds while loaded | 5.8 GB, as reported by Ollama. It stays loaded for about five minutes after its last use (Ollama's default) |

| A prompt the size of a 10-minute recording (108 phrases, 1,665 words) sent to the real model | Fits: 5,134 tokens of the 8,192 allowed, with no words cut; answered in 66 s |

Not checked: a machine with less memory, a real recording near the 10-minute limit, and any
model other than `llama3.1:8b`.

Also checked at the end of Phase 5, with the real worker on synthesised recordings:

| Check | Result |
| --- | --- |
| Submit a recording with `role=reference` and a title | Runs four stages, no `generating_feedback`; stored with its role and title; `coaching` is empty |
| A 133-second recording as a reference, then as a take with AI coaching | 24.6 s and 72.8 s |
| `GET /api/analyses` and `GET /api/analyses?role=reference` | Takes in one, references in the other |
| Fetch a waveform | 1,993 points for a 17-second recording, 21 KB; values within −0.67 to 0.81 |
| Compare an English take with an English reference | 30 of 31 words lined up; four pause rows, all correct; answered in 5 ms |
| Compare a Hindi take with a Hindi reference | 17 of 19 words lined up; the missing and the extra pauses correct |
| Compare a two-minute recording with a copy of itself | At first: 6 of 23 pauses wrongly reported as missing and extra. After the fix in decision S39: 23 of 23 matched, no differences |
| Clear the takes, then the references | Each clear removed only its own role, and its kept audio |

Also checked at the end of Phase 6, through the real API, worker, speech model and
`llama3.1:8b`, on a separate test database so the real one was never touched. The two test
recordings were synthesised with silences of known length inside their phrases; the
detector measured those as 324, 356 and 356 ms in one and 356 and 356 ms in the other.
All 48 checks in the script passed.

| Check | Result |
| --- | --- |
| A fresh database | Calibration version 1, "still calibrating", 13 adjustable settings |
| Analyse the two takes and a reference | 49 s (first run, models loading), 21 s and 6 s. Each result records calibration version 1, the 500 ms minimum pause, and its short silences, every one inside the phrase it is listed under |
| Label one pause accidental and one intentional | The stored result is byte for byte the same; no report is waiting |
| Write the coaching again with those labels | The AI model answered in 38 s and passed the checks. The 2.7 s pause marked accidental is no longer read as a held silence, and is still counted in every pause figure at full length |
| Report two missed pauses in one recording | Nothing moves: "2 of the 3 reports needed for lowering it, from 1 of the 2 recordings needed" |
| Report a third, in the second recording | Minimum pause 500 → 400 ms, with its reason; no other setting changed; the earlier results untouched |
| Analyse the first recording again | 26 s. Revision 2, version 2, 400 ms. Pauses unchanged, as predicted: the silences are 324 to 356 ms, still under 400 |
| Compare that revision with the reference made at 500 ms | `settingsNote` says the two were analysed with different settings |
| Three fresh reports on the revisions | 400 → 350 ms. Analysed again: 5 pauses instead of 3; the two 356 ms silences are now pauses and the 324 ms one is not; speaking time fell by exactly 2 × 0.356 s; the word count is unchanged |
| Say a phrase's WPM looks too high | Nothing changed. Review: "16 words ÷ 4.51 s of speaking × 60 = 212.9 WPM" |
| Correct that phrase's transcript, removing two words | Revision 4: 14 words, 186.3 WPM, which is 14 ÷ 4.51 × 60. Pauses, phrase times, loudness and pitch identical to revision 3; revision 3 unchanged; the revision plays its recording |
| Undo twice | 350 → 400 → 500 ms, then nothing left to undo |
| Analyse the first recording again at 500 ms | Cut exactly as it was the first time: same pauses, same short silences, same phrases and WPM |
| Switch automatic adjustment off and report | Reports saved, nothing moves |
| Reset | Every default back; no reports waiting; the history lists all six versions |

Not checked: a real human voice, a noisy room, a quiet or whispered delivery, and feedback
built up over many days of real use. See "Accuracy and limits" in the science document for
what was measured about the speech detector on hard audio.

