# Monologue Coach

A local speaking-practice coach for Hindi and English monologues. Everything runs on this
device: no paid APIs, no cloud services, no accounts.

> Status: every part of the plan is built. **Monologues** (the monologues you practise,
> each with its original recording), **Daily Speaking Practice** (a timed routine on one
> monologue: listen, mark, perform, record your take and compare it with the original),
> **General Practice** (record or upload any speaking, see it measured, and get coaching),
> **where your voice sits** (its pitch and its resonance, in a lower, neutral or higher
> range, with an optional goal to keep it lower or higher),
> and **feedback with calibration** (tell the app where it was wrong; it adjusts, slowly
> and visibly). Start all of it with one command: `./run.sh`.

How the project works, file by file, and why each design decision was made:

- [DOCUMENTATION.md](DOCUMENTATION.md) — start here
- [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md) — pages, the checklist, the timer
- [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md) — API, database, job queue and worker
- [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md) — how the audio is measured, how the coaching is produced and checked, how two recordings are compared, and how feedback adjusts settings

## What you can do today

- **Monologues** at `/monologue`: the list of monologues you practise. Add one by giving
  the original recording of it once (a file you have the right to use). **Practise** on a
  monologue opens its Daily Practice. Deleting a monologue deletes its original and its
  takes.
- **Daily Speaking Practice** at `/practice`: a timed five-step, 15-minute routine, done on
  the monologue you chose. Each step has what it is done with underneath it:
  1. *Listen and observe*: the original, with its measured pauses, pace, loudness and pitch.
  2. *Mark the delivery*: the original as a script, each phrase on a line, with the measured
     pause after it and the words that stood out.
  3. *Perform the monologue*: the same script to perform from.
  4. *Record and compare*: record or upload your take. It is analysed and set against the
     original: the biggest differences first, then pause by pause and phrase by phrase,
     each with both versions to listen to. Every take is saved under its monologue and can
     be opened again on any day, with a link to its full analysis.
  5. *Correct and repeat*: the two biggest differences, and the way back to recording.

  One round is the day's routine. When it is finished, **Practise again** starts another
  round, on the same monologue or another; the day's record shows how many rounds were
  done and on which monologues. The checklist's progress is saved in this browser's
  `localStorage`; the timer works even when the API is not running, the tools need it.
  The comparison works by lining up the recognised words, so a take needs to be of the
  same text as its original.
- **A take's full analysis** at `/monologue/take`: reached from step 4. Every measurement
  of that take, its coaching, the comparison with the original, and the feedback controls.
- **General Practice** at `/general`: for any speaking, without an original to compare
  with. Choose a delivery profile, record in the browser or upload a file, and get
  your pace, every pause, loudness and pitch, phrase by phrase,
  with a timeline you can click to listen. Its analyses are kept in a history of their own
  and can be compared, reopened and deleted. It needs the API and the worker running; the
  screen tells you if either is missing.
- **Coaching** with every analysis: up to three corrections, most important first, each
  with what was measured, why it matters, a drill, and the phrase to practise on with a Play
  button; then what is already working, targets for the next take, and what is uncertain.
  The wording comes from an AI model running on this computer through
  [Ollama](https://ollama.com), and every figure in it is checked against the measurements.
  If Ollama is not running, the analysis still works and the coaching is written from fixed
  rules instead; you can ask the model again later without re-recording.
- **Phrases and pace**, in every result. A silence of half a second or more is a pause. A
  phrase ends only at a pause of a second or more; a shorter pause stays inside its phrase
  and is shown at the place it fell, like "Be honest are ‖ 0.5 s all of us". Each phrase,
  and the recording as a whole, has two paces:

  | Pace | Worked out as | What it is for |
  | --- | --- | --- |
  | **Delivery pace** | words ÷ the length of the phrases, short pauses inside them counted | The figure shown first, and the one to practise against |
  | Speaking speed | words ÷ the time spent speaking, every pause left out | How fast the words themselves were said |

  A delivery is slowed by pausing, not by saying the words slowly, so the coaching for a
  fast pace asks for short stops inside the line and leaves the words alone. A third
  figure, the whole-clip WPM, also counts the long pauses and the silence at both ends; it
  is shown and never used to judge speed.
- **Where your voice sits**, in every result. Two things decide how a voice is heard: its
  pitch (the note it speaks on) and its resonance (how deep or bright it sounds). The app
  measures both and places each in one of three ranges, with how far into the range it
  lies, for the whole recording and for every phrase:

  | Range | Typically heard as | Pitch | Resonance (formant spacing) |
  | --- | --- | --- | --- |
  | Lower | a masculine voice | under 145 Hz | under 1,040 Hz |
  | Neutral | either | 145 to 175 Hz | 1,040 to 1,100 Hz |
  | Higher | a feminine voice | over 175 Hz | over 1,100 Hz |

  The percentage is a position inside the range, not a probability. The ranges describe
  how a voice is typically heard; the app never says who is speaking. They are rough, and
  the resonance ranges were set from synthesised voices, not from recordings of people.
  Resonance needs a quiet room: with a noisy background it is labelled an estimate or
  left out.
- **A voice goal** (optional), on the recording form: *Keep my voice lower* or *Keep my
  voice higher*. The coaching then points at the phrases where your pitch or resonance
  left that range, with a drill to do on the phrase furthest from it. With no goal,
  nothing about where your voice sits is judged. The choice is remembered in this browser.
  The drills are gentle voice exercises, not medical advice: stop if your throat feels
  strained, and consider a voice coach or a speech therapist for guidance.
- **Download** any analysis as a Markdown file (a plain text document that opens in any
  editor): **Download as Markdown** in the header of a result; **Download** on a monologue,
  for its original and every take of it; **Download all as Markdown** in the General
  Practice history; and **Download every analysis as Markdown** at the top of the
  Monologues list for everything at once. The file holds every measurement, each phrase
  with its pauses, the coaching with the facts and bands behind it, your feedback, and
  for a take of a monologue its comparison with the original. To get a PDF, open the file
  and print it.
- **Feedback** on every result of your own, next to the thing it is about. On a pause:
  intentional, accidental, "not a pause: I was still speaking", or "too short to split the
  phrase". On a phrase: a pause was missed (pick the silence the app heard, or the word
  the pause came after), the WPM looks too high or too low, or the words are wrong (type
  them as you said them). On a correction: useful or not useful. Feedback is optional and
  never changes a measurement that is already stored.
- **Feedback on the original recording** (the reference), in step 1 of Daily Practice:
  correct its misheard words, so that your takes are lined up with the right ones, and
  report mistakes in its pauses. A reference alone never moves a setting; a take of your
  own has to show the same thing.
- **Calibration**, in a panel at the bottom of Daily Practice, of a take's full analysis
  and of General Practice. When at least three
  reports agree, from at least two recordings, one setting moves a small step inside a
  fixed range: the shortest silence that counts as a pause (500 ms by default, 250 to 800
  ms allowed), or how readily a kind of correction is put first. The panel shows every
  value, what changed, why, and on how many reports, with **Undo last adjustment**, **Reset
  to defaults**, and a switch to turn automatic adjustment off. It tunes rules of thumb to
  your recordings. It does not retrain the speech recogniser or make the analysis perfect.
- **What your feedback adds up to**, in the same panel: how much you have said and about
  what, with the measured figures, counted by the app's own code and always current. Under
  it, the notes you wrote. If you ask, the local AI model picks out the three most telling
  notes; it only chooses, and the words shown are yours.
- **Revisions.** Correcting a phrase's words makes a new result with word counts and WPM
  worked out again from your words; analysing a kept recording again uses the settings as
  they are now. Either way the earlier result stays, unchanged, and says which settings
  produced it.

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

**Updating from an earlier phase?** Run the database step again, so the database gets its
new tables and columns. Existing analyses are kept: they become "takes", made with the
default settings, each the first result of its own recording. A take stored before Phase 8
belongs to no monologue, so it shows in the General Practice history; a reference recording
stored before it is now a monologue. A result stored before Phase 9 does not say where the
voice sits, and one stored before Phase 10 ends a phrase at every pause and shows only a
speaking speed. Analysing the recording again brings either up to date, if the recording
was kept; the screen says so on such a result. A monologue's original is kept by default,
so open it in step 1 of Daily Practice and press **Analyse this recording again** once.
No database step is new in Phase 10:

```bash
cd backend && uv run alembic upgrade head
```

`./run.sh` does this step by itself every time it starts the app. Also restart the worker
after an update: it loads its code once, when it starts.

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

The app is three programs: the API, the worker and the frontend. One command starts all
three in one terminal, with each line of output marked `[api]`, `[worker]` or `[web]`:

```bash
./run.sh
```

It first brings the database up to date, then starts whatever is not already running, and
says "Monologue Coach is running. Open http://localhost:1234" when the app answers. Press
`Ctrl+C` there to stop all three. The worker finishes the step it is on and puts an
unfinished job back in the queue; press `Ctrl+C` again to stop it at once.

From any other terminal:

```bash
./run.sh status
```

```bash
./run.sh stop
```

`stop` stops all three however they were started, including a worker left running in
another window. The script only ever touches programs started from this folder. If port
4321 or 1234 is in use by something else, it says what, leaves it alone, and starts
nothing; other ports can be given as `API_PORT=5000 PORT=5001 ./run.sh`.

For AI coaching, Ollama must also be running: open the Ollama app, or run `ollama serve`
in another terminal. The script never starts it. The worker says in its first lines
whether it found it.

### The three programs by hand

The same thing, each program in its own terminal. The checklist needs only the frontend;
audio analysis needs all three.

API, on http://localhost:4321:

```bash
cd backend && uv run uvicorn app.main:app --reload --port 4321
```

Worker (runs the analysis jobs, one at a time):

```bash
cd backend && uv run python -m app.worker
```

Frontend, on http://localhost:1234:

```bash
cd frontend && npm run dev
```

Then open http://localhost:1234 in a browser. The port is fixed on purpose: the browser
keeps the checklist's saved data per address, so a changing port would hide it. To use
another port, run `PORT=4000 npm run dev`. (The frontend's default port was 3210 before it
became 1234: checklist history saved back then shows again under `PORT=3210 npm run dev`.)

If you run the API on a port other than 4321, tell the frontend where it is: create
`frontend/.env.local` containing `NEXT_PUBLIC_API_BASE_URL=http://localhost:<port>`.

Stop any of them with `Ctrl+C`. The worker finishes its current step, puts an unfinished
job back in the queue and exits; press `Ctrl+C` a second time to stop it immediately.

## Health check and troubleshooting

```bash
curl http://localhost:4321/api/health
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
curl -s -X POST http://localhost:4321/api/analyses -F "audio=@/path/to/recording.m4a" -F "language=auto"
```

To have the coaching read the recording against a voice goal, add `-F "voiceGoal=lower"`
(or `higher`). Where the voice sat is measured either way, and is under `voiceRange` in
the result.

Ask how the job is doing (replace `JOB_ID`). Repeat until `status` is `succeeded`:

```bash
curl -s http://localhost:4321/api/jobs/JOB_ID
```

Fetch the result, using the `analysisId` from the finished job. The coaching is under
`coaching`:

```bash
curl -s http://localhost:4321/api/analyses/ANALYSIS_ID
```

Save an analysis, or everything stored, as a Markdown file:

```bash
curl -s -OJ http://localhost:4321/api/analyses/ANALYSIS_ID/export
```

```bash
curl -s -OJ "http://localhost:4321/api/export?scope=all"
```

Have the coaching written again by the AI model. This prints a new job to follow the same
way:

```bash
curl -s -X POST http://localhost:4321/api/analyses/ANALYSIS_ID/coaching
```

Add a monologue: the original recording of it, as a reference. It is followed like any
job; it gets no coaching:

```bash
curl -s -X POST http://localhost:4321/api/analyses -F "audio=@/path/to/original.m4a" -F "role=reference" -F "title=The original" -F "retainAudio=true"
```

List the monologues. `monologueId` names one; `referenceId` is its original recording in
its newest revision:

```bash
curl -s http://localhost:4321/api/monologues
```

Submit a take of a monologue, so that it is stored under it:

```bash
curl -s -X POST http://localhost:4321/api/analyses -F "audio=@/path/to/take.m4a" -F "monologueId=MONOLOGUE_ID"
```

List the takes of one monologue, or the takes that belong to none (the General Practice
history):

```bash
curl -s "http://localhost:4321/api/analyses?monologue=MONOLOGUE_ID"
```

```bash
curl -s "http://localhost:4321/api/analyses?monologue=none"
```

Compare a take with a reference:

```bash
curl -s http://localhost:4321/api/analyses/ANALYSIS_ID/comparison/REFERENCE_ID
```

Mark a pause as accidental. The answer lists the feedback on that analysis, with a
sentence saying what each piece does, and the calibration:

```bash
curl -s -X POST http://localhost:4321/api/analyses/ANALYSIS_ID/feedback -H "Content-Type: application/json" -d '{"category": "pause_accidental", "targetId": "pause-1"}'
```

See the settings in force, their allowed ranges, and the history of every change:

```bash
curl -s http://localhost:4321/api/calibration
```

Undo the most recent adjustment (answers `409` if there is none):

```bash
curl -s -X POST http://localhost:4321/api/calibration/undo
```

Correct the words of a phrase. The answer is a new revision with WPM worked out again. It
works on a reference too:

```bash
curl -s -X POST http://localhost:4321/api/analyses/ANALYSIS_ID/transcript -H "Content-Type: application/json" -d '{"corrections": [{"segmentId": "seg-1", "text": "the words as you said them"}]}'
```

See what all your feedback adds up to, and the notes you wrote:

```bash
curl -s http://localhost:4321/api/feedback-summary
```

Ask the AI model to pick out the most telling notes (answers `409` with fewer than five
notes of a few words or more). Fetch the summary again a few seconds later for its pick:

```bash
curl -s -X POST http://localhost:4321/api/feedback-summary
```

Accepted files: WAV, MP3, M4A, AAC, MP4, OGG, Opus, WebM, FLAC and AIFF, up to 50 MB and
10 minutes. `language` can be `auto`, `en`, `hi` or `hinglish`. All endpoints are listed,
and can be tried in the browser, at http://localhost:4321/docs.

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
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:4321` | frontend (set in `frontend/.env.local`) |

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
| A recording you asked to keep ("Keep this recording") | `backend/data/audio/` | When you delete the recording or its analysis. Clearing the General Practice history deletes those of General Practice only |
| A monologue: its original recording and that recording's measurements | `backend/data/audio/` (kept by default; untick to store measurements only) and the database | When you delete the monologue. Clearing the General Practice history does not touch it |
| The takes of a monologue: their results and coaching | `backend/data/monologue_coach.db`, each marked with its monologue | When you delete the take, or its monologue. Clearing the General Practice history does not touch them |
| Which monologue today's routine is on, and the rounds done | This browser's `localStorage`, with the checklist | With the checklist |
| The voice goal you last chose | This browser's `localStorage`. Each result also records the goal it was made with | When you choose "No goal", or clear site data |
| General Practice results, their coaching, and jobs | `backend/data/monologue_coach.db` | When you delete an analysis or clear the General Practice history |
| Your feedback on a result: labels, reports, notes, corrected words | `backend/data/monologue_coach.db` | With the analysis it is about, or one at a time with "Remove" |
| The calibration: the adjusted settings and the history of every change | `backend/data/monologue_coach.db` | Never deleted, so that every result can be traced to the settings that made it. "Reset to defaults" puts the values back; the history stays |
| The notes the AI model last picked out | `backend/data/monologue_coach.db`, one row | Replaced by the next pick. Not shown once the feedback they came from is deleted |
| A later result of the same recording (a corrected transcript, or a fresh analysis) | `backend/data/monologue_coach.db`, and `backend/data/audio/` if the recording was kept | Like any other analysis. Each can be deleted on its own |
| What the AI model is sent: for coaching, the transcript and measurements; for picking notes, the notes you wrote. Always as text | Ollama's memory on this computer, while it writes the answer | This app saves it nowhere else. Whether Ollama logs anything is up to Ollama's own settings |

Nothing is sent off this computer. The AI model is only ever contacted at an address on this
computer, and it is never given audio. Feedback and calibration are handled by ordinary
code on this computer; the AI model has no part in adjusting a setting, and what it picks
out of your notes is read by nothing. The folder `backend/data/` is not tracked by git.

## Checks

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

If `npm run dev` is running, restart it after `npm run build`: the two share a folder, and
the development server can go on serving an out-of-date stylesheet.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
```

The tests never need Ollama: the AI model is replaced by a scripted stand-in.

One extra backend test runs the real speech model on speech generated by macOS's `say`
command. It is skipped by default because it takes several seconds:

```bash
cd backend && RUN_SPEECH_TESTS=1 uv run pytest tests/test_real_speech.py
```
