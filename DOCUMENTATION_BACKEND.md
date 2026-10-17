# Monologue Coach — Backend Documentation

The Python side of the app: the API, the database, the job queue, and the worker that does
the slow work: measuring the audio and getting the coaching written.

- Start with [DOCUMENTATION.md](DOCUMENTATION.md) for the big picture and the glossary.
- **What** is measured in the audio, how the coaching is produced and checked, and why those
  methods were chosen, is in [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md). This file
  covers **how the work is organised**: requests, jobs, files and tables.
- The browser side is in [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md).

Everything described here is built.

**Last updated:** end of Phase 11 (analyses can be downloaded as Markdown: one analysis,
a monologue with its takes, the General Practice takes, or everything; two new endpoints,
one new file, nothing new stored). Before that, Phase 10 (a phrase ends only at a pause of a second or more, and
shorter pauses stay inside it; the delivery pace beside the speaking speed: new fields in
the stored result, one new file that reads old and new results alike, no new endpoint, no
new table, no migration). Before that, Phase 9 (where the voice sits: resonance is measured, pitch and
resonance are placed in three ranges for every phrase and for the recording, and a
recording can be submitted with a voice goal: two new pipeline files, one new form field,
one new column, no new endpoint and no new table). Before that, Phase 8 (a take remembers
the monologue it was recorded for).

## Contents

1. [The three programs](#1-the-three-programs)
2. [Folder structure](#2-folder-structure)
3. [The API list](#3-the-api-list)
4. [Background jobs (and why there is no Celery)](#4-background-jobs-and-why-there-is-no-celery)
   - [4a. Feedback, calibration and revisions](#4a-feedback-calibration-and-revisions)
   - [4b. Monologues and their takes](#4b-monologues-and-their-takes)
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
| **API** | `uv run uvicorn app.main:app --reload --port 4321` | Answers the browser's requests. Never does slow work. | As long as you use the app |
| **Worker** | `uv run python -m app.worker` | Takes jobs from the queue one at a time: analyses the audio, then gets the coaching written. | As long as you use audio analysis |
| **Model download** | `uv run python -m app.speech_model download` | Fetches the speech model. The only step that uses the internet. | Once |

The API and the worker, together with the frontend, can also be started with one command
from the project's top folder: `./run.sh`. What that script does, and why it is written
the way it is, is in decision B56.

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
│   ├── monologues.py     A monologue: a reference recording and the takes recorded for it
│   ├── feedback.py       Saving feedback, and working out what each piece of it does
│   ├── feedback_summary.py   What all the feedback adds up to: the facts, the notes, and
│   │                     the few notes the AI model picks out
│   ├── revisions.py      Later results of one recording: corrected transcripts, fresh analyses
│   ├── stretches.py      Reads the stretches and paces of a stored result, old or new
│   ├── export.py         Writes stored analyses out as Markdown documents
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
│   │   ├── monologues.py GET /api/monologues, DELETE /api/monologues/{id}
│   │   ├── export.py     GET /api/analyses/{id}/export, GET /api/export
│   │   └── feedback.py   Feedback on an analysis; the calibration: read, undo, reset, on/off;
│   │                     what the feedback adds up to
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
│       ├── segmentation.py   Speech regions -> stretches, pauses and segments
│       ├── metrics.py        Delivery pace, speaking speed and pause statistics
│       ├── acoustics.py      Loudness, pitch, emphasis candidates
│       ├── resonance.py      Resonance: how deep or bright the voice sounds, from its formants
│       ├── voice_range.py    The three ranges for pitch and for resonance; the voice goals
│       ├── fillers.py        Hesitation sounds
│       ├── waveform.py       The outline of the sound wave, for drawing only
│       ├── settings.py       The thresholds (0.5 s pause, 1 s segment break, 5 s long silence…)
│       └── errors.py         Errors with a code and a message safe to show
├── migrations/
│   ├── env.py            Tells the migration tool where the database is
│   └── versions/
│       ├── 0001_jobs_analyses_and_worker_state.py   Creates the three tables
│       ├── 0002_coaching.py                         Adds the four coaching columns
│       ├── 0003_references_and_waveforms.py         Adds role, title and the waveform outline
│       ├── 0004_feedback_and_calibration.py         Adds feedback, calibration and revisions
│       ├── 0005_feedback_summary.py                 Adds the notes the AI model picked out
│       ├── 0006_monologue_takes.py                  Adds the monologue a take was recorded for
│       └── 0007_voice_goal.py                       Adds the voice goal a recording was submitted with
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
| What may be said about a reference recording, and what not? | `app/feedback.py` (`save`) |
| Why did reports on a reference not move a setting? | `app/calibration/engine.py` (`Tally.enough`) |
| What are the lines under "What your feedback adds up to"? | `app/feedback_summary.py` (`build_digest`) |
| What is the AI model asked about my notes, and what is done with its answer? | `app/feedback_summary.py` (`build_prompt`, `read_answer`) |
| How is WPM worked out again after a transcript correction? | `app/transcript_correction.py` |
| How does a recording get a second result? | `app/revisions.py` |
| What is a monologue made of, and what goes when one is deleted? | `app/monologues.py` |
| Why is this take not in the General Practice history? | `app/history.py` (`_scope`) |
| What do the delivery profiles say? | `app/profiles.py` |
| What columns does a table have? | `app/models.py` |

## 3. The API list

An **API endpoint** is an address the frontend can send a request to. Each one has a method
(`GET` to read, `POST` to create or do something) and a path. While the API is running, an
interactive version of this list is at `http://localhost:4321/docs`.

### Built

| Method | Path | What it does | Defined in |
| --- | --- | --- | --- |
| `GET` | `/api/health` | Is the API up, can it reach the database, is a worker alive, is the speech model present, is the AI model available | `routes/health.py` |
| `POST` | `/api/analyses` | Accepts a recording (a take, a take of a monologue, or a reference), queues a job, answers at once with the job | `routes/analyses.py` |
| `GET` | `/api/jobs/{jobId}` | Where a job has got to. Made to be polled | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/cancel` | Asks for a job to stop | `routes/jobs.py` |
| `POST` | `/api/jobs/{jobId}/retry` | Puts a failed job back in the queue | `routes/jobs.py` |
| `GET` | `/api/analyses/{analysisId}` | The stored result of a finished analysis, with its coaching | `routes/analyses.py` |
| `POST` | `/api/analyses/{analysisId}/coaching` | Queues a job that has the AI model write this analysis's coaching again | `routes/analyses.py` |
| `GET` | `/api/analysis-options` | What the form offers: profiles, languages, upload limits | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/comparison/{referenceId}` | Sets an analysis against a reference recording | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/waveform` | The outline of the recording's sound wave, for drawing | `routes/analyses.py` |
| `GET` | `/api/analyses` | Past takes, newest first, with their headline numbers: all of them, one monologue's with `?monologue=<id>`, or those of no monologue with `?monologue=none`. The reference recordings with `?role=reference` | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}` | Deletes one analysis (take or reference), its kept recording and its job | `routes/analyses.py` |
| `DELETE` | `/api/analyses` | Clears the history of takes, narrowed the same way by `?monologue=`; or the references with `?role=reference` | `routes/analyses.py` |
| `GET` | `/api/monologues` | The monologues: each a reference recording in its newest revision, with a count of its takes | `routes/monologues.py` |
| `DELETE` | `/api/monologues/{monologueId}` | Deletes a monologue: its reference in every revision, and all its takes | `routes/monologues.py` |
| `GET` | `/api/analyses/{analysisId}/audio` | The recording itself, if it was kept | `routes/analyses.py` |
| `DELETE` | `/api/analyses/{analysisId}/audio` | Deletes only the kept recording | `routes/analyses.py` |
| `GET` | `/api/analyses/{analysisId}/feedback` | The feedback given on one analysis, with what each piece does, and the calibration | `routes/feedback.py` |
| `POST` | `/api/analyses/{analysisId}/feedback` | Saves one piece of feedback. Adjusts a setting if this completes a run of reports that agree | `routes/feedback.py` |
| `DELETE` | `/api/feedback/{feedbackId}` | Takes one piece of feedback back | `routes/feedback.py` |
| `GET` | `/api/calibration` | The settings in force: every value, its range, what changed it and why | `routes/feedback.py` |
| `POST` | `/api/calibration/undo` | Puts back the value the most recent adjustment replaced | `routes/feedback.py` |
| `POST` | `/api/calibration/reset` | Returns every setting to its default | `routes/feedback.py` |
| `PUT` | `/api/calibration/adaptive` | Switches automatic adjustment on or off | `routes/feedback.py` |
| `POST` | `/api/analyses/{analysisId}/transcript` | Stores a new revision of a take or a reference with corrected words, with WPM worked out again | `routes/analyses.py` |
| `POST` | `/api/analyses/{analysisId}/reanalysis` | Queues a fresh analysis of the kept recording, with the settings in force now | `routes/analyses.py` |
| `GET` | `/api/feedback-summary` | What all the stored feedback adds up to: the facts counted by code, the notes, and the notes the AI model last picked out | `routes/feedback.py` |
| `POST` | `/api/feedback-summary` | Queues a job that asks the AI model to pick out the most telling notes | `routes/feedback.py` |

Submitting, jobs, results and coaching are tested in `tests/test_api.py`; lists, deleting,
kept audio, references, waveforms and the comparison in `tests/test_history_api.py`;
feedback and calibration in `tests/test_feedback_api.py`; corrected transcripts and fresh
analyses in `tests/test_revisions.py`; what the feedback adds up to in
`tests/test_feedback_summary.py`; monologues and their takes in `tests/test_monologues.py`.

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

**A take of a monologue.** One more optional field says which monologue a take was
recorded for:

| Field | Values | Meaning |
| --- | --- | --- |
| `monologueId` | The ID of a monologue, or of its reference recording in any revision | The take is stored under that monologue: listed with `?monologue=<id>`, and no longer in the General Practice history. Ignored for a reference |

It is checked before the file is saved, so an unknown one costs nothing: `404`
`monologue_not_found`. The job's status carries it back as `monologueId`, and so does the
result. Section 4b explains what a monologue is.

**A voice goal.** Since Phase 9, one more optional field:

| Field | Values | Meaning |
| --- | --- | --- |
| `voiceGoal` | `none` (default), `lower`, `higher` | Whether the speaker wants to keep their voice in the lower or the higher range. Ignored for a reference, which is always stored with `none` |

Where the voice sat is measured whatever is sent. The goal decides only whether the
coaching reads it as something to work on (the science document, section 13). Any other
value is refused with `422` `invalid_request`. The job's status carries it back as
`voiceGoal`, and the result as `voiceRange.goal`.

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
| `monologueId` | The monologue the take being analysed was recorded for. `null` for a reference and for a take of none. Not in the example above, which is a General Practice take |
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

Since Phase 8 a result also carries `monologueId`: the monologue the take was recorded for,
or `null`. It is read from its own column when the result is asked for, and is not part
of the stored measurements (decision B58).

Since Phase 10 a phrase (a segment) can hold pauses, and the result says so in five
places. What the terms mean is in the science document, section 4.

```json
"segments": [
  { "id": "seg-1", "startSeconds": 0.0, "endSeconds": 5.0,
    "speechActiveSeconds": 4.4, "pauseCount": 1, "pauseSeconds": 0.6,
    "wordCount": 10, "deliveryWpm": 120.0, "segmentWpm": 136.4, "…": 0 }
],
"stretches": [
  { "index": 0, "startSeconds": 0.0, "endSeconds": 2.0, "segmentId": "seg-1" },
  { "index": 1, "startSeconds": 2.6, "endSeconds": 5.0, "segmentId": "seg-1" },
  { "index": 2, "startSeconds": 6.5, "endSeconds": 10.5, "segmentId": "seg-2" }
],
"pauses": [
  { "id": "pause-1", "index": 0, "durationSeconds": 0.6, "insideSegment": true,
    "afterSegmentId": "seg-1", "beforeSegmentId": "seg-1", "…": 0 },
  { "id": "pause-2", "index": 1, "durationSeconds": 1.5, "insideSegment": false,
    "afterSegmentId": "seg-1", "beforeSegmentId": "seg-2", "…": 0 }
],
"words": [ { "text": "who", "segmentId": "seg-1", "stretchIndex": 1, "…": 0 } ],
"metrics": { "deliveryWpm": { "value": 140.0, "unit": "words/minute", "quality": "measured", "note": "…" } }
```

| Field | Meaning |
| --- | --- |
| `segments[].deliveryWpm` | The phrase's words ÷ its whole length, the pauses inside it counted. The figure the screen shows first and `paceVsTypical` is judged on |
| `segments[].segmentWpm` | Its words ÷ its speaking time: the speaking speed. The same field and the same formula as before Phase 10 |
| `segments[].speechActiveSeconds`, `pauseCount`, `pauseSeconds` | Time spent speaking in the phrase, and the pauses it holds. Its whole length is `endSeconds − startSeconds` |
| `stretches` | Every unbroken run of speaking, in order, with the segment it belongs to. Pause number *n* lies between stretch *n* and stretch *n + 1* |
| `pauses[].insideSegment` | True for a pause shorter than the segment break. `afterSegmentId` and `beforeSegmentId` are then the same segment |
| `words[].stretchIndex` | The stretch the word was spoken in: which side of a pause it is on |
| `metrics.deliveryWpm` | The recording's delivery pace. `speechActiveWpm` is still there, and is the speaking speed |
| `settings.segment_break_ms` | How long a pause had to be to end a phrase: 1000. `settings.version` is 3 |

A result stored before Phase 10 has `stretches: null`, `metrics.deliveryWpm: null`, no
`deliveryWpm` on its segments and no `insideSegment: true`. It is not filled in afterwards.
Every reader goes through `app/stretches.py`, which gives such a result the shape it
really has: one stretch per segment, and its one pace as its delivery pace (decision B69).

Since Phase 9 a result also says **where the voice sat**. For the whole recording:

```json
"voiceRange": {
  "goal": "lower",
  "pitch":     { "valueHz": 125.3, "band": "lower", "percent": 33, "quality": "measured" },
  "resonance": { "valueHz": 1017.0, "band": "lower", "percent": 23, "quality": "measured" },
  "marker": "lower",
  "formantsHz": [452, 1410, 2623],
  "phrases": { "lower": 4, "neutral": 0, "higher": 0, "mixed": 0, "unmeasured": 0 },
  "bands": { "version": 1,
             "pitch_low_end_hz": 85.0, "pitch_neutral_from_hz": 145.0,
             "pitch_neutral_to_hz": 175.0, "pitch_high_end_hz": 255.0,
             "resonance_low_end_hz": 940.0, "resonance_neutral_from_hz": 1040.0,
             "resonance_neutral_to_hz": 1100.0, "resonance_high_end_hz": 1300.0 },
  "resonanceNote": null
}
```

and inside each entry of `segments`, the same for that phrase:

```json
"voice": {
  "pitch":     { "valueHz": 131.0, "band": "lower", "percent": 23, "quality": "measured" },
  "resonance": { "valueHz": 1052.8, "band": "neutral", "percent": 43, "quality": "estimated" },
  "marker": "lower"
}
```

| Field | Meaning |
| --- | --- |
| `goal` | The voice goal the recording was submitted with |
| `pitch`, `resonance` | The value in Hz, the range it falls in (`lower`, `neutral`, `higher`), how far into that range it lies (0 to 100), and whether it is `measured` or `estimated`. `null` when it could not be measured: never a zero |
| `marker` | Pitch and resonance together: `lower`, `neutral`, `higher`, or `mixed` when one is lower and the other higher. `null` when neither was measured |
| `formantsHz` | The three typical formants the resonance figure was worked out from |
| `phrases` | How many phrases got each marker |
| `bands` | The ranges that placed the values, with their version: a copy of `VoiceRangeSettings` |
| `resonanceNote` | Why resonance is an estimate or is missing, in words, when it is |

`voiceRange` is `null` for a recording with no speech, and absent from a result stored
before Phase 9, as is `voice` on its segments. Nothing is filled in afterwards (decision
B64). How each value is measured, and what the percentage means, is in sections 9a and 9b
of the science document.

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

The endpoint itself compares any analysis with any reference, as it always has. That a
take is compared only with the original of its own monologue is the screens' doing: the
frontend asks for no other pair (frontend document, 6.14).

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

Saves one piece of feedback on an analysis: one of your own takes, or a reference
recording. The body is JSON:

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

**On a reference recording** the four report categories, the two WPM categories and
`transcript_wrong` are taken as on a take. The two labels and the two ratings are refused
(`409 not_for_reference`): a reference has no coaching for a label to change or a rating
to be about. A report on a reference counts towards a setting like any other, with one
difference that is decided when the reports are counted, not when they are saved: a
setting moves only if at least one of the reports that agree is about a take of your own.
Until then `status` and each report's `message` end "All of them are about reference
recordings, and a setting moves only once a take of your own shows the same thing."

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
correction); `409 not_for_reference` (a label or a rating on a reference);
`422 outside_target` (the time is not inside the phrase); `422 invalid_request`.

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
      "pending": { "raiseCount": 0, "lowerCount": 0, "recordings": 0, "needed": 3, "takeReports": 0 },
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
  "rules": { "minReports": 3, "minRecordings": 2, "minTakeReports": 1, "minAgreement": 0.75, "window": 10, "reversalReports": 5 }
}
```

| Field | Meaning |
| --- | --- |
| `version` | The version new analyses are made with |
| `adaptive` | `false` when the user has switched automatic adjustment off |
| `state` | `calibrating` while every setting is still at its default; `adjusted` otherwise |
| `settings` | The 15 adjustable settings: the minimum pause, and a priority for each of the 14 kinds of correction (12 until Phase 9 added the two about where the voice sits). Each has explicit bounds |
| `fixed` | The thresholds feedback never changes, shown so that nothing is hidden |
| `changes` | The history, newest first. `cause` is `defaults`, `auto`, `undo` or `reset` |
| `pending.takeReports` | How many of the waiting reports on the larger side are about your own takes. `rules.minTakeReports` (1) of them are needed before the setting can move |

| Request | What it does | Refused with |
| --- | --- | --- |
| `POST /api/calibration/undo` | Adds a version that puts back the value the most recent adjustment replaced | `409 nothing_to_undo` |
| `POST /api/calibration/reset` | Adds a version with every default, and sets aside the reports that were waiting | `409 already_default` |
| `PUT /api/calibration/adaptive` with `{ "enabled": false }` | Switches automatic adjustment off. Feedback is still saved; no setting moves. Switching it on again acts on what built up | |

All three answer with the calibration in the shape above.

### `POST /api/analyses/{analysisId}/transcript`

Corrects the words of one or more phrases of a take or of a reference recording, and
stores the outcome as a **new revision**. It answers `201` with the new result, at once:
there is no job, because no audio is read.

```json
{ "corrections": [ { "segmentId": "seg-1", "text": "You clearly do not know who you are talking to" } ] }
```

Word counts and the three WPM figures are worked out again from the corrected words and
each phrase's own measured length (science document, section 15). Everything measured from
the sound is copied unchanged. The result that was corrected is not modified. The new
revision of a take gets coaching from the fixed rules straight away, with a notice saying
the AI model has not been asked yet. The new revision of a reference keeps its role and
its title and, like every reference, has no coaching. Both revisions of a reference stay
in the library; a comparison is with whichever one is asked for.

Refusals: `400 nothing_changed` (the words are the same as before); `404 unknown_target`;
`404 analysis_not_found`.

### `POST /api/analyses/{analysisId}/reanalysis`

Queues a fresh analysis of this result's **kept** recording, with the settings in force
now, and answers `202` with a job to poll, exactly as an upload does. The job's
`sourceAnalysisId` says which result it started from. The outcome is stored as a further
revision; the earlier result is not changed. Asking again while one is queued or running
returns that job (`200`). The fresh analysis keeps the voice goal of the result it started
from.

Refused with `409 audio_not_kept` when the recording was not kept.

### `GET /api/feedback-summary`

What everything said so far adds up to. Nothing is stored to answer it except the model's
last pick: the facts and the notes are read from the `feedback` table each time.

```json
{
  "feedbackCount": 12,
  "facts": [
    { "id": "f1", "text": "12 pieces of feedback in all, on 3 recordings: 6 on your own takes and 6 on reference recordings." },
    { "id": "f2", "text": "What it is about, largest group first: missed pauses (5), WPM figures (3), pauses you labelled (2), coaching corrections (1), wrong words (1)." },
    { "id": "f5", "text": "Missed pauses you reported: 5. At 5 of them the detector had heard a silence lasting between 324 and 356 ms, which was shorter than the minimum pause at the time and so was not counted as a pause." }
  ],
  "notes": [
    { "about": "a pause you said the app missed", "text": "he stops for a beat here in the film" }
  ],
  "noteCount": 10, "pickableNotes": 9, "minNotes": 5,
  "picked": {
    "notes": [ { "about": "a pause you said the app missed", "text": "yahan maine jaan-boojhkar ruka tha" } ],
    "model": "llama3.1:8b", "modelSeconds": 2.5, "generatedAt": "2026-10-11T10:18:02Z",
    "noteCount": 10, "stale": false
  },
  "job": null
}
```

| Field | Meaning |
| --- | --- |
| `facts` | Sentences written by code from the stored feedback, in a fixed order. Each is about one thing only, and no two count the same feedback |
| `notes` | The most recent 15 notes, oldest first, word for word, each with what it was written about |
| `noteCount` | Every note there is, including any too old to be listed |
| `pickableNotes` | The listed notes of three words or more: the only ones the AI model is offered |
| `minNotes` | The AI model is asked only when it can be offered at least this many (5) |
| `picked` | The notes the AI model last picked, as they read when it picked them, the most telling first. `null` until it has been asked. `stale` is `true` once the notes have changed |
| `job` | The request to the AI model while it is queued or running, and after it failed until a later pick is stored. The usual job shape, with `kind` `"summary"` |

How the facts are worded and why the AI model is only allowed to pick is in the science
document (section 15).

### `POST /api/feedback-summary`

Queues a job of kind `summary` and answers `202` at once, in the shape above with `job`
filled in. There is no separate job to poll: `GET /api/feedback-summary` says how it is
going. Asking again while one is queued or running returns the same job (`200`). The job
can be cancelled like any other, with `POST /api/jobs/{jobId}/cancel`.

Refused with `409 too_few_notes` when fewer than five notes are worth offering.

A summary job that fails says why in `job.error` (`not_running`, `model_missing`,
`ai_off`, `timeout`, `bad_answer`) and stores nothing. It is never retryable: there is no
audio to keep for it, and asking again costs a click.

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

Since Phase 9 the answer also lists the voice goals, with the note the form shows under
them. The texts live in `app/pipeline/voice_range.py`:

```json
"voiceGoals": [
  { "id": "none", "label": "No goal", "note": null },
  { "id": "lower", "label": "Keep my voice lower",
    "note": "Coaching will point at the phrases where your pitch or resonance left the lower range." },
  { "id": "higher", "label": "Keep my voice higher", "note": "…" }
],
"voiceGoalNote": "Optional. The app measures where your voice sits, in pitch and in resonance, whether or not you choose a goal. …"
```

The profile texts live in `app/profiles.py`. `focus[].metric` is the JSON name of a real
metric in the result (since Phase 10 a profile that cares about pace points at
`deliveryWpm`, where it used to point at `speechActiveWpm`); a test fails if a profile points at a metric that does not exist.

### `GET /api/analyses`

Query parameters: `limit` (1–100, default 20), `offset` (default 0), `role` (`take` by
default, or `reference`) and `monologue`. Takes and references are never mixed in one
list. Each item also carries its `role`, a reference its `title`, and a take its
`monologueId`.

| `monologue` | Lists |
| --- | --- |
| left out | Every take, as before Phase 8 |
| `none` | The takes that belong to no monologue: the General Practice history |
| a monologue's ID, or the ID of its reference in any revision | The takes recorded for that monologue |

An ID that names no monologue is `404` `monologue_not_found`. The parameter means nothing
for `role=reference` and is ignored there.

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
| `DELETE /api/analyses?monologue=none` | The same, but only for takes that belong to no monologue. This is what "Clear all history" on General Practice sends | Every monologue's takes, as well |
| `DELETE /api/analyses?monologue=<id>` | The same, but only for that monologue's takes | The monologue itself, and every other take |
| `DELETE /api/analyses?role=reference` | The same, for the references. Their takes are kept and become takes of no monologue | Every take |
| `DELETE /api/monologues/{id}` | A monologue whole: every revision of its reference, every take recorded for it, their kept recordings, jobs and feedback | Everything else |

Deleting a reference with `DELETE /api/analyses/{id}` removes that one revision. While
another revision remains, the monologue remains, under the same ID. When the last one
goes, its takes are not deleted: they become takes of no monologue, and show in the
General Practice history. To delete a monologue *with* its takes, use
`DELETE /api/monologues/{id}`.

Clearing answers with what it removed: `{ "deletedAnalyses": 2, "deletedJobs": 3 }`.
The single-item deletes answer `204` with no body, or `404` (`analysis_not_found`,
`audio_not_kept`).

### `GET /api/monologues`

```json
{ "items": [ { "monologueId": "16bb16d4…", "referenceId": "ae81ea40…",
               "title": "The one who knocks", "createdAt": "2026-10-11T16:25:02Z",
               "language": "en", "durationSeconds": 14.538, "audioRetained": true,
               "revision": 2, "revisionCount": 2,
               "takeCount": 3, "lastTakeAt": "2026-10-11T16:29:41Z",
               "settings": { "version": 1, "min_pause_ms": 500, "…": 0 } } ] }
```

| Field | Meaning |
| --- | --- |
| `monologueId` | Names the monologue. It is the ID of the first analysis of its reference recording, and never changes |
| `referenceId` | The reference to compare takes with: the newest revision. Equal to `monologueId` until the reference is corrected or measured again |
| `title`, `language`, `durationSeconds`, `audioRetained`, `settings` | Those of that newest revision |
| `createdAt` | When the reference was first added |
| `revision`, `revisionCount` | The newest revision's number, and how many revisions are stored |
| `takeCount` | How many takes were recorded for it. A take with a corrected transcript, or analysed again, is still one take |
| `lastTakeAt` | When the newest of them was analysed. `null` with no takes |

The one practised or added most recently comes first. There is no paging: a list of
monologues is short. There is also no endpoint that *adds* a monologue: submitting a
recording with `role=reference` is what adds one.

### `DELETE /api/monologues/{monologueId}`

Answers `200` with what went: `{ "deletedReferences": 2, "deletedTakes": 3 }`. The ID may
be the monologue's own or that of any revision of its reference.

| Refusal | When |
| --- | --- |
| `404 monologue_not_found` | No such monologue. The ID of a take is not one |
| `409 monologue_busy` | A recording of this monologue is still queued or being analysed: a take of it, a fresh analysis of its reference, or new coaching for one of its takes. Nothing is deleted. Wait, or cancel the job, and ask again |

### `GET /api/analyses/{analysisId}/export` and `GET /api/export`

Added in Phase 11. Both answer with a Markdown document (`text/markdown; charset=utf-8`)
and the header `Content-Disposition: attachment`, so a browser saves it as a file.

| Request | The document holds | File name |
| --- | --- | --- |
| `GET /api/analyses/{id}/export` | That one analysis, in the revision asked for | `monologue-coach-take-<date>-<id>.md`, or `…-<title>-<date>-<id>.md` for an original |
| `GET /api/export` or `?scope=all` | Every monologue with its takes, oldest monologue first, then the General Practice takes | `monologue-coach-all-<date>.md` |
| `GET /api/export?scope=monologue&monologue=<id>` | One monologue: its original, then the takes recorded for it, oldest first | `monologue-coach-<title>-<date>.md` |
| `GET /api/export?scope=general` | The takes that belong to no monologue | `monologue-coach-general-practice-<date>.md` |

`404 analysis_not_found` or `404 monologue_not_found` for an unknown ID (a take's ID is
not a monologue); `422` for an unknown scope.

What is written for each analysis, in this order:

| Part | What it holds |
| --- | --- |
| A table at the top | What it is (an original, a take of which monologue, or a General Practice take), its ID, when it was analysed, which revision, the file's name, profile, language, length, whether the recording was kept, the voice goal |
| Warnings | As stored |
| Settings | Every setting the result was measured with |
| Measurements | Every metric by its JSON name, with its unit and quality. A metric the result does not have is left out; one that could not be measured is a dash |
| Phrases | One row per phrase: times, length, words, speaking time, pauses inside, both paces, faster or slower than typical, whether trusted and why not, loudness and pitch against the typical phrase, where the voice sat, and the words with each pause inside the phrase marked ‖0.6 s‖ where it fell. An older result has one pace column |
| Pauses | Every pause: when, how long, its kind, inside which phrase or between which two, the words before it, and the user's label if any |
| Where the voice sits | Pitch, resonance, the marker, the goal, the phrase counts and the ranges used |
| Words that stood out, hesitation sounds, transcript | As stored |
| Coaching (a take) | Who wrote it and when, the bands behind its wording, the summary, **every finding** with its level and role, the corrections with their drills, what works, the targets, the caveats |
| How the app's bands read this recording (an original) | The findings a coaching would start from, worked out now with today's bands. Not stored (decision B76) |
| Feedback given | Each piece, with what it does |
| Against the original (a take of a monologue) | The comparison: the note on the line-up, the biggest differences, the recordings as wholes, pause by pause, phrase by phrase |

In a document of several analyses each recording is given once, in its **newest
revision**. Writing a document reads the stored results and changes none of them.

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
| `summarising_feedback` | Only in a `summary` job: the AI model picks out the most telling notes | 2 to 5 seconds, whatever the number of recordings |

**Two roles.** An analysis job is for a `take` or a `reference`. A reference job runs the
first four stages and stops: it has no `generating_feedback` stage and never calls the AI
model. On this machine a 133-second reference took 24.6 seconds; the same recording as a
take, with AI coaching, took 72.8.

**Three kinds of job.** Everything above describes an `analysis` job. A `coaching` job is
the small one created by `POST /api/analyses/{id}/coaching`: it has no audio, goes straight
to `generating_feedback`, and replaces only the coaching of an analysis that already exists.
A `summary` job, created by `POST /api/feedback-summary`, is smaller still: it has neither
audio nor an analysis. Its one stage is `summarising_feedback`, in which the AI model is
asked which of the user's notes are the most telling, and its outcome is one row in the
`feedback_summary` table. It takes two to five seconds. All three kinds sit in the same
table, wait in the same queue and are run by the same worker, one at a time, so the speech
model and the AI model are never working at the same moment.

A job row always has a `role`, a `profile` and a `language_hint`, because the first kind of
job needs them. A summary job fills them with the defaults (`take`, `custom`, `auto`); they
mean nothing for it.

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
| `create_summary_job` | `POST /api/feedback-summary` | Insert a queued summary job, or return the one already in progress |
| `find_by_idempotency_key` | `POST /api/analyses` | Detect a repeated submission |
| `to_status` | every job endpoint | Build the JSON status |
| `request_cancel` | `POST …/cancel` | Cancel now, or set the flag |
| `retry_job` | `POST …/retry` | Put a failed job back in the queue |
| `claim_next_job` | worker | Take the oldest queued job |
| `set_stage`, `touch_job` | worker | Report progress and heartbeat |
| `is_cancel_requested` | worker (`check`) | Read the cancel flag |
| `complete_job`, `fail_job`, `finish_cancelled`, `release_job` | worker | The four ways a run ends |
| `complete_coaching_job` | worker | Replace an analysis's coaching and mark the coaching job succeeded |
| `complete_summary_job` | worker | Store the picked notes in place of the last pick and mark the summary job succeeded |
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

### Feedback on a reference recording

A reference is an analysis like any other, with `role` `reference`, so the same endpoints
serve it. Three things differ, each in one place:

| What | Where | How |
| --- | --- | --- |
| Labels and ratings are refused | `feedback.save` | A reference has no coaching. `409 not_for_reference` |
| Its reports cannot move a setting alone | `calibration/engine.py`, `Tally.enough` | Each report carries `own_take`, read from the analysis's role when the reports are counted (`store.pending_reports`). An adjustment needs `MIN_TAKE_REPORTS` (1) of the agreeing reports to have it |
| A corrected reference has no coaching | `revisions.create_corrected` | The new revision is stored with `coaching` empty, like the reference it came from |

Nothing about a report on a reference is stored differently. That is on purpose: whether
it may count is a rule about the whole set of waiting reports, so it is decided when they
are counted. If the rule is ever changed, the stored reports need no migration.

The wording of two messages also depends on whose recording it is, because "if you were
still speaking" is wrong about a film clip: the note on a pause too long to be explained
by any setting (`feedback.UNHEARD`), and the review of a WPM figure (`wpm_review.review`,
`on_reference=True`).

### What the feedback adds up to

`feedback_summary.py` has two halves that never mix.

**The facts** (`build_digest`). Every request to `GET /api/feedback-summary` reads the
whole `feedback` table, joined to `analyses` for the role, and writes ten or so sentences:
how much feedback, what it is about, each kind with its measured figures, the settings,
the notes. Nothing is cached. The table is small (a few rows per recording) and the
sentences must always agree with it, so working them out again costs less than keeping a
copy honest.

**The pick** (`build_prompt`, `read_answer`, `pick`). A `summary` job gives the AI model
the notes, numbered `n1`, `n2`, …, and asks for the numbers of the three most telling.

```
 POST /api/feedback-summary ──▶ jobs row (kind "summary", queued)
                                        │
 worker: build_digest ─▶ build_prompt ─▶ AI model ─▶ read_answer ─▶ feedback_summary row (id 1)
                                                        │
                              names only: ["n4", "n1", "n6"] ──▶ those notes, copied word for word
```

Four details of that path:

- **Only notes worth offering are offered.** A note of fewer than three words is left out
  of the prompt (`Digest.candidates`). The names in the answer are mapped back to
  positions in the full list (`Prompt.names`).
- **The answer can only name a note that exists.** The JSON schema sent to Ollama lists
  the allowed names as an `enum`, so the model cannot produce any other.
- **`read_answer` is forgiving and strict in the right places.** A name given twice counts
  once, a name that is no note is passed over, extra names are dropped. Fewer than two
  different notes is no pick: the model is asked once more, and then the job fails.
- **What is stored is the notes, not the names.** `feedback_summary.picked` holds each
  picked note's text and what it was about, as they read at the time, so the pick still
  shows correctly after a note is edited. A fingerprint of the notes it was picked from is
  stored beside it; when the current notes give a different fingerprint, the answer says
  `stale`.

The worker does this in `Worker._sum_up_feedback`. Like a coaching job, it stores nothing
if it is cancelled at the last moment (`complete_summary_job` changes the table and the
job's status in one transaction).

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
| `build_digest` | `feedback_summary.py` | Reads all stored feedback and writes the facts and the list of notes |
| `build_prompt`, `read_answer`, `pick` | `feedback_summary.py` | What the AI model is asked about the notes, and what is made of its answer |
| `describe` | `feedback_summary.py` | Everything `GET /api/feedback-summary` returns |

## 4b. Monologues and their takes

Phase 8 joined the Monologue screen and Daily Practice: the user picks a monologue and
practises it, and each take recorded on the way belongs to that monologue. This section
explains how the backend keeps the two together. All of it is in `app/monologues.py`, a
few lines of `app/history.py`, and one check in `app/job_queue.py`.

### A monologue is not a table

```
 analyses
 ┌──────────┬───────────┬──────────┬──────────┬──────────────┐
 │ id       │ role      │ root_id  │ revision │ monologue_id │
 ├──────────┼───────────┼──────────┼──────────┼──────────────┤
 │ R1       │ reference │ R1       │ 1        │              │ ┐ one monologue: "R1"
 │ R2       │ reference │ R1       │ 2        │              │ ┘ (its original, corrected once)
 │ T1       │ take      │ T1       │ 1        │ R1           │ ┐
 │ T2       │ take      │ T2       │ 1        │ R1           │ │ its takes
 │ T3       │ take      │ T2       │ 2        │ R1           │ ┘ (T3 is T2 with corrected words)
 │ F1       │ take      │ F1       │ 1        │              │   a General Practice take
 └──────────┴───────────┴──────────┴──────────┴──────────────┘
```

- A **monologue** is a reference recording in all its revisions. Its ID is that
  recording's `root_id`: the ID of the first analysis of it. Nothing else is stored.
- A **take of a monologue** is a take whose `monologue_id` is that ID.
- A take whose `monologue_id` is empty belongs to none.

`GET /api/monologues` groups the references by root, takes the newest revision of each
for the title and the figures, and counts the takes that point at it.

### How a take gets its monologue

```
 POST /api/analyses  (monologueId = R2)
        │
        ▼
 monologues.resolve("R2")  ──▶  "R1"      any revision's ID, or the monologue's own, is accepted
        │                                  and turned into the monologue's ID. Unknown: 404.
        ▼
 jobs row:  monologue_id = "R1"
        │   … the worker measures the recording …
        ▼
 job_queue.complete_job:  is there still a reference with root "R1"?
        │        yes ─▶ analyses row:  monologue_id = "R1"
        │        no  ─▶ analyses row:  monologue_id empty   (a take of no monologue)
```

The worker needed no change for this: it hands the job to `complete_job`, which is where
a result has always been given its identity (role, title, revision). A later revision of
the take (a corrected transcript, a fresh analysis) copies the `monologue_id` of the take
it was made from.

### What is linked to what, and why it is the monologue

A take points at the **monologue**, not at the revision of the reference that was newest
when it was recorded. So when the user corrects a word in the original, every take of
that monologue is at once compared with the corrected words, with nothing to update. The
comparison is still asked for with two analysis IDs; the frontend takes the second from
`referenceId`.

### Deleting

| What is deleted | What happens to the rest |
| --- | --- |
| A take | Nothing else |
| One revision of a reference, others remain | The monologue stays, with the same ID and takes |
| The last revision of a reference (`DELETE /api/analyses/{id}`, or clearing the references) | Its takes are **freed**: `history.unlink_orphaned_takes` empties their `monologue_id`, so they show in the General Practice history |
| A monologue (`DELETE /api/monologues/{id}`) | Its references, its takes, their kept audio, their jobs and (through the database) their feedback all go. Refused while one of its recordings is still in the queue |

Freeing is the safety net, and deleting the monologue is the deliberate act. Without the
first, a take could end up pointing at a monologue that no longer exists, and so be
listed nowhere: not under any monologue, and not in the General Practice history, which
only lists takes with no monologue.

### Which function does what

| Function | File | Does |
| --- | --- | --- |
| `resolve` | `monologues.py` | Turns a monologue's ID, or any revision of its reference, into the monologue's ID. `None` if it names none |
| `list_monologues` | `monologues.py` | Everything `GET /api/monologues` returns |
| `delete_monologue` | `monologues.py` | Deletes a monologue whole, or raises `MonologueBusy` |
| `monologue_exists` | `job_queue.py` | Whether any revision of a monologue's reference is still stored |
| `_scope` | `history.py` | The condition "takes of this monologue" / "takes of none" / "every take", for listing and for clearing |
| `unlink_orphaned_takes` | `history.py` | Frees the takes of a monologue whose reference is gone |

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
| `monologue_id` | For a take recorded for a monologue: that monologue's ID. Empty for a reference and for a take of none. Added in Phase 8 |
| `voice_goal` | `none`, `lower` or `higher`: the voice goal the recording was submitted with. Always `none` for a reference. Added in Phase 9; every earlier row has `none` |
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
| `monologue_id` | The monologue a take was recorded for: the `root_id` of that monologue's reference recording. Empty for a reference, and for a take made in General Practice. Indexed, because a monologue's takes are listed by it. Added in Phase 8; every earlier row has it empty |
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

**`feedback_summary`** — a single row (id 1): the notes the AI model last picked out.

| Column | Meaning |
| --- | --- |
| `generated_at`, `model`, `model_seconds` | When it was picked, by which model, and how long the model took |
| `note_count` | How many notes it was picked from |
| `fingerprint` | Identifies those notes. When the notes now give a different one, the pick is out of date |
| `picked` | The picked notes as they read at the time, as JSON: `[{"about", "text"}]`, the most telling first |

The facts shown beside it are not stored anywhere. They are counted from `feedback` each
time they are asked for.

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
| `0005_feedback_summary` | Creates `feedback_summary`. Changes no existing table. The new kind of job, `summary`, needed no migration: `jobs.kind` is text |
| `0006_monologue_takes` | Adds `monologue_id` to `jobs` and to `analyses`, with an index on the second. Existing rows are kept and have it empty: every take stored so far belongs to no monologue, and every reference stored so far is a monologue, because a monologue is nothing but its reference |

| `0007_voice_goal` | Adds `voice_goal` to `jobs`, `none` for every existing row. Nothing is added to `analyses`: where the voice sat, and the goal, are inside the stored result (decisions B63 and B64) |

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
| The user clears the General Practice history | Every kept file of a take that belongs to no monologue is deleted, and any upload a failed job of one was holding |
| The user deletes a monologue | The kept files of its reference, in every revision, and of all its takes are deleted, and any upload a failed job of one was holding |

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

### B49. Feedback is taken on takes only (replaced in Phase 7 by B52)

- **Was chosen in Phase 6:** feedback on a reference recording was refused
  (`409 not_a_take`).
- **Why, then:** calibration is meant to fit the app to *the user's own* recordings: their
  microphone, their room, their way of speaking. A film clip is a different kind of sound,
  often with music, and reports about it would pull the settings the wrong way.
- **What was wrong with it:** it protected the settings by making a reference impossible
  to correct. A misheard word in the reference throws off the line-up of every take
  compared with it, and nothing could be done about it. B52 keeps the protection and drops
  the refusal.

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

### B52. A reference takes feedback; the rule that protects the settings sits in the engine

- **Chosen:** `feedback.save` accepts reports, WPM reviews and transcript flags on a
  reference, and `revisions.create_corrected` accepts its corrected words. The reason B49
  gave is now met by one condition in `calibration/engine.py`: of the reports that agree,
  at least one must be about a take.
- **Why there:** B49's worry was about *what moves a setting*, and the engine is the one
  place that decides that. A refusal at the door was a blunt way of saying it. The engine
  rule is also visible: the waiting count and its sentence are on the calibration screen,
  so a user can see that their reports on a reference were counted and what is missing.
- **Why "at least one" and not "most":** a user with one monologue has one reference and
  many takes; reports about the reference's pauses are real evidence about what they call
  a pause. One take showing the same thing is enough to say it is not only the film's
  sound. The other conditions (three reports, two recordings, three in four agreeing) all
  still apply.
- **Decided against:** storing a flag on each report saying whether it may count (the rule
  would then be frozen into old rows); a separate calibration for references (the brief
  rules out settings per profile, and two recordings cut by different rules cannot be
  compared).

### B53. The AI model's pick is a job; the facts are not

- **Chosen:** the facts are worked out inside the request that asks for them. The pick is
  a third kind of job in the same queue.
- **Why:** the first costs a few thousandths of a second and must never be out of date.
  The second calls the AI model, and only the worker has an AI model (B18): the API does
  no slow work and never talks to Ollama. Going through the queue also means the pick
  waits its turn behind an analysis, so the speech model and the AI model are never asked
  to work at once.
- **Decided against:** *calling Ollama from the API "because it is only two seconds"*: it
  is two seconds when the model is loaded and thirty when it is not, and the rule that the
  API never waits on a model is worth more than one exception. *A new table of summary
  jobs:* every guarantee a job needs (one at a time, cancel, crash recovery) is already in
  `jobs`.

### B54. One stored pick, holding the notes themselves

- **Chosen:** `feedback_summary` has one row. A new pick replaces it. The row holds the
  picked notes' text, not their IDs.
- **Why one row:** a pick is a reading aid, not a record. Nothing depends on what the
  model picked last week, unlike a calibration version, which every result points back to.
- **Why the text:** a note can be edited or its feedback removed. Stored as text, the pick
  always shows what the model was actually looking at, and the fingerprint says when that
  is no longer the current set.
- **Decided against:** keeping every pick ever made; storing feedback IDs and looking the
  notes up again when shown.

### B55. Two helpers were added to the coaching checks and then taken out again

- **What happened:** the first design of this feature had the AI model restate the facts,
  and needed two extra functions in `coaching/grounding.py`. When that design was dropped
  (science decisions S69 and S70), nothing used them any more.
- **Chosen:** `grounding.py` was put back exactly as it was in Phase 6.
- **Why it is written down:** a later reader who thinks "the summary should check its
  figures like the coaching does" should know it was tried, and that the checks passing
  was not the problem.

### B56. `run.sh`: one script that starts, stops and reports on the three programs

- **Chosen:** a Bash script at the top of the project, with no dependencies beyond what the
  app already needs. `./run.sh` starts whatever is not running and stays attached,
  `./run.sh stop` stops all three however they were started, `./run.sh status` says what is
  running.
- **Why:** three terminals and three commands were the first thing to go wrong in use: a
  worker left running in another window, and no quick way to tell.

How it is built, and what each choice avoids:

| Choice | Why |
| --- | --- |
| A program is "ours" if the folder it was started in is inside this project (`lsof` gives the folder) | The ports 4321 and 1234 are ordinary numbers. Another project may be using them, and this script must never stop a program that is not this app. A port in use by anything else stops the start, with the program named and left alone |
| The database is brought up to date first (`uv run alembic upgrade head`) | Otherwise the API starts and reports a broken database after every update. The command changes nothing when there is nothing to do |
| Each program is started in a session of its own, through one line of the backend's own Python (`os.setsid()`, then `exec`) | `Ctrl+C` in a terminal goes to every program in the terminal's foreground group at once. The worker treats a second signal as "stop at once", so if the script also passed the signal on, the worker would never get to finish its step. In its own session, each program hears only from the script. macOS has no `setsid` command; the app's Python is always there |
| The programs are run from `backend/.venv/bin/python` and `frontend/node_modules/.bin/next`, not through `uv run` and `npm run` | One process per program. A wrapper in between either passes signals on (two signals for one) or does not (the program outlives its wrapper) |
| The process ID is written to a temporary file by the program's launcher | Bash's own record of "the last program started" names the wrong process when output is piped. The file is removed when the script ends |
| Waiting is done with `sleep … &` and `wait` | Bash puts off a signal until the command it is waiting for ends, and can drop a `Ctrl+C` altogether if that command ended normally. `wait` is the one way of waiting that a signal interrupts |
| On stop: one signal to all three; the API and the frontend are killed after 10 s if still there; the worker is waited for | The worker finishes the step it is on and puts its job back in the queue. A second `Ctrl+C` tells it again, which by its own rule stops it at once, and if it is still there 5 s later it is killed |
| If one program dies, the others are stopped and the script exits with an error | Half an app is worse than none: the screen would show a worker that is not running, or a frontend with no API |
| It installs nothing, and never starts Ollama | Installing downloads from the internet, and the app's rule is that only the two documented set-up steps do that. Whether Ollama is running is reported by the worker in its first lines |

- **Decided against:** *a Node or Python program to do the same* (one more thing to keep
  working, for what the shell does in 300 lines); *`concurrently` or another process
  manager* (a new dependency, and none of them knows the worker's two-signal rule); *a
  `Makefile`* (it can start three programs but not stop them in order); *running the three
  under `launchd`* (the app would then be running when the user is not using it).

What was checked on this machine is in the table at the end of section 10.

### B57. A monologue is a view of the analyses, not a table of its own

- **Chosen:** a monologue is a reference recording in all its revisions, named by that
  recording's `root_id`. `GET /api/monologues` works the list out from the `analyses`
  table each time. There is no `monologues` table.
- **Why:** everything a monologue has, the reference already had: a title, a recording, a
  language, revisions. A table would hold one row per reference and say nothing new, and
  it would be a second place for "does this monologue exist" to disagree with the first.
  It also means every reference added before Phase 8 is a monologue with no migration of
  data at all.
- **Decided against:** *a `monologues` table with the reference and the takes pointing at
  it*: the right shape if a monologue ever needs something of its own (a script typed by
  hand, notes, more than one original). Nothing asks for that yet.
- **When to revisit:** when a monologue needs a property that is not a property of its
  reference recording.

### B58. A take's monologue is a column, not part of the measured result

- **Chosen:** `analyses.monologue_id`. It is left out of the stored `result` document
  (`job_queue.STORED_APART`) and filled in when the result is read, as the list of
  revisions and the coaching are.
- **Why:** it is not a measurement, and unlike a measurement it can change: when a
  monologue's last reference is deleted its takes are freed (B61). The `result` is
  written once and never changed (B16), so anything that can change must live beside it.
  A column also lets the takes of a monologue be listed with an index, without opening
  any JSON.
- **Decided against:** storing it in both places. Two copies of one fact, one of which may
  not be updated, is how they come to disagree.

### B59. A take points at its monologue, not at one revision of the reference

- **Chosen:** `monologue_id` holds the reference's root ID. `POST /api/analyses` accepts
  the ID of any revision and stores the root.
- **Why:** correcting a misheard word in the original makes a new revision. Takes
  recorded before the correction are takes of the same monologue, and should be compared
  with the corrected words without anyone updating them.
- **Decided against:** *pointing at the revision that was newest at the time*. Every
  correction of the reference would leave the earlier takes behind, attached to a
  revision nobody looks at any more.
- **What is not recorded, as a result:** which revision of the reference a take was first
  compared with. Nothing needs it: a comparison is worked out on request (B34) and says
  which two results it used.

### B60. `monologue=none` asks for the takes of no monologue; leaving it out still means all

- **Chosen:** one query parameter on the list and on the clear: a monologue's ID, the
  word `none`, or nothing.
- **Why a word and not a second parameter:** the three cases exclude each other, so one
  parameter cannot be given a contradictory value.
- **Why "nothing" still means every take:** it is what the endpoint did before Phase 8,
  and every script and test written against it keeps working. The General Practice
  screen asks for `none` explicitly.
- **Decided against:** *making "no monologue" the default.* Quietly changing what an
  existing request returns is how an old script comes to delete or miss the wrong things.

### B61. Deleting a monologue deletes its takes; deleting only its reference frees them

- **Chosen:** two different acts. `DELETE /api/monologues/{id}` removes the reference in
  every revision and every take recorded for it. Deleting a reference through the older
  `DELETE /api/analyses/{id}` removes that one row, and when it was the last revision the
  takes lose their monologue and become ordinary takes.
- **Why delete the takes with the monologue:** they are shown only under it. Left behind
  they would turn up in the General Practice history, which is for something else. The
  screen says how many takes will go before it asks.
- **Why free them in the other case:** that endpoint deletes "one analysis", and has
  never deleted anything the caller did not name. The alternative to freeing is a take
  that points at nothing and is listed nowhere.
- **Why refuse while a job is in the queue:** the job would finish after the delete and
  store a take for a monologue that is gone. `409 monologue_busy` says so; the user waits
  or cancels.
- **Decided against:** *a database rule (`ON DELETE CASCADE`) from takes to their
  monologue*: a monologue is not a row (B57), so there is nothing for such a rule to hang
  on; and kept audio files have to be deleted by code in any case.

### B62. A take whose monologue went while it waited is stored as a take of none

- **Chosen:** when a job finishes, `complete_job` checks that the monologue still has a
  reference. If not, the result is stored with no monologue.
- **Why:** B61 refuses to delete a *monologue* while one of its jobs is waiting, but the
  older endpoint can still delete the *reference* under a waiting job. The recording has
  been measured by then, and half a minute of work should not be thrown away or hidden.
  Stored as a take of none, it is in the General Practice history.
- **Decided against:** failing the job (the measurements are fine); refusing to delete a
  reference that has a job waiting (a new refusal on an endpoint that never had one).

### B63. The voice goal is a column on the job, and is written into the result

- **Chosen:** `jobs.voice_goal` carries the goal from the request to the worker. The
  worker writes it into the result as `voiceRange.goal`. Nothing is added to `analyses`.
- **Why a column on the job:** the worker needs it before any result exists, and a job's
  row is the only thing that travels from the request to the worker (section 4).
- **Why inside the result, when the monologue is not (B58):** the monologue says where a
  take is *filed*, and can stop being true (its reference is deleted). The goal says how
  this result is to be *read*: the coaching is written from the stored result alone, also
  when it is written again weeks later, and a corrected or re-analysed revision must be
  read the same way. `revisions.voice_goal` reads it back from the result for both.
- **Decided against:** *a setting in the database, one goal for everything*: simpler, and
  an old result would then be coached against whatever the goal is today. A recording
  keeps the goal it was made with. *A column on `analyses` as well*: two copies that
  could disagree.

### B64. Where the voice sat is part of the result document; older results are left without it

- **Chosen:** `voiceRange` on the result and `voice` on each segment, inside the one JSON
  document (B15). No table, no column. A result stored before Phase 9 has neither, and
  is not touched.
- **Why:** it is a measurement, and measurements are stored once and never updated in
  place (B16). The schema makes both fields optional, so an old result still reads, which
  a test checks.
- **How an old recording gets one:** "Analyse again", if the recording was kept. That is
  a new revision by the pipeline as it now stands, like any other (science decision S63).
- **Decided against:** *working it out for old results in the migration*: the audio of
  most of them is gone, by design.

### B65. Resonance is one more replaceable piece of the pipeline, inside the existing stage

- **Chosen:** `PipelineDeps.measure_resonance`, called during `measuring_audio` beside
  loudness and pitch. No new stage in the job's progress.
- **Why:** it takes about a hundredth of the recording's length (85 times real time), so
  a stage of its own would flash past. Being a replaceable piece, like the detector and
  the recogniser, lets the tests script "this voice has a spacing of 990 Hz" and check
  the placement by hand; the real measurement has tests of its own on built vowels.
- **Decided against:** *measuring it only when a goal is set*: the user asked for the
  voice to be shown for every recording, and a result measured differently depending on
  a coaching choice would break "a goal changes no measurement".

### B66. A reference is measured the same way and never has a goal

- **Chosen:** `voiceGoal` sent with a reference is ignored and stored as `none`. Its
  voice range is measured and stored like a take's.
- **Why:** a goal is about the speaker's own voice. A reference is somebody else's
  performance, gets no coaching (B33), and has nothing to be coached towards. Showing
  where the original's voice sits is still useful beside a take.
- **Decided against:** refusing the request with an error: the screen sends one form
  for both, and an ignored field costs nothing.

### B67. A changed default raises the settings version, with no migration

- **Chosen:** `pitch_voiced_probability` went into `AnalysisSettings` at 0.3 and
  `version` went from 1 to 2. No stored result was touched.
- **Why:** every result carries a full copy of its settings (science section 12), so an
  old one still says how it was measured: no `pitch_voiced_probability` and version 1
  means the old 0.5. Reading stored settings already tolerates a missing field, which
  Phase 6 needed for the same reason.
- **Decided against:** *re-measuring pitch for kept recordings*: it would change figures
  the user has already read, behind their back (B16).

### B68. Stretches, and the pauses a segment holds, are part of the result document

- **Chosen:** `stretches`, `stretchIndex`, `insideSegment`, `pauseCount`, `pauseSeconds`
  and the two `deliveryWpm` fields live in the one JSON document of the result (B15). No
  table, no column, no migration.
- **Why:** they are measurements, stored once (B16), and nothing ever needs to search or
  join on them: a result is always read whole.
- **Pause numbering was kept:** pause *n* used to lie between segment *n* and segment
  *n + 1*. It now lies between *stretch* *n* and *n + 1*, and in an older result the two
  statements are the same. So `pause-3` means the same pause before and after, which
  matters because feedback is stored against pause IDs.

### B69. One file reads old and new results alike

- **Chosen:** `app/stretches.py` answers five questions about a stored result: its
  stretches, the stretch of a word, the pauses inside a segment, whether it has a
  delivery pace, and what that pace is. The comparison, the coaching, the WPM review, the
  transcript correction and the feedback rules all ask it, and none of them looks at
  `stretches is None` for itself.
- **Why:** an older result is not a damaged newer one. It is a result in which every
  pause ended a segment, and read that way everything about it is still true: one stretch
  per segment, and a pace per segment that *is* its delivery pace. Putting that reading
  in one place is what let Phase 10 go without a migration and without touching a stored
  row (B16, science decision S90).
- **Decided against:** *a migration that rewrites old results into the new shape*: it
  could add the stretches, but not regroup the segments without measuring again, so the
  result would look new and still be cut the old way. Better that it says what it is.

### B70. `segmentWpm` keeps its meaning; `deliveryWpm` is added beside it

- **Chosen:** `segmentWpm` is still words ÷ speaking time, as the brief defines it and as
  every stored result has it. The pace with pauses counted is a new field.
- **Why:** changing what an existing field means would make every older result silently
  wrong to a newer reader, and every newer result wrong to anything still reading the
  old way. A new name can simply be absent.
- **Cost:** the main figure on screen is not the field with the obvious name. The schema
  says so beside both.

### B71. Sound is measured over stretches, phrases over segments

- **Chosen:** the detector's output goes to loudness, pitch and resonance as stretches.
  A segment's loudness is the mean over its stretches (`EnergyTrack.mean_db_within`), not
  over its whole length.
- **Why:** a segment now contains silence. Averaging over it would make a line read
  quieter the more it paused, and would count pause time as speech when the voice is set
  against the background.
- **What did not change:** `PipelineDeps` still passes replaceable pieces; they are now
  handed stretches, which have the same `start` and `end` a segment had.

### B72. A corrected transcript puts each word back on its side of the pause

- **Chosen:** when the words of a segment that holds a pause are corrected, unchanged
  words keep their stretch, and new or changed words are placed by the rule the pipeline
  uses (`assign_words`): the stretch containing the middle of their time, or the nearest.
- **Why:** the corrected words arrive as one line of text, with nothing to say where the
  pause falls among them. Their times are already estimates (B45); the stretch follows
  from the time by the same code as everywhere else.
- **For an older result** the revision keeps the older shape, with no `deliveryWpm` and
  no stretches, so a revision never looks newer than the analysis it came from.

### B73. A report that a pause split a phrase is refused where it did not, and kept where it cannot count

- **Chosen:** `split_wrong` on a pause inside a segment answers `422 not_a_split`. On a
  pause that did end a segment it is stored with `no_vote: fixed_break` and the break it
  was made with, and counts towards nothing.
- **Why:** the first is a statement that is not true of that pause, and the screen does
  not offer it; the refusal is for anything else that sends it. The second is true and
  useful to keep, and the segment break is not adjustable (science decision S89).
- **In an older result** the same report still counts towards the minimum pause, as it
  did when it was made.

### B74. An export is written by the backend, as Markdown, on request

- **Chosen:** two `GET` endpoints that answer with a text document. Nothing is stored,
  queued or cached; the document is written from the stored results each time.
- **Why Markdown:** the user asked for "PDF or Markdown", to read the analyses and to hand
  them to someone else to study. Markdown is plain text: it can be read as it is, opened
  in any editor, searched, compared between two days, and its tables can be read by a
  program. It needs no new dependency. A browser or editor prints it to PDF if paper is
  wanted.
- **Why the backend:** the document has to say exactly what the results hold, including
  parts the screen never loads together (every take of every monologue, each with its
  comparison). The backend already has all of it and the code that reads old and new
  results alike (B69).
- **Decided against:** *a PDF library*: a large dependency to produce something harder to
  reuse. *A job in the queue*: writing every analysis of a real database took four
  hundredths of a second. *The raw stored JSON as the download*: complete, and unreadable
  by a person; it also leaves out the comparison, which is never stored (B34).

### B75. One recording, one entry: its newest revision

- **Chosen:** a document of several analyses gives each recording once, in its newest
  revision, and says which revision that is and out of how many.
- **Why:** revisions of one recording repeat almost everything, and a reader comparing
  takes wants each take once. The newest is the one with corrected words or the current
  settings.
- **A single analysis is the exception:** `GET /api/analyses/{id}/export` gives exactly
  the revision asked for, so an earlier one can still be downloaded from its own page.
- **A take is compared with the newest revision of its original**, as on screen (B59).

### B76. An original's export says how today's bands read it, and that is not stored

- **Chosen:** for a reference, the export runs the findings step of the coaching on it,
  with the default bands, and lists the findings under a heading that says what they are.
- **Why:** an original gets no coaching (B33), so nothing stored says whether its pace
  would be called "fast" or its pauses "short". That is exactly what is needed to judge
  the bands themselves: they are this app's rough choices, and the originals are real
  performances to hold them against. It is the purpose the export was asked for.
- **Why not stored:** it is a reading of the result with today's bands, not a measurement.
  Stored, it would go stale the day a band changes, and B33 would no longer be true.
- **What it is not:** coaching. No corrections, no drills, no AI model. It is the output
  of `build_findings` and nothing else.

### Decisions already made for later phases

None. Every phase in the plan is built, and so is everything Phase 6 had listed as left out.

## 10. Tests

Run with the command in the README. Current result: **847 pass**, 1 skipped (the opt-in
real-speech test, which also passes when run). 21 of them are new in Phase 11
(`test_export.py`); 65 were new in Phase 10.

Most of the older tests build their recordings with `make_body` and `make_recording`,
which make a result of the shape stored before Phase 10. They were left that way on
purpose: all of them still pass, which is the evidence that an older result reads as it
did. The Phase 10 tests build theirs with `measured`, which runs the real pipeline on
scripted speech and so makes a result of today's shape.

| Test file | Tests | What it proves |
| --- | --- | --- |
| `test_segmentation.py` | 34 | Segments and pauses from speech regions; threshold edges; long silences; word assignment. Short silences: every gap is either a pause or a short silence, never both; what counts follows the minimum pause in force; settings stored with an older result can still be read. Since Phase 10: a pause shorter than the segment break stays inside its segment and is still a pause; one of exactly the break ends it and a millisecond less does not; a segment's speaking time apart from its pauses; every pause knows the segments either side; with the break at the minimum pause the cut is the old one; words either side of a pause inside a segment go to their own stretch; a result from before the break is read as ending a segment at every pause |
| `test_metrics.py` | 30 | WPM with pauses excluded and included; reliability flags; typical pace and faster/slower; pause statistics; no division by zero. Since Phase 10: a segment with a pause inside has a delivery pace and a speaking speed, and one without has one pace; the recording's delivery pace counts pauses inside segments and not those between; whether a segment is long enough is judged on its speaking time; the review flag is judged on speaking speed; typical pace and variation are taken from delivery pace |
| `test_segment_pauses.py` | 37 | One recording with a pause inside a line and one between two lines, built by the real pipeline, followed through everything that reads a result. What is stored: both pauses, both paces, the stretches, each word's stretch, loudness taken from the speech and not the pause. **An older result reads as one stretch per segment**, and correcting it leaves it in the older shape. A corrected line keeps its pause, has both paces worked out again, and its words stay on their side of the pause. The WPM review lays out the delivery pace and the pauses it counts. The comparison: a recording against itself matches every pause, inside a line or not; a pause left out or added inside a line is reported where it fell; a line's pace is its delivery pace in both; a pause of the take long enough to end a line is not also counted as slowness; an older take against a newer original says the phrases are not like for like. The coaching: pace judged on delivery pace, **a fast delivery slowed with short pauses and not with slower words**, an older result keeping the advice that fits it, a phrase slow because of its pauses run through, and the model shown the pauses inside a phrase under its line. Feedback: a pause inside a phrase cannot be reported as having split it; one that ended a phrase can, and moves nothing. Through the API: the new fields, and an older result served without them |
| `test_export.py` | 21 | A missing figure is a dash, never a zero; text cannot break a table; a title becomes a plain file name. One analysis written out in full: its settings and measurements by name, **a phrase with both paces and its pause marked where it fell**, an older result with the one pace it has, the coaching with its findings and bands, the feedback given, beside the pause it is about. The download is a Markdown file with a plain name; an unknown analysis is refused; **exporting changes nothing stored**. An original is given with how the bands read it and no coaching; a take of a monologue with its comparison; a take of none without one. A monologue's export holds its original and only its own takes; the General Practice export only takes of no monologue; everything is given monologues first; **a recording appears once, in its newest revision**; an unknown monologue or scope is refused; with nothing stored it says so |
| `test_audio_and_acoustics.py` | 20 | Decoding, length limit, clipping, loudness in dB, pitch, emphasis candidates, hesitation sounds |
| `test_pipeline.py` | 33 | The whole pipeline with scripted speech: numbers, warnings, no-speech, garbled transcripts, cancellation. Since Phase 9: pitch and resonance each placed in a range with a position; every phrase placed and counted; the ranges stored with the result; **the goal recorded and no measurement changed by it**; resonance that could not be measured is unavailable and pitch still decides; a phrase with neither measured counted as unmeasured; no voice range without speech; a loud background makes resonance an estimate and a very loud one withholds it |
| `test_voice_range.py` | 30 | The ranges as stated, low to high; a pitch and a resonance placed by position, at the far ends, at the edges of the neutral range and in its middle; beyond a far end stays at 100%; ranges that overlap or run backwards are refused; every combination of pitch and resonance gives the right marker, including "mixed" and one of the two missing |
| `test_resonance.py` | 7 | The spacing of an even ladder is its step, and the higher formants weigh more. **Vowels built with known formants are found**: 1,000 and 1,200 Hz within 20; the note the voice speaks on does not move its resonance; nor does a much quieter copy; only speech is measured; too little sound is unavailable, not a number |
| `test_coaching_voice.py` | 26 | With no goal the voice is described and nothing is judged; each range named with its edges; only what was measured is stated; an estimate says why. With a goal: a voice that stayed in range is a strength; phrases that left it are named furthest first; the same voice reads the other way round for the other goal; a whole voice outside the range outweighs a few stray phrases; a summary line and a word of caution are added. The correction points the right way and is practised on the furthest phrase. **The model is not shown how a range is typically heard; a remark about the speaker is sent back once, then left out; with nothing left the fixed rules write the coaching**; the same words pass when no goal was chosen and inside a quoted line; an internal phrase label is rewritten |
| `test_voice_api.py` | 8 | The form is offered the three goals; no goal unless one is chosen; an unknown goal is refused; the result says where the voice sat and keeps the goal; the same recording with no goal is measured the same and not judged; a reference is measured and never has a goal; analysing again and correcting the words keep the goal; a result stored before Phase 9 still reads |
| `test_job_queue.py` | 25 | Every status change: claim order, duplicates, cancel, fail, retry, expiry, crash recovery, liveness |
| `test_worker.py` | 31 | Real jobs end to end: success, clean-up, failure messages, cancel mid-job, graceful stop, recovery. Coaching as the last stage; an unavailable model or a crash in coaching never failing the analysis; coaching jobs succeeding, failing, being cancelled, handed back and recovered. A reference measured like a take with no coaching stage and no call to the AI model; the waveform stored beside the measurements, and the measurements identical with and without it |
| `test_api.py` | 35 | Submitting, polling, cancel, retry, every refusal, the full upload → poll → result journey. Coaching in the result; writing it again; asking twice; the old coaching surviving a failure; health reporting the AI model |
| `test_history_api.py` | 22 | Form options, the history list and paging, kept-audio playback and deletion, deleting one analysis, clearing history without touching work in progress. References: submitted with a title, listed and cleared separately from takes. The waveform served only on request. The comparison endpoint and every refusal |
| `test_comparison.py` | 26 | Pauses matched, missing, extra and unplaced; a recording against a copy of itself showing no difference even with word times pushed into the pauses; phrase pace over the same words; whole-recording rows; the biggest differences in order and in words; different passages compared only as wholes; neither recording changed |
| `test_comparison_align.py` | 20 | Word keys, including Hindi spelling variants; dropped, added and misheard words; a repeated line matched to the right repetition; speed on a ten-minute passage |
| `test_waveform.py` | 6 | The outline's lowest and highest values, its size for long and short recordings, padding, no normalising |
| `test_migrations.py` | 2 | The migrations build exactly the tables the code expects, `feedback_summary` among them; a database from before Phase 4 upgrades with its rows intact, each result becoming calibration version 1, the first result of its own recording, and a take of no monologue; a job queued before Phase 9 has the voice goal `none` |
| `test_monologues.py` | 19 | A reference is a monologue and a take is not; **a take recorded for a monologue is listed under it and not in the General Practice history**; the monologue is kept in its column and not inside the measured result; an unknown monologue is refused and nothing is stored; a corrected reference is still the same monologue, now compared with by its new revision; a corrected or re-analysed take stays with its monologue and counts as one take; the one practised most recently comes first. Clearing the General Practice history leaves every monologue's take, and one monologue's takes can be cleared alone. **Deleting a monologue removes its references, its takes, their recordings, jobs and feedback, and nothing of any other**; it is refused while a take of it is waiting; a failed take holding its recording goes with it. Takes are freed when the last revision of their reference is deleted, and when the references are cleared; a take whose monologue went while it waited is stored as a take of none |
| `test_calibration_engine.py` | 37 | The adjustment rules with no database: one or two reports move nothing; three from one recording are not enough; disagreement and ties change nothing; only recent reports count; the minimum pause is steered by the silences reported and never moves more than 100 ms at once; **no setting ever leaves its allowed range**; a report already answered by an earlier change stops counting; moving back needs five reports; the detection threshold is not adjustable. **Reports on references alone move nothing, however many**; one agreeing report on a take lets them count; a take report pointing the other way does not stand in for one |
| `test_feedback.py` | 26 | What each kind of feedback is taken to mean: labels speak for no setting; a short false pause for raising the minimum pause; a long one for nothing; a missed pause for lowering it only where a silence of 250 ms or more was heard; one silence can be reported only once; **no feedback speaks for more than one setting** |
| `test_feedback_api.py` | 34 | Through the API: storing, replacing, noting and removing feedback; a fresh install says it is still calibrating; two reports change nothing; **three agreeing reports from two recordings move only the minimum pause**, with a reason and a confidence; each adjustment needs fresh reports; **undo, reset and switching off**; new analyses use the new value and old ones stay as they were; **labelling a pause changes no measurement**, and reaches the coaching when it is written again; saying a WPM looks wrong changes no number. On a reference: a mistake can be reported; labels and ratings are refused; four reports on two references move nothing and the screen says what is missing; one report on a take then moves the setting; the WPM review does not speak of what "you" said |
| `test_feedback_summary.py` | 40 | The facts: every sentence for a known set of feedback, word for word; each label in a fact of its own; ratings and what they were about in one fact; a moved setting stated with its default; only the latest 15 notes listed but all counted. The pick: **the model is shown the notes and nothing else**; a note that says nothing is never offered; an untidy answer is used as far as it goes; fewer than two notes named is no pick; every way the model can be unavailable. Through the API and the worker: the picked notes stored word for word, **no setting, version or report count changed**; out of date when a note changes and not when only a count does; a new pick replaces the old; failure, cancellation before and during, and recovery after a crash |
| `test_transcript_correction.py` | 20 | **Segment WPM is the corrected word count over the phrase's own length, with no correction factor**; totals recounted; untouched phrases keep every figure; everything measured from the sound identical; corrected words get times between their neighbours; hesitation sounds recounted; emphasis candidates kept only for words still there |
| `test_revisions.py` | 17 | A reference's words can be corrected too: still a reference, still without coaching, both revisions in the library, a take comparable with either. A corrected transcript becomes revision 2 and the corrected result stays exactly as it was; both are in the history; pause labels come along and reports do not; the kept recording is shared and each copy can be deleted alone. Analysing again: a new revision with the settings in force, for takes and references; asking twice; refused without a kept recording; a cancelled one leaves the kept recording alone |
| `test_wpm_review.py` | 13 | The review of a reference is worded for someone else speaking, and points at the same things. The arithmetic shown; too high points at extra words and speech lost in a pause, too low at dropped words and silences counted as speaking; word timing is always part of it; reviewing changes nothing |
| `test_coaching_findings.py` | 45 | Every finding: its band, its wording, its role under each profile; what is left out when a measurement is missing; that statements contain no figure that is not a measurement or a band. Pause labels: an accidental pause is not praised as a held silence, an intentional one is never an issue, labels never change a measurement. Priorities move an issue down the list without removing it |
| `test_coaching_rules.py` | 92 | Template coaching: order, practice phrase, profile sentence, targets; every template under every profile fills in completely and quotes only known figures. 16 more since Phase 9: the four voice templates under each of the four profiles. 12 more since Phase 10: the three pause-based templates |
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
| A fresh database | Calibration version 1, "still calibrating", 13 adjustable settings (15 since Phase 9) |
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


Also checked at the end of Phase 7, the same way: the real API, worker, speech model and
`llama3.1:8b`, in a complete copy of the project in a temporary folder with its own
database, on other ports, so that neither the real database nor the programs the user had
running were touched. All 41 checks in the script passed.

| Check | Result |
| --- | --- |
| A fresh database | Version 1; the rules say one report must be about a take; no facts, no notes, and the AI model is not asked (`409 too_few_notes`) |
| Analyse a take and two references | 36 s (first run, models loading), 6 s and 6 s. Neither reference has coaching |
| For each silence the detector heard, report the gap after the word before it (the rule the screen uses when a word is picked) | 6 of 6 came back as being about that silence, including one of 132 ms. The gap chosen was 0.03 to 0.12 s from the start of the silence |
| Report a gap with no silence near it | Saved; counts towards nothing; "the detector heard speech straight through" |
| Label a reference's pause, or rate a correction on it | Refused, `409 not_for_reference`, three times out of three |
| Four missed-pause reports on two references | Nothing moves: "4 of the 3 reports needed for lowering it. All of them are about reference recordings…". The references' stored results are byte for byte the same |
| One more, on a take | Minimum pause 500 → 400 ms: "after 5 reports of a pause that was missed, from 3 recordings. The silences reported were around 356 ms long." |
| Say a reference's WPM looks too high | Review: "3 words ÷ 0.83 s of speaking × 60 = 217.4 WPM", worded without "you" |
| Correct two words of a reference | Revision 2: still a reference, same title, no coaching; 16 words over the phrase's own 4.51 s = 212.9 WPM; pauses identical; the reference it came from unchanged |
| Compare the take with each revision | 47 of 47 words lined up with the first; 45 of 47 with the corrected one, exactly the two words changed |
| Give ten more pieces of feedback, nine with notes | The facts count all of them: 5 missed pauses with silences "between 324 and 356 ms", each label in its own line, the moved setting with its default |
| Ask the AI model with 3 notes worth offering | Refused, `409 too_few_notes` |
| Ask it five times with 8 worth offering | Five picks in 2 to 6 s each. Every picked note is one of the notes, word for word; none picked twice; the note that says "ok" never picked; each pick includes a note from the largest group |
| After the five picks | The calibration is identical: no setting, version or report count changed |
| More feedback without a note, then with one | The facts update at once and the pick stays current; with the new note it is marked out of date and still shows what was picked |

`run.sh`, checked in that same copy:

| Check | Result |
| --- | --- |
| `./run.sh` with ports 4321 and 1234 in use by the user's own running app | Refused, naming the program on the port; nothing started; the user's programs untouched |
| `./run.sh` on a database that did not exist yet | Five migrations applied, three programs started, "Monologue Coach is running" after about 10 s |
| `./run.sh` again while it is running | "Everything is already running", with the three process IDs; exits |
| `./run.sh stop` for programs the script had lost track of | All three stopped in 3.5 s |
| `Ctrl+C` with nothing in progress | All three stopped; no process and no temporary folder left behind |
| `Ctrl+C` while the worker was transcribing | Stopped in 3.3 s. The worker logged "returned to the queue (worker stopping)"; the job was `queued` with attempt 0 |
| Start again | The job was picked up without being submitted again and succeeded in 19 s |
| The interrupt signal sent to the script alone, not through a terminal | Stopped within 4 s |
| The API killed on its own | "One of the programs has stopped"; the other two stopped within 2 s |
| The worker frozen so that it cannot answer, then `Ctrl+C` twice | After 10 s: "The worker is finishing the step it is on. Press Ctrl+C again…". Five seconds after the second, it was stopped outright |

Two faults were found and fixed while testing the script. The first version asked Bash for
the ID of the program it had just started and was given the ID of the pipe beside it, so
it believed all three had died and exited while they were still running. And a test that
sent the interrupt to "the script" was sending it to one of the script's own helpers,
which ignores it on purpose; that was the test's mistake, but it led to the change from
`sleep` to `wait`.

Not checked in Phase 7: a real human voice, a real film clip as the reference, and notes
written over weeks of use. `run.sh` was run on macOS only, and from a background shell,
not typed into a terminal window by hand: its `Ctrl+C` tests sent the same signal a
terminal sends, to the same group of processes a terminal would send it to.


Also checked at the end of Phase 8, the same way as Phase 7: the real API, worker and
speech model, in a complete copy of the project in a temporary folder with its own
database, on other ports. The recordings were synthesised with pauses of known length. All
16 checks in the script passed, and the copy was left with nothing in it.

| Check | Result |
| --- | --- |
| The new migration, on a copy of the project's own database, then on the database itself | `5c2a9e7b1d43 -> 7d4b2c9a6e15`; the API, which was running, answered `"database":"ok"` before and after |
| Add a reference with a title | 23 s (first run, the speech model loading). `GET /api/monologues`: one monologue, its ID and its `referenceId` both the new analysis, `takeCount` 0 |
| Submit **the same file** as a take of it | The job and the result both carry `monologueId`. Compared with the reference: 31 of 31 words lined up, 3 of 3 pauses in both with a difference of zero, **no differences listed**. This is the check with a known answer: a recording against itself |
| Submit a different take of it (other pauses, faster) | Lined up fully; four differences, among them "The reference pauses for 2.3 seconds after “…and you think that of me”. You did not pause there." and "17% faster" |
| Submit the same file with no monologue | `monologueId` is `null` |
| The three lists | `?monologue=<id>`: the two takes, newest first. `?monologue=none`: the one free take. The monologue's `takeCount`: 2 |
| Correct one word of the reference | Revision 2. Still one monologue, same `monologueId`, `referenceId` now the revision, `revisionCount` 2, `takeCount` still 2; its takes listed under either revision's ID |
| Compare the self-take with the corrected reference | 30 of 31 words lined up: exactly the one word changed |
| `DELETE /api/analyses?monologue=none` | `{"deletedAnalyses": 2, "deletedJobs": 2}`; the monologue's takes untouched |
| `DELETE /api/monologues/<id>` | `{"deletedReferences": 2, "deletedTakes": 3}`; no monologue, take or reference left; `data/audio/` and `data/uploads/` empty; no row left in `analyses`, `jobs` or `feedback` |

Not checked in Phase 8: a real human voice or a film clip as the original, as in every
phase; a monologue with more takes than the 50 the screen lists; and the user's own
worker, which was started before this phase and has to be restarted to run the new code
(until then it stores a take without its monologue).

Also checked at the end of Phase 9, the same way: the real API, worker, speech model and
AI model, in a complete copy of the project in a temporary folder with its own database,
on other ports. The recordings were synthesised: a deeper voice, a higher voice, one
recording with the deeper voice followed by the higher, and the deeper voice with hiss
added at two levels. All 22 checks in the script passed. The measured figures are in the
science document ("How Phase 9 has been tested"); what concerns the backend:

| Check | Result |
| --- | --- |
| The new migration, on the copy and then on the project's own database | `7d4b2c9a6e15 -> 2f8c5a1e9b36`; existing jobs have `voice_goal` `none` |
| `GET /api/analysis-options` | The three goals and the note |
| A take submitted with `voiceGoal=higher` | The job's status carries `voiceGoal`; the result carries `voiceRange.goal`, the placements, the marker, the phrase counts and a copy of the ranges |
| The same file with no goal, and with `lower` | Every measured figure identical across the three; only the coaching differs |
| A recording of two phrases in two voices | Each segment carries its own `voice`; `phrases` counts one lower and one higher |
| A take with hiss, 24 dB between voice and background as the app reads it | Warning `resonance_noisy`; resonance `estimated`; `resonanceNote` says why |
| The same with 14 dB | `resonance` is `null`, `resonanceNote` says the background is too loud, pitch is still there and decides the marker |
| A reference submitted with `voiceGoal=lower` | Stored with `none`; measured like a take; no coaching |
| Coaching written by the real AI model with a goal | 30 to 33 s; `source` `ai`, no notice; no word about the speaker in its wording |

Three of those checks failed the first time and changed the code: the pitch of the deeper
voice was "unavailable" (the voicing threshold, B67), the model's wording spoke about the
speaker (the science document, decision S81), and the 14 dB recording returned a resonance
in the wrong range (the noise limits, S82).

Not checked in Phase 9: a real human voice, as in every phase, which matters more here
than anywhere, because the resonance ranges were set from synthesised voices; a recording
near the 10-minute limit (resonance was timed on short clips only, at about 85 times real
time); and the user's own worker, which has to be restarted to run the new code. Until it
is, a recording is analysed by the worker as it was started: with no voice range in the
result, and the goal ignored.

Also checked at the end of Phase 10, the same way: the real API, worker, speech model and
AI model, in a complete copy of the project in a temporary folder, on other ports. This
time the copy's database was a copy of the project's own, with its two kept recordings,
so that real recordings could be analysed again without touching the originals. All 42
checks passed, in two passes; the first was run by the user from their own terminal. The
measured figures are in the science document ("How Phase 10 has been tested"); what
concerns the backend:

| Check | Result |
| --- | --- |
| A recording with four known silences, uploaded | The result carries `stretches` (5), `segments` (3), `insideSegment` true, true, false, false on its pauses, `stretchIndex` on every word, and `settings.segment_break_ms` 1000 with `settings.version` 3 |
| `POST …/feedback` with `split_wrong` on a pause inside a phrase | `422 not_a_split`, nothing stored |
| The same on a pause that ended a phrase | `200`; the item's message says the break is fixed and no setting changes |
| `POST …/feedback` with `wpm_too_low` on a phrase | The item's `review.formula` reads "24 words ÷ 8.19 s × 60 = 175.9 WPM. The 8.19 s include 2 pauses, 1.35 s in all, inside the phrase. With those left out, the speaking speed is 210.6 WPM." |
| `POST …/transcript` adding one word to that phrase | `201`, revision 2: both paces worked out again, `pauses` and `stretches` equal to the first revision's |
| `POST …/reanalysis` on each of the two real recordings | 11 and 17 s. A new revision cut the new way; the stored result it started from is unchanged, byte for byte in its segments |
| `GET …/comparison/…` between a result made before Phase 10 and one made after | `settingsNote` says, in words, that one ended a phrase at every pause and the other only at a pause of 1 second or more |
| The same file as a reference and as a take of it | `metrics` has a `deliveryWpm` row with the same value on both sides; `differences` is empty; `settingsNote` is `null` |
| `GET /api/analyses` | Each row's `metrics` has `deliveryWpm` when the result has one, and leaves it out when it does not |

One fault was found by the automated tests before this and fixed: a result saved again
after Phase 10 (a corrected transcript of an older result) stores `"deliveryWpm": null`,
and the history list tried to read that as a metric and failed. The list now leaves out a
metric that is empty as well as one that is missing.

Not checked in Phase 10: a real recording made by the user after the change; a recording
near the 10-minute limit; and the user's own worker and API, which were not running at
the end of the phase. The worker loads its code once, so it must be started again before
a new recording is cut the new way.

Also checked at the end of Phase 11: the export was run against a copy of the project's
own database (two monologue originals and one General Practice take, real recordings) and
the document was read. 41,555 characters, written in 0.04 s. It held, for each recording,
every part listed in section 3; the take's coaching with its eleven findings and the
bands of the day it was written; its five pieces of feedback; and for each original the
findings today's bands give it. Reading it showed nothing wrong with the export, and one
thing about the data worth knowing when the bands are studied: both originals are film
clips with other sound in them. Both carry the warning that word timings did not line up
with the detected speech, one is also marked noisy, and neither has a resonance figure:
the background was too loud for one to be given.

Not checked in Phase 11: the download links in a browser (they are plain links to these
endpoints; the endpoints are tested through the same HTTP layer a browser uses); a
monologue with takes in the real database, because none had been recorded for either
monologue yet (the comparison part of the export is covered by tests on scripted
recordings); and a database with hundreds of analyses.
