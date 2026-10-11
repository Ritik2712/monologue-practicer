# Monologue Coach — Backend Documentation

The Python side of the app: the API, the database, the job queue and the worker that does
the slow audio work.

- Start with [DOCUMENTATION.md](DOCUMENTATION.md) for the big picture and the glossary.
- **What** is measured in the audio, and why those methods were chosen, is in
  [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md). This file covers **how the work is
  organised**: requests, jobs, files and tables.
- The browser side is in [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md).

Anything not built yet is marked **Planned**.

**Last updated:** end of Phase 3 (history, kept-audio and form-options endpoints added for the
General Practice screen).

## Contents

1. [The three programs](#1-the-three-programs)
2. [Folder structure](#2-folder-structure)
3. [The API list](#3-the-api-list)
4. [Background jobs (and why there is no Celery)](#4-background-jobs-and-why-there-is-no-celery)
5. [The database](#5-the-database)
6. [Audio files on disk](#6-audio-files-on-disk)
7. [Settings](#7-settings)
8. [What is and is not written to logs](#8-what-is-and-is-not-written-to-logs)
9. [Backend decisions](#9-backend-decisions)
10. [Tests](#10-tests)

## 1. The three programs

The backend folder contains three things you run. They share one database file and one
data folder, and never talk to each other directly.

| Program | Command (from `backend/`) | What it does | Runs for |
| --- | --- | --- | --- |
| **API** | `uv run uvicorn app.main:app --reload --port 8000` | Answers the browser's requests. Never does slow work. | As long as you use the app |
| **Worker** | `uv run python -m app.worker` | Takes jobs from the queue one at a time and analyses the audio. | As long as you use audio analysis |
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
```

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
│   ├── profiles.py       The delivery profiles and language choices, as text
│   ├── uploads.py        Creating, moving and deleting audio files
│   ├── worker.py         The worker program
│   ├── speech_model.py   Finds or downloads the speech model
│   ├── routes/
│   │   ├── health.py     GET /api/health
│   │   ├── analyses.py   Submit, read, list and delete analyses; kept audio; form options
│   │   └── jobs.py       GET /api/jobs/{id}, POST …/cancel, POST …/retry
│   └── pipeline/         The audio analysis itself (explained in the science document)
│       ├── runner.py         Runs the stages in order and assembles the result
│       ├── audio.py          Decodes any audio file to one standard format
│       ├── vad.py            Finds where speech is
│       ├── transcribe.py     Speech to words with timestamps
│       ├── segmentation.py   Speech regions -> segments and pauses
│       ├── metrics.py        Words per minute and pause statistics
│       ├── acoustics.py      Loudness, pitch, emphasis candidates
│       ├── fillers.py        Hesitation sounds
│       ├── settings.py       The thresholds (0.5 s pause, 5 s long silence…)
│       └── errors.py         Errors with a code and a message safe to show
├── migrations/
│   ├── env.py            Tells the migration tool where the database is
│   └── versions/
│       └── 0001_jobs_analyses_and_worker_state.py   Creates the three tables
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
| When is an audio file deleted? | `app/uploads.py`, `app/job_queue.py`, `app/history.py` |
| What do the delivery profiles say? | `app/profiles.py` |
| What columns does a table have? | `app/models.py` |

## 3. The API list

An **API endpoint** is an address the frontend can send a request to. Each one has a method
(`GET` to read, `POST` to create or do something) and a path. While the API is running, an
interactive version of this list is at `http://localhost:8000/docs`.

### Built

| Method | Path | What it does | Defined in |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Is the API up, can it reach the database, is a worker alive, is the speech model present | `routes/health.py` |
| `POST` | `/api/analyses` | Accepts a recording, queues a job, answers at once with the job | `routes/analyses.py` |
| `GET` | `/api/jobs/{jobId}` | Where a job has got to. Made to be polled | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/cancel` | Asks for a job to stop | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/retry` | Puts a failed job back in the queue | `routes/jobs.py` |
| `GET` | `/api/analyses/{analysisId}` | The stored result of a finished analysis | `routes/analyses.py` |
| `GET` | `/api/analysis-options` | What the form offers: profiles, languages, upload limits | `routes/analyses.py` |
| `GET` | `/api/analyses` | Past analyses, newest first, with their headline numbers | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}` | Deletes one analysis, its kept recording and its job | `routes/analyses.py` |
| `DELETE` | `/api/analyses` | Clears all history | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/audio` | The recording itself, if it was kept | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}/audio` | Deletes only the kept recording | `routes/analyses.py` |

The first six are tested in `tests/test_api.py`, the last six in `tests/test_history_api.py`.

### `GET /api/health`

```json
{ "status": "ok", "database": "ok", "worker": "running", "speechModel": "ready" }
```

- `status` and `database` describe the API itself.
- `worker` is `running` if a worker has reported in during the last 15 seconds.
- `speechModel` is what the worker last reported: `ready`, `missing`, or `unknown` if no
  worker has ever started. The API does not check the model itself, so that it never has to
  load the heavy speech libraries.

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

**The `Idempotency-Key`.** "Idempotent" means doing something twice has the same effect as
doing it once. The browser makes up a random key for each recording it submits. If the
button is clicked twice, or the request is sent again after a network hiccup, the same key
arrives twice and only one job is created. A new recording must use a new key.

### `GET /api/jobs/{jobId}`

```json
{
  "jobId": "104a71305a78446ea62279bb51bdf7c2",
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
| `status` | `queued`, `running`, `succeeded`, `failed` or `cancelled` |
| `stage` | Only while running: `preparing_audio`, `detecting_speech`, `transcribing`, `measuring_audio` |
| `cancelRequested` | `true` between asking a running job to stop and the worker actually stopping |
| `error` | Only when failed: `{ code, message, retryable }` |
| `analysisId` | Only when succeeded: where to fetch the result |
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
`not_failed`, `not_retryable` or `audio_gone`.

### `GET /api/analyses/{analysisId}`

The complete result: transcript, segments, pauses, words, metrics, loudness timeline,
warnings, and the settings that produced it. Its contents are described in the science
document. The result is stored once and never changed.

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

Query parameters: `limit` (1–100, default 20) and `offset` (default 0).

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
| `DELETE /api/analyses/{id}` | The result, its kept recording, and the job that produced it | Everything else |
| `DELETE /api/analyses/{id}/audio` | Only the kept recording | The measurements |
| `DELETE /api/analyses` | Every result, every kept recording, every finished job, and any audio a failed job was holding for a retry | Jobs still queued or running, and their uploads |

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

### Planned (not built — names and details may change)

| Method | Path | Purpose | Phase |
| --- | --- | --- | --- |
| `POST` | `/api/analyses/{id}/feedback` | Save a correction from the user | 6 |
| `GET` / `PATCH` | `/api/calibration` | Read or change calibration settings | 6 |

## 4. Background jobs (and why there is no Celery)

### The problem

Analysing audio is slow: a two-minute recording takes about half a minute here. If the API
did that work while the browser waited, the page would hang and a closed tab would lose
everything. The usual fix is a **background job**:

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
3. **Finish**, in exactly one of these ways:

| What happened | Job becomes | Audio file |
| --- | --- | --- |
| The pipeline returned a result | `succeeded`; the result is stored in `analyses` | Deleted, or moved to `data/audio/` if `retainAudio` was set |
| Cancellation was requested | `cancelled` | Deleted |
| The worker is shutting down | `queued` again; the attempt is not counted | Kept |
| An expected failure (`PipelineError`) such as unreadable audio | `failed` with that error's code and message | Deleted, unless the error is retryable |
| Any other error | `failed` with code `unexpected_error` | Kept for a retry |

### Cancellation is cooperative

A running job is never killed from outside. Cancelling sets a flag; the pipeline checks that
flag at **safe points** — between stages, and between each 30-second window of
transcription — and stops itself there. That is why the status stays `running` with
`cancelRequested: true` for a moment: the app does not claim a job is cancelled until it
really has stopped. Measured on two-minute recordings, that took 2.6 and 4.2 seconds. It can
take longer when the recogniser is redoing a difficult window (see the science document,
decision S9), because a window is never interrupted half-way.

### Heartbeats: how anyone knows the worker is alive

Every 3 seconds, a small background thread in the worker writes the current time into:

- the `worker_state` table → the API uses it for `worker` in the health check and for
  `workerAlive` in every job status;
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
| still has its audio and has been started fewer than `MAX_JOB_ATTEMPTS` (2) times | `queued` again |
| has already used its attempts, or has lost its audio | `failed` with code `worker_stopped` |

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
| `find_by_idempotency_key` | `POST /api/analyses` | Detect a repeated submission |
| `to_status` | every job endpoint | Build the JSON status |
| `request_cancel` | `POST …/cancel` | Cancel now, or set the flag |
| `retry_job` | `POST …/retry` | Put a failed job back in the queue |
| `claim_next_job` | worker | Take the oldest queued job |
| `set_stage`, `touch_job` | worker | Report progress and heartbeat |
| `is_cancel_requested` | worker (`check`) | Read the cancel flag |
| `complete_job`, `fail_job`, `finish_cancelled`, `release_job` | worker | The four ways a run ends |
| `recover_orphaned_jobs` | worker | Deal with jobs a dead worker left behind |
| `expire_failed_audio` | worker | Delete audio kept too long |
| `report_worker`, `worker_alive` | worker / API | The worker's own heartbeat |

## 5. The database

One SQLite file: `backend/data/monologue_coach.db`, created the first time the migration
command runs. It is listed in `.gitignore`, so it is never committed.

### Tables

**`jobs`** — one row per request to analyse a recording.

| Column | Meaning |
| --- | --- |
| `id` | The job ID (32 random hexadecimal characters) |
| `status`, `stage` | See section 4 |
| `cancel_requested` | The cooperative-cancel flag |
| `attempt` | Times a worker has started it |
| `idempotency_key` | Unique; blocks duplicate submissions |
| `profile`, `language_hint`, `retain_audio` | What was asked for |
| `original_filename` | The file's display name only, never a path |
| `audio_path` | Where the upload is, relative to the data folder. Empty once deleted |
| `error_code`, `error_message`, `error_retryable` | Why it failed |
| `analysis_id` | The result, once succeeded |
| `created_at`, `updated_at`, `started_at`, `finished_at`, `heartbeat_at` | Times, stored in UTC |

**`analyses`** — one row per successful job.

| Column | Meaning |
| --- | --- |
| `id`, `job_id`, `created_at` | Identity |
| `profile`, `language`, `duration_seconds` | Copied out of the result for quick listing later |
| `schema_version` | Version of the result's JSON shape |
| `settings_version` | Version of the thresholds that produced it |
| `revision` | 1 today. A later re-analysis will be added as a new row, never written over this one |
| `result` | The whole result, as JSON |
| `audio_path` | Only if the recording was kept |

**`worker_state`** — a single row.

| Column | Meaning |
| --- | --- |
| `pid` | The worker's process number |
| `started_at`, `heartbeat_at` | When it started and when it last reported |
| `speech_model`, `speech_model_ready` | Which model, and whether it is on disk |

### Migrations

Tables are never created by hand. Every change to the structure is a **migration**: a
numbered script in `migrations/versions/`. Running `uv run alembic upgrade head` applies any
that have not run yet, so every copy of the database ends up with the same structure.

To change a table: edit `app/models.py`, then run
`uv run alembic revision --autogenerate -m "what changed"`, read the generated file, and run
`uv run alembic upgrade head`. The test in `tests/test_migrations.py` fails if `models.py`
and the migrations ever disagree.

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

The audio thresholds (what counts as a pause, and so on) are not environment variables.
They live in `app/pipeline/settings.py` and are described in the science document.

## 8. What is and is not written to logs

The worker prints lines like these, and nothing more:

```
01:07:49 INFO job d10fd104 started (attempt 1)
01:07:49 INFO job d10fd104: transcribing
01:08:14 INFO job d10fd104 succeeded in 25.1s
```

- **Never logged:** audio, transcripts, file names, file paths.
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

### B16. Results are never updated in place

- **Chosen:** an analysis row is written once. `revision` and the stored settings exist so
  that a later re-analysis becomes a new row.
- **Why:** old results must stay explainable by the settings that produced them, which the
  calibration feature in Phase 6 depends on.

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
- **Why:** the same descriptions will be handed to the AI model for coaching. One source
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

### Decisions already made for later phases *(not built yet)*

| Topic | Decision | Instead of |
| --- | --- | --- |
| AI model | The local Ollama `llama3.1:8b`, behind a small wrapper so it can be swapped | LiteLLM or any cloud model |
| Where the AI call runs | In the worker, as one more stage (`generating_feedback`) | In the API request |
| If the AI model is unavailable | The measured result is still saved and shown | Failing the whole job |

## 10. Tests

Run with the command in the README. Current result: **162 pass**, 1 skipped (the opt-in
real-speech test, which also passes when run).

| Test file | Tests | What it proves |
| --- | --- | --- |
| `test_segmentation.py` | 20 | Segments and pauses from speech regions; threshold edges; long silences; word assignment |
| `test_metrics.py` | 23 | WPM with pauses excluded and included; reliability flags; typical pace and faster/slower; pause statistics; no division by zero |
| `test_audio_and_acoustics.py` | 20 | Decoding, length limit, clipping, loudness in dB, pitch, emphasis candidates, hesitation sounds |
| `test_pipeline.py` | 24 | The whole pipeline with scripted speech: numbers, warnings, no-speech, garbled transcripts, cancellation |
| `test_job_queue.py` | 25 | Every status change: claim order, duplicates, cancel, fail, retry, expiry, crash recovery, liveness |
| `test_worker.py` | 16 | Real jobs end to end: success, clean-up, failure messages, cancel mid-job, graceful stop, recovery |
| `test_api.py` | 23 | Submitting, polling, cancel, retry, every refusal, the full upload → poll → result journey |
| `test_history_api.py` | 10 | Form options, the history list and paging, kept-audio playback and deletion, deleting one analysis, clearing history without touching work in progress |
| `test_migrations.py` | 1 | The migrations build exactly the tables the code expects |
| `test_real_speech.py` | 1 | Opt-in: the real speech detector and model on synthesised speech with known silences |

How the tests stay fast and exact: the slow parts (speech detection, transcription, pitch)
are passed into the pipeline as replaceable pieces, so most tests script them — "speech from
1 s to 5 s, twelve words" — and check numbers that can be worked out by hand. Time is a fake
clock the test moves forward. Each test gets its own temporary database and data folder.

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
