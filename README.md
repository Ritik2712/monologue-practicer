# Monologue Coach

A local speaking-practice coach for Hindi and English monologues. Everything runs on this
device: no paid APIs, no cloud services, no accounts.

> Status: **Daily Speaking Practice**, **Monologue** (compare your take with the original
> recording) and **General Practice** (record or upload your voice, see it measured, and get
> coaching for the next take) are built. Feedback and calibration are not built yet. Features
> are added phase by phase.

How the project works, file by file, and why each design decision was made:

- [DOCUMENTATION.md](DOCUMENTATION.md) — start here
- [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md) — pages, the checklist, the timer
- [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md) — API, database, job queue and worker
- [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md) — how the audio is measured, how the coaching is produced and checked, and how two recordings are compared

## What you can do today

- **Daily Speaking Practice** at `/practice`: a timed five-step, 15-minute routine with a
  checklist and a history of recent days. It runs entirely in the browser and works even when
  the API is not running. Progress is saved in this browser's `localStorage`, so it stays on
  this device, is separate for each browser, and is removed if you clear the browser's site
  data.
- **Monologue** at `/monologue`: add the original recording once (a file you have the right
  to use) and study its pauses, pace, loudness and pitch. Then record or upload your own
  take and see where the two differ: the biggest differences first, then pause by pause and
  phrase by phrase, each with both versions to listen to. An optional picture draws the two
  sound waves on one timeline. The comparison works by lining up the recognised words, so
  both recordings need to be of the same text.
- **General Practice** at `/general`: choose a delivery profile, record in the browser or
  upload a file, and get speaking rate (with pauses excluded), every pause, loudness and
  pitch, phrase by phrase, with a timeline you can click to listen. Past analyses are kept
  in a history and can be compared, reopened and deleted. It needs the API and the worker
  running; the screen tells you if either is missing.
- **Coaching** with every analysis: up to three corrections, most important first, each
  with what was measured, why it matters, a drill, and the phrase to practise on with a Play
  button; then what is already working, targets for the next take, and what is uncertain.
  The wording comes from an AI model running on this computer through
  [Ollama](https://ollama.com), and every figure in it is checked against the measurements.
  If Ollama is not running, the analysis still works and the coaching is written from fixed
  rules instead; you can ask the model again later without re-recording.
- **Comparison with a reference** is also inside General Practice, as a section of every
  result.

## Stack

- **Frontend:** Next.js (React, TypeScript, Tailwind CSS) in `frontend/`
- **Backend:** FastAPI (Python 3.12, managed with [uv](https://docs.astral.sh/uv/)) in `backend/`
- **Worker:** a second Python process in `backend/` that runs the analysis jobs
- **Database:** SQLite, one local file at `backend/data/monologue_coach.db`, schema managed
  with Alembic migrations
- **Speech recognition:** faster-whisper, model `small`, running on the CPU
- **Speech detection and measurements:** Silero VAD, NumPy, librosa
- **Coaching:** the `llama3.1:8b` model in Ollama, called directly over HTTP on this
  computer. Optional: without it, coaching is written from fixed rules

## Prerequisites

- Node.js 20.9 or newer and npm
- uv (it downloads Python 3.12 for the backend on first use)
- About 1.5 GB of free disk space: roughly 0.5 GB each for the frontend packages, the Python
  packages and the speech model
- An internet connection for the setup steps below. After setup, analysing a recording makes
  no network requests beyond this computer.
- Optional, for AI coaching: [Ollama](https://ollama.com) with the `llama3.1:8b` model
  (4.9 GB on disk; it used 5.8 GB of memory while loaded here). Everything else works
  without it.

No separate ffmpeg install is needed; audio decoding is built into the Python packages.

## Setup

Frontend packages:

```bash
cd frontend && npm install
```

Backend packages and database tables:

```bash
cd backend && uv sync && uv run alembic upgrade head
```

The speech model, once (about 480 MB, saved under `~/.cache/huggingface`):

```bash
cd backend && uv run python -m app.speech_model download
```

**Updating from an earlier phase?** Run the database step again, so the tables get their new
columns. Existing analyses are kept (and become "takes"):

```bash
cd backend && uv run alembic upgrade head
```

### AI coaching (optional)

The app uses the Ollama model you already have. It **never downloads a model itself**. Check
what is installed:

```bash
ollama list
```

If `llama3.1:8b` is in that list, there is nothing to do. If it is not and you want AI
coaching, install it yourself (a 4.9 GB download):

```bash
ollama pull llama3.1:8b
```

To use a different model that you already have, set `OLLAMA_MODEL` in `.env` to its name as
shown by `ollama list`.

## Run

Three programs, each in its own terminal. The checklist needs only the frontend; audio
analysis needs all three. For AI coaching, Ollama must also be running: open the Ollama app,
or run `ollama serve` in a fourth terminal. The worker says at start-up whether it found it.

API, on http://localhost:8000:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 8000
```

Worker (runs the analysis jobs, one at a time):

```bash
cd backend && uv run python -m app.worker
```

Frontend, on http://localhost:3210:

```bash
cd frontend && npm run dev
```

Then open http://localhost:3210 in a browser. The port is fixed on purpose: the browser
keeps the checklist's saved data per address, so a changing port would hide it. To use
another port, run `PORT=4000 npm run dev`.

Stop any of them with `Ctrl+C`. The worker finishes its current step, puts an unfinished
job back in the queue and exits; press `Ctrl+C` a second time to stop it immediately.

## Health check and troubleshooting

```bash
curl http://localhost:8000/api/health
```

A fully working setup answers
`{"status":"ok","database":"ok","worker":"running","speechModel":"ready","coach":"ready","coachModel":"llama3.1:8b"}`.

| You see | Meaning | Fix |
| --- | --- | --- |
| No answer at all | The API is not running | Start the API |
| `"database":"error"` | The database file cannot be used, has no tables, or is from an earlier phase | `cd backend && uv run alembic upgrade head` |
| `"worker":"not_running"` | No worker has reported in the last 15 seconds; uploads will wait in the queue | Start the worker |
| `"speechModel":"missing"` | The model is not downloaded; jobs will fail with instructions | `cd backend && uv run python -m app.speech_model download` |
| `"speechModel":"unknown"` | No worker has ever started, so nothing has checked | Start the worker |
| Worker says "Another worker is already running" | Only one worker may run at a time | Use the one already running, or stop it first |
| A job stays `queued` | The worker is not running, or is busy with an earlier job | Check `workerAlive` and `queuePosition` in the job status |
| A job stays `running` with `"workerAlive":false` | The worker stopped mid-job | Start the worker; it puts the job back in the queue |
| "Microphone access was blocked" on the General Practice screen | The browser was not given permission | Allow the microphone for the site (the icon in the address bar), then press Try again. Uploading a file works without it |
| `"coach":"not_running"` | Ollama is not running. Analyses still work; coaching is written from fixed rules | Open the Ollama app, or run `ollama serve` |
| `"coach":"model_missing"` | Ollama is running but does not have the model | `ollama pull llama3.1:8b`, or set `OLLAMA_MODEL` to one you have |
| `"coach":"not_local"` | `OLLAMA_BASE_URL` points at another computer, which is refused | Set it to `http://localhost:11434` |
| `"coach":"off"` | AI coaching is switched off | Set `AI_COACHING=on` in `.env` and restart the worker |
| Coaching says "Written from fixed rules, not by the AI model" | The model could not be used when that recording was analysed; the reason is shown with it | Fix the reason, then press "Ask the AI model for coaching" on that result. No need to record again |
| "Writing the coaching" takes over a minute | The first answer after Ollama has been idle includes loading the model; long recordings have more to read | Wait; the limit is `OLLAMA_TIMEOUT_SECONDS` (180) |
| The comparison says the two "do not appear to be the same passage" | Fewer than 30% of the reference's words were found in your take, in order. Different text, a different language, or a poor transcript of either | Check both transcripts (under each result). Compare takes only with a reference of the same text |
| A pause is listed as "Not found in your take" | The words around it could not be matched, so the spot could not be located. It is not counted as missing | Usually a misheard stretch; a cleaner recording helps |
| "No waveform is stored for…" | That recording was analysed before waveforms were added | Analyse it again |
| **Reference** or **Yours** cannot be pressed | That recording was not kept and is not in this page's memory | Tick "Keep this recording" when adding it |
| Styles look wrong in `npm run dev` after running `npm run build` | The development server can keep an old stylesheet | Restart `npm run dev` |
| The result warns that the transcript looks garbled | The speech recogniser got stuck on a hard stretch, usually poor audio | Analyse again, or use a cleaner recording. Pause, loudness and pitch figures are not affected |

Is the speech model installed?

```bash
cd backend && uv run python -m app.speech_model status
```

For more detail in the worker's output, including error tracebacks, set `LOG_LEVEL=DEBUG`
in `.env`.

## Try the analysis from a terminal

The General Practice screen does all of this for you. The same steps by hand, with the API
and the worker running: send a recording. This prints a job with a `jobId`:

```bash
curl -s -X POST http://localhost:8000/api/analyses -F "audio=@/path/to/recording.m4a" -F "language=auto"
```

Ask how the job is doing (replace `JOB_ID`). Repeat until `status` is `succeeded`:

```bash
curl -s http://localhost:8000/api/jobs/JOB_ID
```

Fetch the result, using the `analysisId` from the finished job. The coaching is under
`coaching`:

```bash
curl -s http://localhost:8000/api/analyses/ANALYSIS_ID
```

Have the coaching written again by the AI model. This prints a new job to follow the same
way:

```bash
curl -s -X POST http://localhost:8000/api/analyses/ANALYSIS_ID/coaching
```

Add a reference recording. It is followed like any job; it gets no coaching:

```bash
curl -s -X POST http://localhost:8000/api/analyses -F "audio=@/path/to/original.m4a" -F "role=reference" -F "title=The original" -F "retainAudio=true"
```

List the reference recordings:

```bash
curl -s "http://localhost:8000/api/analyses?role=reference"
```

Compare a take with a reference:

```bash
curl -s http://localhost:8000/api/analyses/ANALYSIS_ID/comparison/REFERENCE_ID
```

Accepted files: WAV, MP3, M4A, AAC, MP4, OGG, Opus, WebM, FLAC and AIFF, up to 50 MB and
10 minutes. `language` can be `auto`, `en`, `hi` or `hinglish`. All endpoints are listed,
and can be tried in the browser, at http://localhost:8000/docs.

On an Apple M2, measuring a 2-minute recording takes roughly half a minute. The first job
after starting the worker takes a few seconds longer while the speech model loads. The AI
coaching then adds 20 to 50 seconds, whatever the recording's length.

## Configuration

All settings are optional. Copy `.env.example` to `.env` in the repository root to override
backend defaults, then restart the API and the worker.

| Variable | Default | Used by |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///<repo>/backend/data/monologue_coach.db` | API, worker |
| `DATA_DIR` | `<repo>/backend/data` | API, worker (uploaded and kept audio) |
| `FRONTEND_ORIGINS` | none (any `localhost` / `127.0.0.1` port is always allowed) | API (CORS, extra origins) |
| `MAX_UPLOAD_MB` | `50` | API |
| `MAX_AUDIO_MINUTES` | `10` | API, worker |
| `WHISPER_MODEL` | `small` | worker, model download |
| `WHISPER_COMPUTE_TYPE` | `int8` | worker |
| `FAILED_AUDIO_RETENTION_HOURS` | `24` | worker |
| `MAX_JOB_ATTEMPTS` | `2` | worker |
| `WORKER_POLL_SECONDS` | `1` | worker |
| `LOG_LEVEL` | `INFO` | worker |
| `AI_COACHING` | `on` | worker (`off`: never call the AI model) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | worker (must be on this computer) |
| `OLLAMA_MODEL` | `llama3.1:8b` | worker (must already be installed in Ollama) |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | worker |
| `OLLAMA_CONTEXT_TOKENS` | `8192` | worker |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | frontend (set in `frontend/.env.local`) |

The worker runs one job at a time on purpose: speech recognition uses all CPU cores and
several hundred megabytes of memory, and the AI model several gigabytes, so two at once
would only make both slower. After a job, Ollama keeps the model in memory for about five
minutes (its own default) so the next coaching starts quickly. A bigger
model (`WHISPER_MODEL=medium`) is more accurate, especially for Hindi, and several times
slower.

## Where your data is

| What | Where | When it is deleted |
| --- | --- | --- |
| Checklist progress | This browser's `localStorage` | When you reset or clear it, or clear site data |
| A recording you just made or chose, for playback | This browser tab's memory | When the tab is closed or refreshed |
| An uploaded recording | `backend/data/uploads/` | As soon as its job succeeds or is cancelled, or fails in a way a retry cannot fix |
| A recording whose job failed but could be retried | `backend/data/uploads/` | On a successful retry, when you discard the job, or after 24 hours |
| A recording you asked to keep ("Keep this recording") | `backend/data/audio/` | When you delete the recording, delete its analysis, or clear the history, on the General Practice screen |
| A reference recording and its measurements | `backend/data/audio/` (kept by default; untick to store measurements only) and the database | When you delete that reference. Clearing the history of takes does not touch references |
| Which reference is chosen | This browser's `localStorage` | When you choose none, or delete it |
| Analysis results, their coaching, and jobs | `backend/data/monologue_coach.db` | When you delete an analysis or clear the history |
| What the AI model is sent: the transcript and measurements, as text | Ollama's memory on this computer, while it writes the answer | This app saves it nowhere else. Whether Ollama logs anything is up to Ollama's own settings |

Nothing is sent off this computer. The AI model is only ever contacted at an address on this
computer, and it is never given audio. The folder `backend/data/` is not tracked by git.

## Checks

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

The tests never need Ollama: the AI model is replaced by a scripted stand-in.

One extra backend test runs the real speech model on speech generated by macOS's `say`
command. It is skipped by default because it takes several seconds:

```bash
cd backend && RUN_SPEECH_TESTS=1 uv run pytest tests/test_real_speech.py
```
