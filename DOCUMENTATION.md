# Monologue Coach — Project Documentation (start here)

These documents explain how the project is built, written so that a beginner can read them
top to bottom and understand what each part does and why it was built that way.

| Document | What is in it |
| --- | --- |
| **This file** | What the app is, what is built, how the parts fit together, glossary |
| [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md) | Everything that runs in the browser: pages, the Daily Practice checklist, the timer, General Practice, the Monologue screen, browser storage, and the frontend decisions |
| [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md) | The Python side: the API list, the database, the job queue and worker (and why there is no Celery), and the backend decisions |
| [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md) | How a recording is measured — speech detection, pauses, the three kinds of WPM, loudness, pitch — with formulas and limits; how the coaching is produced with a local AI model and how its answer is checked; how a take is compared with a reference recording; and the science decisions |
| [README.md](README.md) | The commands to install, run and check the app |

The documents are updated at the end of every phase. Anything that is not built yet is
clearly marked **Planned**. If the code and a document ever disagree, the code is right and
the document needs fixing.

**Last updated:** end of Phase 5 (comparison with a reference recording, the Monologue
screen, the waveform picture).

## 1. What this app is

A speaking-practice coach for Hindi and English monologues that runs entirely on your own
computer. No paid services, no cloud, no account. The full plan has these parts:

- **Daily Speaking Practice**: a timed five-step checklist with a history of recent days.
- **Monologue comparison**: compare your recording with the original actor's.
- **General Practice**: record or upload your voice, get measured feedback (speed, pauses,
  loudness, pitch) and coaching from a local AI model.
- **Feedback / calibration**: tell the app when its analysis was wrong so it adjusts.

Today three screens exist:

- the **Daily Speaking Practice** checklist;
- **Monologue**, where you add the original recording once, study it, record your own take,
  and see where the two differ, pause by pause and phrase by phrase, with both to listen to;
- **General Practice**, where you record or upload your voice, see it measured, and get
  coaching on what to change for the next take. The coaching is worded by an AI model
  running on this computer (Ollama), or by fixed rules when that model is not available.

Feedback and calibration are not built yet.

## 2. What is built so far

| Phase | What | Frontend | Backend | Status |
| --- | --- | --- | --- | --- |
| 0 | Project skeleton, database setup, health check | Home page, backend status dot | API with one endpoint, empty database | **Built** |
| 1 | Daily Speaking Practice checklist | The whole feature | Nothing — not touched | **Built** |
| 2 | Audio pipeline, job table and worker | Nothing — not touched | The whole phase: 5 new endpoints, 3 tables, the worker, the measurements | **Built** |
| 3 | General Practice screen (record, upload, results, history) | The whole screen: recording, upload, job progress, results, chart, compare, history | 6 small endpoints (form options, list, delete, kept audio); typical-pace labels; a fix to the speech recogniser's settings | **Built** |
| 4 | AI coaching through the local Ollama model | The Coaching section of the results, "write the coaching again", a notice when the model is unavailable | Findings, templates, the Ollama client, checks on the model's answer, a coaching-only job, 1 new endpoint, 4 new database columns | **Built** |
| 5 | Reference comparison, Monologue screen, waveform overlay | The Monologue screen, the reference library, the comparison section (also inside General Practice), the waveform picture, checklist links | Reference recordings as a role of analysis, lining up two transcripts, the comparison, the waveform outline, 2 new endpoints, 5 new database columns | **Built** |
| 6 | Feedback and automatic calibration | Feedback panel | Storing feedback, adjusting settings | Planned |

Phase 1 was a frontend-only phase: the checklist runs completely in the browser and never
calls the backend. Phase 2 was a backend-only phase. Phase 3 is where the two meet: the
General Practice screen drives the backend built in Phase 2. Phase 4 touched all three
documents: backend (most of the work), frontend (showing it) and science (how coaching is
produced and checked). Phase 5 again touched all three, about evenly: a new screen, a new
kind of recording, and a new piece of science (comparing two recordings).

## 3. The big picture

The app is three programs of its own — the frontend, the API and the worker — plus Ollama,
a separate program you install yourself that runs the AI model, and the places where data
lives.

```
            YOUR BROWSER
  ┌──────────────────────────────────┐
  │  Frontend (Next.js / React)      │
  │  the pages you see and click     │
  │                                  │
  │  localStorage                    │
  │  (the checklist is saved here)   │
  └───────────────┬──────────────────┘
                  │  HTTP requests, e.g. GET /api/health
                  ▼
  ┌──────────────────────────────────┐        ┌──────────────────────────┐
  │  Backend API (FastAPI / Python)  │ ─────▶ │  SQLite database file    │
  │  answers requests, queues jobs   │        │  backend/data/*.db       │
  └───────────────┬──────────────────┘        └────────────▲─────────────┘
                  │ saves the upload                       │
                  ▼                                        │
        backend/data/uploads/                              │
                  │ reads it                               │
                  ▼                                        │
  ┌──────────────────────────────────┐                     │
  │  Worker (Python)                 │ ────────────────────┘
  │  analyses audio, one job at a    │   text only     ┌─────────────────────────┐
  │  time, with local models         │ ──────────────▶ │  Ollama (its own        │
  └──────────────────────────────────┘ ◀────────────── │  program, on this       │
                                          coaching      │  computer): the AI      │
                                                        │  model llama3.1:8b      │
                                                        └─────────────────────────┘
```

- The **frontend** is what runs in the browser: pages, buttons, the timer.
- The **API** is a Python program that the frontend sends requests to. It accepts a
  recording, puts a job in the queue and answers at once.
- The **worker** is a second Python program that takes jobs from the queue and does the slow
  work — finding speech, recognising words, measuring, and getting the coaching written —
  so the API never has to wait.
- **Ollama** is not part of this project. It is a free program that runs AI language models
  on your own computer. The worker sends it the transcript and the measurements as text
  (never the audio) and gets the wording of the coaching back. If Ollama is not running,
  everything else still works and the coaching is written from fixed rules instead.
- The **database** is a single file on disk that both of them read and write. The queue is
  a table in it.

The API and the worker never talk to each other directly. They only meet in the database
and in the folder of uploaded files. Only the worker talks to Ollama.

## 4. Top-level folder structure

```
monologue coach/
├── README.md                    How to install, run and check the app
├── DOCUMENTATION.md             This file
├── DOCUMENTATION_FRONTEND.md    Frontend documentation
├── DOCUMENTATION_BACKEND.md     Backend documentation
├── DOCUMENTATION_SCIENCE.md     How the audio is measured, and the AI model
├── .env.example                 Template for optional settings (copy to .env)
├── .gitignore                   Files git should not track (secrets, database, caches)
├── .claude/launch.json          Lets the Claude desktop app start the two dev servers
├── claude_monologue_coach_full_implementation_prompt.md   The original requirements
├── frontend/                    Everything that runs in the browser  → frontend document
└── backend/                     The Python API, worker and audio pipeline
                                                       → backend and science documents
```

## 5. Where data is stored

| Data | Where | Who can see it | Status | Explained in |
| --- | --- | --- | --- | --- |
| Daily checklist progress and history | The browser's `localStorage` | Only this browser on this device | **Built** | Frontend document |
| Analysis jobs and results | SQLite file `backend/data/monologue_coach.db` | Only this computer | **Built** | Backend document |
| The coaching for each result | The same SQLite file, in its own column beside the measurements | Only this computer | **Built** | Backend document |
| Reference recordings: their measurements | The same SQLite file, as analyses with the role "reference" | Only this computer | **Built** | Backend document |
| Reference recordings: their audio | `backend/data/audio/`, when kept (the default for a reference) | Only this computer | **Built** | Backend document |
| The waveform outline of each recording | The same SQLite file, in its own column; sent only when the picture is switched on | Only this computer | **Built** | Science document |
| Which reference is chosen | The browser's `localStorage` | Only this browser on this device | **Built** | Frontend document |
| The ID of an analysis in progress | The browser's `localStorage`, until the job ends | Only this browser on this device | **Built** | Frontend document |
| A recording you just made or chose | The page's memory, until the tab is closed or refreshed | Only this tab | **Built** | Frontend document |
| Uploaded recordings | `backend/data/uploads/`, deleted once analysed | Only this computer | **Built** | Backend document |
| Recordings you ask to keep | `backend/data/audio/` | Only this computer | **Built** | Backend document |
| Feedback and calibration | SQLite | Only this computer | Planned | |
| The speech model | `~/.cache/huggingface/` (downloaded once) | Only this computer | **Built** | Science document |
| The AI language model | Inside Ollama's own folder (`~/.ollama/`). Installed by you; this app never downloads it | Only this computer | **Built** | Science document |
| Settings | Optional `.env` file in the project root | Only this computer | **Built** | README |

## 6. Decisions that affect both halves

Each entry says what was chosen, what was considered, and what was decided against and why.
Frontend decisions (F1, F2…), backend decisions (B1, B2…) and science decisions (S1, S2…)
are in their own documents.

### G1. Two separate apps: Next.js frontend and FastAPI backend

- **Chosen:** a Next.js (React) app for the screens and a Python FastAPI app for the API.
- **Why:** this is the stack the requirements name. It also fits the work: the audio and
  speech libraries are Python, while a timer and recording UI is easiest in React.
- **Decided against:**
  - *Streamlit or Chainlit* (Python-only UIs): ruled out by the requirements, and they give
    little control over a custom timer, microphone recording or layout.
  - *Next.js alone, with its own API routes*: the API would be JavaScript, but the audio
    tools are Python.

### G2. The frontend calls the backend directly

- **Chosen:** the browser sends requests straight to `http://localhost:8000`. The backend
  allows this with a CORS rule (backend decision B4).
- **Why:** later, audio files will be uploaded. Sending them straight to FastAPI avoids
  passing large files through a second server.
- **Decided against:** routing requests through Next.js (a "proxy" or "rewrite"). It hides
  the backend address but adds a hop and its own size and time limits for uploads.

### G3. Each feature stores its data where it is used

- **Chosen:** the checklist saves in the browser; everything that needs Python (jobs and
  analysis results today, feedback and calibration later) saves in SQLite.
- **Why and what was decided against:** see frontend decision F2 and backend decision B1.

### G4. After setup, nothing leaves this computer

- **Chosen:** speech recognition, speech detection and the AI model all run locally. The
  internet is used only by the setup commands: installing packages and downloading the
  speech model once. The worker is started in offline mode and cannot download anything.
  The AI model is reached only at an address on this computer; an address pointing at
  another machine is refused (science decision S31), and the worker never asks Ollama to
  download a model.
- **Why:** required by the project brief, and a voice recording is personal data.
- **Decided against:** cloud speech-to-text or cloud AI models, which are often more
  accurate and faster but send recordings to someone else's servers and cost money per use.
- **Trade-off accepted:** accuracy and speed are limited by this laptop. See "Accuracy and
  limits" in the science document.

### G5. Measuring and explaining are done by different things

- **Chosen:** every number is calculated by ordinary code. The AI model only chooses among
  facts that code has already written down and words the advice about them; its answer is
  then checked against the measurements before anything is shown.
- **Why and what was decided against:** see science decisions S21 and S24 to S35, and
  section 13 of the science document.

### G6. Three kinds of statement, never mixed

- **Chosen:** the app says three different kinds of thing about a take, and keeps them in
  separate places on screen and in the code:

  | Kind | Example | Produced by |
  | --- | --- | --- |
  | A measurement | "You paused for 2.6 seconds" | The audio pipeline |
  | A judgement against a profile described in words | "For Walter White, pauses this short work against the profile" | Coaching (findings, then the AI model or templates) |
  | A measured comparison with a real recording you supplied | "The reference pauses 6.1 seconds here; you did not" | The comparison |

- **Why:** the brief requires it, and it is what keeps the app honest. A profile is a
  description, with no recording behind it; a reference is a recording. Running the two
  together would let a description pass for a measurement.
- **Decided against:** folding the reference comparison into the coaching, so that one
  list of corrections drew on both. It may be worth doing later; it should be a deliberate
  step, taken after the comparison has been tried on real recordings.

### G7. A reference is supplied by the user and treated like any other recording

- **Chosen:** the app ships with no recordings of any actor. A reference is a file the user
  adds, measured on this computer by the same pipeline as their own takes, and never sent
  anywhere. The app compares timing and delivery; it does not copy, clone or generate a
  voice.
- **Why:** the rights to a recording are the user's to have, and the brief rules out voice
  cloning. Measuring a reference the same way as a take is also what makes the comparison
  fair.

## 7. Glossary

| Word | Meaning |
| --- | --- |
| **Frontend** | The part of an app that runs in the browser. |
| **Backend** | The part that runs as a server program and answers requests. |
| **API / endpoint** | The set of addresses a backend answers; one address is an endpoint. |
| **HTTP request** | A message from the browser to a server, such as "GET /api/health". |
| **Next.js / React** | React builds screens out of components; Next.js adds pages, routing and a build system on top. |
| **Component** | A reusable piece of screen, like a button or the timer panel. |
| **Hook** | A React function whose name starts with `use`, giving a component state or behaviour. |
| **FastAPI** | A Python library for writing APIs. |
| **SQLite** | A database that is a single file, with no server. |
| **Migration** | A small script that changes the database structure, so changes are repeatable. |
| **Alembic** | The tool that runs migrations for this project. |
| **`localStorage`** | A small key–value store built into every browser, private to one site. |
| **JSON** | A text format for data, e.g. `{"status": "ok"}`. |
| **CORS** | A browser safety rule: a page may only call a server on another address if that server says it is allowed. |
| **Queue / job / worker** | A job is a piece of slow work; the queue is the waiting list; the worker is the program that does the jobs. |
| **Polling** | Asking "is it done yet?" repeatedly at an interval. |
| **Celery / Redis** | A Python job-queue library and the in-memory server it usually needs. Not used here. |
| **Ollama** | A program that runs AI language models on your own computer. |
| **Language model (LLM)** | A program that writes text one small piece at a time. Here: `llama3.1:8b`, used only to word the coaching. |
| **Prompt** | The text sent to a language model: its instructions plus the data to work from. |
| **Token** | The small pieces of text a language model reads and writes; roughly a word or part of one. |
| **Finding** | One plain statement of fact about a recording, written by code from the measurements, e.g. "You spoke at 240 WPM". |
| **Grounding** | Making sure everything the model says rests on something that was actually measured. |
| **Template** | A fixed sentence with gaps that code fills in, e.g. "Say {line} at half speed". |
| **Take** | One of your own recordings. |
| **Reference** | A recording you supply to compare your takes with, such as the original performance. |
| **Line-up (alignment)** | Working out which word of one recording is which word of the other. |
| **Waveform** | A picture of a sound wave. Here it is only ever a picture: nothing is measured from it. |
| **Epoch milliseconds** | A moment in time written as the number of milliseconds since 1 January 1970 UTC. |
| **Pure function** | A function whose result depends only on its inputs and that changes nothing else. Easy to test. |
| **Reconcile** | Here: bringing saved state up to date with the real clock, e.g. finishing a timer that ended while the page was closed. |
| **Lint / type-check** | Automatic checks that catch mistakes without running the app. |
