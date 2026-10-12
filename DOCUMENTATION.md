# Monologue Coach — Project Documentation (start here)

These documents explain how the project is built, written so that a beginner can read them
top to bottom and understand what each part does and why it was built that way.

| Document | What is in it |
| --- | --- |
| **This file** | What the app is, what is built, how the parts fit together, glossary |
| [DOCUMENTATION_FRONTEND.md](DOCUMENTATION_FRONTEND.md) | Everything that runs in the browser: pages, the Monologues list, Daily Practice on a monologue (the checklist, the timer, the tools of each step), a take's full analysis, General Practice, the feedback controls and the calibration panel, browser storage, and the frontend decisions |
| [DOCUMENTATION_BACKEND.md](DOCUMENTATION_BACKEND.md) | The Python side: the API list, the database, the job queue and worker (and why there is no Celery), how monologues and their takes are kept together, how feedback, calibration and revisions are stored, and the backend decisions |
| [DOCUMENTATION_SCIENCE.md](DOCUMENTATION_SCIENCE.md) | How a recording is measured — speech detection, pauses, the three kinds of WPM, loudness, pitch — with formulas and limits; how the coaching is produced with a local AI model and how its answer is checked; how a take is compared with a reference recording; how feedback adjusts settings, and what it is not allowed to change; and the science decisions |
| [README.md](README.md) | The commands to install, run and check the app |

The documents are updated at the end of every phase. Every phase in the original plan
(0 to 6) is built, Phase 7 added what Phase 6 had left out, Phase 8 joined the Monologue
screen and Daily Practice into one flow, and Phase 9 added where a voice sits (its pitch
and its resonance) and an optional voice goal. If the code and a document ever disagree, the code
is right and the document needs fixing.

**Last updated:** end of Phase 9 (every result says where the voice sat, in pitch and in
resonance, for the recording and for each phrase; a speaker may choose to keep their
voice lower or higher, and the coaching then follows that). Before that, Phase 8 (a list
of monologues, Daily Practice done on one of them, takes stored under their monologue).

## 1. What this app is

A speaking-practice coach for Hindi and English monologues that runs entirely on your own
computer. No paid services, no cloud, no account. The full plan has these parts:

- **Daily Speaking Practice**: a timed five-step checklist with a history of recent days.
- **Monologue comparison**: compare your recording with the original actor's.
- **General Practice**: record or upload your voice, get measured feedback (speed, pauses,
  loudness, pitch) and coaching from a local AI model.
- **Feedback / calibration**: tell the app when its analysis was wrong so it adjusts.

All four are built. Since Phase 8 the first two are one flow, because the daily routine is
always done on a monologue. There are three places in the navigation:

- **Monologues**: the list of monologues you practise. A monologue is added by giving its
  original recording once. Choosing one opens Daily Practice for it;
- **Daily Speaking Practice**: the timed five-step routine, done on that monologue. Each
  step holds what it is done with: the original to listen to and study, its script with
  the measured pauses, the recorder for your take, the comparison of the take with the
  original pause by pause and phrase by phrase, and the two biggest differences. Every
  take is saved under its monologue, and each has a page with its full analysis;
- **General Practice**, for any speaking that has no original to set it against: you
  record or upload your voice, see it measured, and get coaching against a delivery
  profile you choose. The coaching is worded by an AI model running on this computer
  (Ollama), or by fixed rules when that model is not available.

**Feedback and calibration** live wherever a full result is shown: a take's full analysis,
and General Practice. Beside each pause, phrase and correction you can say where the
analysis got it wrong: this pause was a slip, a pause was missed here, these words are
wrong, this advice was not useful. Two things come of it. A
label on a pause changes how the coaching reads that pause. And when several reports
agree, one setting moves a small step, inside a fixed range, with the reason shown and an
undo. No feedback ever changes a measurement that is already stored.

A monologue's original recording (its reference) takes feedback too, in step 1 of Daily
Practice: its misheard words can be corrected, and mistakes in its pauses reported. The panel that shows the settings also
counts up everything you have said so far, and on request the local AI model puts that
count into a few sentences. That summary is only something to read.

**Where your voice sits** (Phase 9) is part of every result. The app measures the pitch
of the voice and its resonance (how deep or bright it sounds), and places each in one of
three stated ranges: lower, neutral or higher, with how far into the range it lies. It
does this for the whole recording and for every phrase. The ranges describe how a voice
is typically heard; the app never says who is speaking. If you are working on your voice
you can choose a goal, "keep my voice lower" or "keep my voice higher", and the coaching
then points at the phrases that left that range and gives a drill. With no goal, nothing
about it is judged.

All three programs can be started with one command: `./run.sh`.

## 2. What is built so far

| Phase | What | Frontend | Backend | Status |
| --- | --- | --- | --- | --- |
| 0 | Project skeleton, database setup, health check | Home page, backend status dot | API with one endpoint, empty database | **Built** |
| 1 | Daily Speaking Practice checklist | The whole feature | Nothing — not touched | **Built** |
| 2 | Audio pipeline, job table and worker | Nothing — not touched | The whole phase: 5 new endpoints, 3 tables, the worker, the measurements | **Built** |
| 3 | General Practice screen (record, upload, results, history) | The whole screen: recording, upload, job progress, results, chart, compare, history | 6 small endpoints (form options, list, delete, kept audio); typical-pace labels; a fix to the speech recogniser's settings | **Built** |
| 4 | AI coaching through the local Ollama model | The Coaching section of the results, "write the coaching again", a notice when the model is unavailable | Findings, templates, the Ollama client, checks on the model's answer, a coaching-only job, 1 new endpoint, 4 new database columns | **Built** |
| 5 | Reference comparison, Monologue screen, waveform overlay | The Monologue screen, the reference library, the comparison section (also inside General Practice), the waveform picture, checklist links | Reference recordings as a role of analysis, lining up two transcripts, the comparison, the waveform outline, 2 new endpoints, 5 new database columns | **Built** |
| 6 | Feedback and automatic calibration | Feedback controls beside each pause, phrase and correction; the list of what was said; the calibration panel with undo, reset and on/off; revisions in the header and history | Storing feedback; deciding what each piece counts towards; the adjustment rules; versions of the settings; corrected transcripts and fresh analyses as new revisions; 9 new endpoints, 3 new tables | **Built** |
| 7 | What Phase 6 left out, and one command to start the app | Picking the word a missed pause came after; feedback controls on a reference, on the Monologue screen; "What your feedback adds up to" in the calibration panel, with a button to ask the AI model | Feedback and transcript corrections on references; the rule that a setting needs a report from one of your own takes; the facts counted from the feedback; a third kind of job that has the AI model word them, with checks; 2 new endpoints, 1 new table; `run.sh` | **Built** |
| 8 | Monologues and Daily Practice as one flow | The Monologues list; Daily Practice on a chosen monologue, with the tools of each step under it; the script of the original; rounds ("practise again"); a page for a take's full analysis; General Practice without the reference comparison | Which monologue a take belongs to; the monologues as a list with their takes counted; deleting a monologue with its takes; the General Practice history narrowed to takes that belong to none; 2 new endpoints, 2 new database columns | **Built** |
| 9 | Where a voice sits, and a voice goal | The "Where your voice sits" section of every result (two cards, a table per phrase, the ranges and limits); the goal list on the recording forms, remembered in the browser | Resonance measured from the formants; pitch and resonance placed in three ranges, for the recording and each phrase; the goal carried from the form to the coaching; two new findings and four templates; a check on the AI model's wording; 1 new form field, 1 new database column, no new endpoint | **Built** |

Phase 1 was a frontend-only phase: the checklist runs completely in the browser and never
calls the backend. Phase 2 was a backend-only phase. Phase 3 is where the two meet: the
General Practice screen drives the backend built in Phase 2. Phase 4 touched all three
documents: backend (most of the work), frontend (showing it) and science (how coaching is
produced and checked). Phase 5 again touched all three, about evenly: a new screen, a new
kind of recording, and a new piece of science (comparing two recordings). Phase 6 touched
all three as well: the rules for what feedback may change (science), where it is stored
and how old results stay traceable (backend), and the controls and the panel (frontend).
Phase 7 was not in the original plan: it built three things Phase 6 had named as not
built, and a script at the top of the project. It also touched all three documents.
Phase 8 was not in the plan either. It came from using the app: the daily routine is
always done on a monologue, so keeping the routine on one screen and the monologue on
another made no sense. It is mostly frontend work, with a small backend part (a take
remembers its monologue), and it changes no measurement.
Phase 9 also came from use: a speaker who is working on how their voice is heard asked
whether the app could show it. It is mostly science: a new measurement (resonance) that
was tried on recordings with known answers before anything was shown, the ranges, and
what the AI model may and may not say about them.

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
  │  (the checklist is saved here,   │
  │   with the monologue it is on)   │
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
  a table in it. So are the user's feedback and the calibration: the API writes them, and
  the worker reads the calibration at the start of each job.

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
├── run.sh                       Starts, stops or reports on all three programs  → README
├── .claude/launch.json          Lets the Claude desktop app start the two dev servers
├── claude_monologue_coach_full_implementation_prompt.md   The original requirements
├── frontend/                    Everything that runs in the browser  → frontend document
└── backend/                     The Python API, worker and audio pipeline
                                                       → backend and science documents
```

## 5. Where data is stored

| Data | Where | Who can see it | Status | Explained in |
| --- | --- | --- | --- | --- |
| Daily checklist progress and history, with the monologue each round was on | The browser's `localStorage` | Only this browser on this device | **Built** | Frontend document |
| Which monologue a take was recorded for | The same SQLite file, in the take's `monologue_id` column | Only this computer | **Built** | Backend document |
| The monologues themselves | Nowhere of their own: a monologue is its reference recording, in every revision, plus the takes marked with it | Only this computer | **Built** | Backend document |
| Analysis jobs and results | SQLite file `backend/data/monologue_coach.db` | Only this computer | **Built** | Backend document |
| The coaching for each result | The same SQLite file, in its own column beside the measurements | Only this computer | **Built** | Backend document |
| Reference recordings: their measurements | The same SQLite file, as analyses with the role "reference" | Only this computer | **Built** | Backend document |
| Reference recordings: their audio | `backend/data/audio/`, when kept (the default for a reference) | Only this computer | **Built** | Backend document |
| The waveform outline of each recording | The same SQLite file, in its own column; sent only when the picture is switched on | Only this computer | **Built** | Science document |
| Where the voice sat, and the ranges that placed it | Inside each stored result, in the same SQLite file | Only this computer | **Built** | Science and backend documents |
| The voice goal last chosen | The browser's `localStorage`. Each result also records the goal it was made with | Only this browser on this device | **Built** | Frontend document |
| The ID of an analysis in progress | The browser's `localStorage`, until the job ends | Only this browser on this device | **Built** | Frontend document |
| A recording you just made or chose | The page's memory, until the tab is closed or refreshed | Only this tab | **Built** | Frontend document |
| Uploaded recordings | `backend/data/uploads/`, deleted once analysed | Only this computer | **Built** | Backend document |
| Recordings you ask to keep | `backend/data/audio/` | Only this computer | **Built** | Backend document |
| Feedback: labels, reports, notes | The same SQLite file, in the `feedback` table. Deleted with the analysis it is about | Only this computer | **Built** | Backend document |
| Calibration: the adjusted settings and their history | The same SQLite file, in `calibration_versions`. Rows are only ever added | Only this computer | **Built** | Backend and science documents |
| Later results of one recording (revisions) | The same SQLite file, as further rows in `analyses` | Only this computer | **Built** | Backend document |
| What your feedback adds up to (the facts) | Nowhere: counted from the `feedback` table each time it is shown | Only this computer | **Built** | Science document |
| The AI model's wording of those facts | The same SQLite file, one row in `feedback_summary`. A new one replaces it | Only this computer | **Built** | Backend and science documents |
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

- **Chosen:** the browser sends requests straight to `http://localhost:4321`. The backend
  allows this with a CORS rule (backend decision B4).
- **Why:** later, audio files will be uploaded. Sending them straight to FastAPI avoids
  passing large files through a second server.
- **Decided against:** routing requests through Next.js (a "proxy" or "rewrite"). It hides
  the backend address but adds a hop and its own size and time limits for uploads.

### G3. Each feature stores its data where it is used

- **Chosen:** the checklist saves in the browser; everything that needs Python (jobs,
  analysis results, feedback and calibration) saves in SQLite.
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

### G8. Feedback may change how things are read and how future recordings are measured, never what was measured

- **Chosen:** three firm lines. A label on a pause changes the coaching's reading of it. A
  report can, with others, move one setting for recordings analysed from then on. Nothing
  the user says changes a stored measurement; a correction or a fresh analysis is stored as
  a new revision beside the earlier result.
- **Why:** the brief requires each of the three, and together they are what keeps the
  history meaningful. If last week's results quietly changed whenever a setting moved, no
  two takes could be compared across time.
- **Decided against:** recalculating old results after an adjustment; removing a pause
  from the statistics because it was labelled; multiplying a WPM that "looks wrong" by a
  correction. See science decisions S46 to S64 and backend decisions B38 to B51.

### G9. Settings move by fixed rules, slowly, and say so

- **Chosen:** an adjustment needs several reports that agree, from more than one
  recording; it is small; it stays inside a stated range; it is announced with its reason
  and the number of reports behind it; and it can be undone, reset, or switched off.
- **Why:** an app that adapts invisibly cannot be trusted or debugged. The brief asks for
  conservative, transparent rules, and for the app never to claim it has learned from one
  or two noisy events.
- **Decided against:** letting the AI model decide what to adjust, or adjusting a little
  on every click.

### G10. A setting is adjustable only if moving it does something

- **Chosen:** before the speech detector's sensitivity was made adjustable, as the brief
  suggests it could be, its effect was measured on the real detector. Inside its safe range
  it changed almost nothing; outside it, it lost real pauses. So it stays fixed, and the
  reports it would have answered are saved with an honest explanation.
- **Why:** "the app adjusted itself after your feedback", followed by identical results, is
  a false claim. Measuring before promising is the rule this project has followed since
  Phase 4.

### G11. A reference can be corrected, but it cannot retune the app by itself

- **Chosen:** feedback is taken on reference recordings: wrong words can be corrected
  (a new revision of the reference, which takes are then lined up with), and mistakes in
  its pauses reported. Those reports count towards a setting, but a setting moves only if
  at least one of the reports that agree is about one of the user's own takes.
- **Why:** the comparison with a reference is only as good as the reference's own
  measurement, so it has to be correctable. But a reference is often a film clip: another
  voice, another room, sometimes music. The settings are meant to fit the user's
  recordings. Asking for one take to show the same thing lets a reference's reports help
  without letting them decide.
- **Decided against:** refusing feedback on references (the Phase 6 choice, which left a
  misheard reference uncorrectable); counting their reports exactly like a take's; keeping
  a separate set of settings per recording, which the brief rules out.

### G12. The AI model may put feedback into words; it decides nothing

- **Chosen:** what the feedback adds up to is counted by code and always on screen. The
  local AI model is asked only when the user presses a button, is given those counts and
  the user's notes as text, and its answer is checked number by number before it is shown.
  Nothing reads the summary: settings change by the fixed rules of G9 alone.
- **Why:** this is the one use of the model the brief allows here ("may summarise
  feedback"), with its condition that deterministic code applies and validates every
  numeric change. Keeping the summary out of every calculation makes that condition true
  by construction.
- **Decided against:** letting the model suggest a value for a setting; writing a summary
  automatically after every piece of feedback (half a minute of the model's time for a
  sentence nobody asked for).

### G13. The daily routine is done on a monologue, and the two are one flow

- **Chosen:** the Monologues screen is a list. Choosing a monologue opens Daily Practice
  for it, and each of the five steps holds what it is done with. A take recorded in step 4
  belongs to that monologue: it is stored with it, listed under it, and compared with its
  original.
- **Why:** it is how the app is used. Step 1 says "listen to the original" and step 4
  "record and compare"; before Phase 8 both sent the user to another screen, where a
  reference had to be chosen and a take picked from a menu of every take ever made.
- **Decided against:** keeping the two screens and adding more links between them (the
  user still has to carry "which monologue" across in their head); a monologue chosen
  once in a setting (a user with two monologues would be changing a setting daily).
- **What it cost:** the checklist no longer works with nothing chosen, and its tools need
  the backend. The timer and the checkboxes still work without it.

### G14. General Practice has no reference comparison

- **Chosen:** a take made in General Practice is measured and coached against a delivery
  profile, and is never set against a reference recording. A take recorded for a monologue
  is compared with that monologue's original and with no other.
- **Why:** it finishes what G6 started. The three kinds of statement now each have their
  own place: measurements and profile coaching in General Practice, the measured
  comparison in Daily Practice. Before, any take could be compared with any reference,
  including one of different words, which the comparison could only answer with "these do
  not appear to be the same passage".
- **Decided against:** leaving the comparison in General Practice as an option. A
  comparison of a take with an original it was not recorded for is a question nobody
  asked.

### G15. The app describes a voice, and never says who is speaking

- **Chosen:** pitch and resonance are placed in a lower, a neutral or a higher range.
  Each range is explained once, by how such a voice is *typically heard* (as masculine,
  either way, as feminine). The speaker is never labelled, on screen, in the stored
  result or in the coaching. A voice is judged against a range only when the speaker has
  chosen a goal, and then only as "inside" or "outside" the range they chose.
- **Why:** the feature was asked for by someone whose voice is heard differently from how
  they want it to be, and it has to serve them without telling anyone what they are. Two
  measurements cannot know that. They can say where a sound sits, which is also all that
  practice can change. Keeping the goal a direction ("lower" or "higher") makes it work
  the same for any speaker, in either direction, for any reason.
- **Where it is enforced:** in the wording written by code (science decision S78), in
  what the AI model is shown and in a check on what it writes (S81), and on screen
  (frontend decision F79).
- **Decided against:** *a "masculine/feminine" score or label for the speaker*: a guess
  about a person, with nothing behind it that could be checked. *Judging the voice by
  default*: the app's own position is still that a voice's register is nobody's mistake.
- **Honest limit:** the ranges are rough, the resonance ranges were set from synthesised
  voices only, and how a voice is heard depends on much that is not measured here. The
  screens say so beside the figures.

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
| **Reference** | A recording you supply to compare your takes with, such as the original performance. On screen it is called "the original". |
| **Monologue** | One piece you practise: its reference recording, and the takes you recorded for it. |
| **Free take** | A take that belongs to no monologue: one made in General Practice. |
| **Round** | One pass through the five steps of the daily routine. One round is the day's routine; more are extra. |
| **Pitch** | How high or low the note of a voice is, in Hz. |
| **Resonance** | How deep or bright a voice sounds, apart from its note. Measured here as the spacing of its formants, in Hz. |
| **Voice range** | Where a voice sits: its pitch and its resonance, each in the lower, neutral or higher range, with a percentage saying how far into the range. |
| **Voice goal** | Your own choice to keep your voice lower or higher. Optional; it changes the coaching and no measurement. |
| **Line-up (alignment)** | Working out which word of one recording is which word of the other. |
| **Waveform** | A picture of a sound wave. Here it is only ever a picture: nothing is measured from it. |
| **Feedback** | Something you say about one analysis: a label, a report, or a note for the record. |
| **Label** | Your word for what a pause meant: intentional or accidental. It changes the coaching's reading of the pause, never the measurement. |
| **Report** | Feedback saying the analysis got something wrong, such as a missed pause. Several that agree can move a setting. |
| **Calibration** | The current values of the few settings feedback may adjust, with the history of every change. |
| **Minimum pause** | The shortest silence that counts as a pause. 500 ms unless feedback has moved it. |
| **Revision** | A later result made from a recording that already has one, stored beside the earlier result. |
| **Fact (about your feedback)** | One line counted from the stored feedback by code, e.g. "Missed pauses you reported: 5". The AI model's summary may only restate these. |
| **Session (of a program)** | A group of running programs that a terminal treats as one. `run.sh` gives each program its own, so that Ctrl+C reaches the script first and it can stop them in order. |
| **Epoch milliseconds** | A moment in time written as the number of milliseconds since 1 January 1970 UTC. |
| **Pure function** | A function whose result depends only on its inputs and that changes nothing else. Easy to test. |
| **Reconcile** | Here: bringing saved state up to date with the real clock, e.g. finishing a timer that ended while the page was closed. |
| **Lint / type-check** | Automatic checks that catch mistakes without running the app. |
