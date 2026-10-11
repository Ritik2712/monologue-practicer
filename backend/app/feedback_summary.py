"""What all the feedback the user has given adds up to.

There are two parts, each done by whichever of code and the language model does it reliably.

**The facts** are counts and measured figures read from the stored feedback by ordinary
code. They are the summary: always on the screen, always current, never worded by a model.

**The notes** are the user's own words. They are listed as written. On request, the local
language model picks out the few that, between them, best show what the notes are about:

    the notes, numbered -> language model -> the numbers of the notes it picked

The model is given the notes and nothing else: no counts, no settings, no transcript. It
answers with numbers only, and the JSON schema lets it name only notes that exist. What is
then shown is those notes, word for word. Nothing the model writes reaches the screen, so
there is nothing it can get wrong except its choice.

That is deliberate. Two freer designs were tried on the real model first (science decisions
S69 and S70). Asked to restate the counts, it kept every number and still said wrong things
about what the numbers counted. Asked to say in its own words what the notes have in
common, it added things that no note said.

Nothing here changes a setting, and nothing that changes a setting reads any of this: that
stays with the fixed rules in `app.calibration`.
"""

import hashlib
import json
import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import job_queue, schemas
from app.calibration import store
from app.calibration.registry import ADAPTIVE, CORRECTION_KINDS, MIN_PAUSE, show
from app.llm import ChatModel, LlmError, Message
from app.models import Analysis, Feedback, Job, StoredSummary

logger = logging.getLogger("app.feedback_summary")

# With fewer notes than this there is nothing to pick from: they are all on the screen.
MIN_NOTES = 5
# The most recent notes are listed and given to the model; older ones are only counted.
MAX_NOTES = 15
# How many notes the model is asked to pick.
PICKS = 3
# A note shorter than this ("ok", "wrong") tells nobody anything, so it is never offered to
# the model. On the real model, such notes were picked in 9 runs out of 10 when they were.
MIN_NOTE_WORDS = 3
# How many kinds of coaching correction are named in the fact about ratings.
MAX_KIND_FACTS = 4
# Room for three short numbers in JSON, and no more.
MAX_ANSWER_TOKENS = 60
# The model gets a second try if its answer cannot be read.
MAX_ATTEMPTS = 2

AI_OFF = "AI coaching is switched off in the settings, so the AI model was not asked."
TOO_FEW = (
    f"There are fewer than {MIN_NOTES} notes of a few words or more, so there is nothing to "
    "pick from: they are all listed already."
)
BAD_ANSWER = "The AI model's answer could not be read."

# What a note was written about, to finish "Note on …".
NOTE_ABOUT = {
    "pause_intentional": "a pause you labelled intentional",
    "pause_accidental": "a pause you labelled accidental",
    "pause_false": "a pause the app detected and you said was not one",
    "split_wrong": "a pause the app detected and you said was too short to split the phrase",
    "pause_missed": "a pause you said the app missed",
    "wpm_too_high": "a WPM figure you said the app put too high",
    "wpm_too_low": "a WPM figure you said the app put too low",
    "transcript_wrong": "words you said the app got wrong",
    "coaching_useful": "a coaching correction you rated useful",
    "coaching_not_useful": "a coaching correction you rated not useful",
}

# The things feedback can be about, and the categories that belong to each.
TOPICS = {
    "missed pauses": ("pause_missed",),
    "pauses you labelled": ("pause_intentional", "pause_accidental"),
    "pauses that were not real": ("pause_false", "split_wrong"),
    "WPM figures": ("wpm_too_high", "wpm_too_low"),
    "wrong words": ("transcript_wrong",),
    "coaching corrections": ("coaching_useful", "coaching_not_useful"),
}


class SummaryUnavailable(Exception):
    """The language model could not make its pick. `message` is safe to show."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Fact:
    id: str
    text: str


@dataclass(frozen=True)
class Digest:
    """Everything the stored feedback says: the facts counted by code, and the notes."""

    feedback_count: int
    facts: tuple[Fact, ...]
    # The most recent notes, newest last, each with what it was written about.
    notes: tuple[tuple[str, str], ...]
    # Every note there is, including those too old to be listed.
    note_count: int = 0

    @property
    def notes_fingerprint(self) -> str:
        """Changes whenever the notes do, which is when a pick from them goes out of date."""
        content = json.dumps(self.notes, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()

    @property
    def candidates(self) -> tuple[int, ...]:
        """The positions of the notes that say enough to be worth picking."""
        return tuple(
            position
            for position, (_, note) in enumerate(self.notes)
            if len(note.split()) >= MIN_NOTE_WORDS
        )


@dataclass(frozen=True)
class Picked:
    """The notes the model picked, as positions in `Digest.notes`, the most telling first."""

    positions: tuple[int, ...]
    model: str
    seconds: float


# --- The facts ---------------------------------------------------------------------------


def _count(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _span(values: list[float], unit: str, digits: int = 0) -> str:
    """ "420 ms", or "between 320 and 410 ms" when the values differ."""
    low, high = f"{min(values):.{digits}f}", f"{max(values):.{digits}f}"
    return f"{low} {unit}" if low == high else f"between {low} and {high} {unit}"


def _pause_seconds(rows: list[Feedback]) -> list[float]:
    return [row.features["pause_ms"] / 1000 for row in rows if row.features.get("pause_ms")]


def build_digest(session: Session) -> Digest:
    """Reads every stored piece of feedback and states what it adds up to.

    Each fact is about one thing only, and no two facts count the same feedback. A fact
    that could be misread carries a sentence saying what it means, so that nobody who
    restates it, person or model, has to work that out.
    """
    stored = session.execute(
        select(Feedback, Analysis.role)
        .join(Analysis, Analysis.id == Feedback.analysis_id)
        .order_by(Feedback.created_at, Feedback.id)
    ).all()
    if not stored:
        return Digest(0, (), (), 0)
    rows = [row for row, _ in stored]
    by_category: dict[str, list[Feedback]] = {}
    for row in rows:
        by_category.setdefault(row.category, []).append(row)

    def of(*categories: str) -> list[Feedback]:
        return [row for category in categories for row in by_category.get(category, [])]

    texts: list[str] = []

    on_references = sum(1 for _, role in stored if role == job_queue.REFERENCE)
    recordings = len({row.recording_id for row in rows})
    total = f"{_count(len(rows), 'piece')} of feedback in all, on {_count(recordings, 'recording')}"
    texts.append(
        f"{total}: {len(rows) - on_references} on your own takes and {on_references} on "
        "reference recordings."
        if on_references
        else f"{total}."
    )

    # What the feedback is about, largest group first, so "mostly about" is never a guess.
    topics = sorted(
        ((len(of(*categories)), name) for name, categories in TOPICS.items() if of(*categories)),
        key=lambda topic: (-topic[0], topic[1]),
    )
    if len(topics) > 1:
        texts.append(
            "What it is about, largest group first: "
            + ", ".join(f"{name} ({count})" for count, name in topics)
            + "."
        )

    for label in ("intentional", "accidental"):
        labelled = of(f"pause_{label}")
        if not labelled:
            continue
        text = f"Pauses you labelled {label}: {len(labelled)}."
        lengths = _pause_seconds(labelled)
        if lengths:
            text += f" {'It' if len(labelled) == 1 else 'They'} lasted {_span(lengths, 's', 1)}."
        texts.append(f"{text} A label changes how the coaching reads a pause, not its length.")

    still_speaking, too_short_to_split = of("pause_false"), of("split_wrong")
    if still_speaking or too_short_to_split:
        both = still_speaking + too_short_to_split
        text = (
            f"Detected pauses you reported as not real pauses: {len(both)} "
            f"({len(still_speaking)} where speech carried on, {len(too_short_to_split)} too "
            "short to split the phrase)."
        )
        lengths = [row.features["pause_ms"] for row in both if row.features.get("pause_ms")]
        if lengths:
            text += f" They lasted {_span(lengths, 'ms')}."
        texts.append(text)

    missed = of("pause_missed")
    if missed:
        reasons = Counter(row.features.get("no_vote") for row in missed)
        heard = [
            row.features["silence_ms"]
            for row in missed
            if row.features.get("no_vote") is None and row.features.get("silence_ms")
        ]
        text = f"Missed pauses you reported: {len(missed)}."
        if heard:
            text += (
                f" At {len(heard)} of them the detector had heard a silence lasting "
                f"{_span(heard, 'ms')}, which was shorter than the minimum pause at the time "
                "and so was not counted as a pause."
            )
        if reasons["too_short"]:
            text += (
                f" At {reasons['too_short']} the silence was shorter than "
                f"{MIN_PAUSE.minimum:.0f} ms, which never counts as a pause."
            )
        if reasons["no_silence"]:
            text += f" At {reasons['no_silence']} the detector had heard speech straight through."
        unchecked = reasons["no_position"] + reasons["not_recorded"]
        if unchecked:
            text += f" {unchecked} could not be checked against what the detector heard."
        texts.append(text)

    too_high, too_low = of("wpm_too_high"), of("wpm_too_low")
    if too_high or too_low:
        texts.append(
            f"WPM figures you said looked wrong: {len(too_high)} too high and {len(too_low)} "
            "too low. Saying so changes no figure."
        )

    wrong_words = of("transcript_wrong")
    if wrong_words:
        corrected = sum(1 for row in wrong_words if "revision" in row.features)
        texts.append(
            f"Phrases whose words you said were wrong: {len(wrong_words)}. You corrected "
            f"{corrected} of them, and their word counts were worked out again."
        )

    useful, not_useful = of("coaching_useful"), of("coaching_not_useful")
    if useful or not_useful:
        text = (
            f"Coaching corrections you rated: {len(useful)} useful and {len(not_useful)} not "
            "useful."
        )
        # Said inside the same fact: a line of its own would read as further ratings.
        for verdict, rated in (("useful", useful), ("not useful", not_useful)):
            kinds = Counter(
                CORRECTION_KINDS.get(kind, kind.replace("_", " "))
                for row in rated
                if (kind := str(row.features.get("finding_kind") or ""))
            )
            if kinds:
                listed = ", ".join(
                    f"{about} ({count})" for about, count in kinds.most_common(MAX_KIND_FACTS)
                )
                text += f" The ones rated {verdict} were about: {listed}."
        texts.append(text)

    current = store.active(session)
    moved = [
        ADAPTIVE[name] for name, value in current.values.items() if value != ADAPTIVE[name].default
    ]
    if moved:
        texts += [
            f"{setting.label} is now {show(setting, current.values[setting.name])}; the "
            f"default is {show(setting, setting.default)}. Your reports moved it, and it "
            "applies to recordings analysed from now on."
            for setting in moved
        ]
    else:
        texts.append(
            "No setting has moved: each one is still at its default. The minimum pause is "
            f"{show(MIN_PAUSE, current.values[MIN_PAUSE.name])}."
        )
    waiting = sum(1 for row in rows if row.setting and row.used_by_version is None)
    if waiting:
        texts.append(
            f"{_count(waiting, 'report')} {'is' if waiting == 1 else 'are'} waiting to count "
            "towards a setting."
        )
    unsupported = sum(1 for row in rows if row.features.get("no_vote"))
    if unsupported:
        texts.append(
            f"{_count(unsupported, 'report')} {'was' if unsupported == 1 else 'were'} saved "
            "but can count towards no setting, because what was measured there does not "
            "support a change."
        )

    noted = [row for row in rows if row.note]
    if noted:
        on = sorted(
            (
                (sum(1 for row in noted if row.category in categories), name)
                for name, categories in TOPICS.items()
            ),
            key=lambda topic: (-topic[0], topic[1]),
        )
        listed = ", ".join(f"{name} ({count})" for count, name in on if count)
        texts.append(f"You wrote {_count(len(noted), 'note')} with your feedback, on: {listed}.")
    notes = tuple(
        (NOTE_ABOUT.get(row.category, "a piece of feedback"), row.note or "")
        for row in noted[-MAX_NOTES:]
    )

    facts = tuple(Fact(f"f{index}", text) for index, text in enumerate(texts, start=1))
    return Digest(len(rows), facts, notes, len(noted))


# --- Asking the model --------------------------------------------------------------------

SYSTEM = """You help someone who practises speaking with an app. The app measures their \
recordings. Where they think a measurement or a piece of coaching is wrong they say so, and \
sometimes add a short note. You are given those notes, numbered, each with what it was \
written about. You did not hear any recording."""

TASK = """TASK
Choose the {count} notes that, between them, best show what these notes are about.
- Most of the notes are on {most}. Choose at least one of those.
- Prefer a note that says something particular over one that says something general.
- After that, choose notes about different things when you can.
Answer in JSON with the numbers of the notes you chose, the most telling first."""


@dataclass(frozen=True)
class Prompt:
    messages: list[Message]
    schema: dict
    # The name the answer may use for each note offered: its position in `Digest.notes`.
    names: dict[str, int]


def build_prompt(digest: Digest) -> Prompt:
    """What the model is sent: the notes, numbered, and what each is about. Nothing else."""
    names = {f"n{number}": position for number, position in enumerate(digest.candidates, start=1)}
    count = min(PICKS, len(names))
    offered = [(name, *digest.notes[position]) for name, position in names.items()]
    notes = "\n".join(f'{name} (on {about}): "{note}"' for name, about, note in offered)
    # Which subject has the most notes is counted here, so the model need not count.
    most = Counter(about for _, about, _ in offered).most_common(1)[0][0]
    schema = {
        "type": "object",
        "properties": {
            "notes": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                # Only a note that exists can be named.
                "items": {"type": "string", "enum": list(names)},
            }
        },
        "required": ["notes"],
    }
    return Prompt(
        messages=[
            Message("system", SYSTEM),
            Message(
                "user",
                f"NOTES, word for word:\n{notes}\n\n{TASK.format(count=count, most=most)}",
            ),
        ],
        schema=schema,
        names=names,
    )


def read_answer(text: str, prompt: Prompt) -> tuple[int, ...] | None:
    """The positions of the notes an answer names, or None if it does not name enough.

    Each note counts once however often it is named, and a name that is not a note is
    passed over. At least two different notes are needed for the pick to say anything.
    """
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    named = answer.get("notes") if isinstance(answer, dict) else None
    if not isinstance(named, list):
        return None
    positions = [
        prompt.names[name]
        for name in dict.fromkeys(named)
        if isinstance(name, str) and name in prompt.names
    ]
    return tuple(positions[:PICKS]) if len(positions) >= 2 else None


def pick(llm: ChatModel | None, digest: Digest, check: Callable[[], None] = lambda: None) -> Picked:
    """Asks the model which notes are the most telling.

    Raises SummaryUnavailable if it gives no usable answer. There is nothing to fall back
    on and nothing is needed: every note is already listed on the screen.
    """
    if len(digest.candidates) < MIN_NOTES:
        raise SummaryUnavailable("too_few_notes", TOO_FEW)
    if llm is None:
        raise SummaryUnavailable("ai_off", AI_OFF)

    prompt = build_prompt(digest)
    seconds = 0.0
    try:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            reply = llm.complete_json(
                prompt.messages, prompt.schema, max_tokens=MAX_ANSWER_TOKENS, check=check
            )
            seconds += reply.seconds
            positions = None if reply.truncated else read_answer(reply.text, prompt)
            if positions is not None:
                return Picked(positions, llm.name, seconds)
            logger.info("attempt %d: the answer did not name enough notes", attempt)
    except LlmError as error:
        raise SummaryUnavailable(error.code, error.message) from None
    raise SummaryUnavailable("bad_answer", BAD_ANSWER)


# --- Storing and describing --------------------------------------------------------------


def to_row(digest: Digest, picked: Picked, now: datetime) -> StoredSummary:
    """The one stored pick. A new one replaces it."""
    return StoredSummary(
        id=1,
        generated_at=now,
        model=picked.model[:64],
        model_seconds=round(picked.seconds, 1),
        note_count=len(digest.notes),
        fingerprint=digest.notes_fingerprint,
        # The notes themselves, as they read when they were picked.
        picked=[
            {"about": digest.notes[position][0], "text": digest.notes[position][1]}
            for position in picked.positions
        ],
    )


def latest_job(session: Session) -> Job | None:
    return session.execute(
        select(Job)
        .where(Job.kind == job_queue.SUMMARY)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def describe(
    session: Session, now: datetime, data_dir: Path | None = None
) -> schemas.FeedbackSummary:
    """Everything the summary panel shows: the facts, the notes, the model's pick, the job."""
    digest = build_digest(session)
    stored = session.get(StoredSummary, 1)
    pick_made = None
    if stored is not None and digest.notes:
        pick_made = schemas.NotePick(
            notes=[schemas.SummaryNote(about=n["about"], text=n["text"]) for n in stored.picked],
            model=stored.model,
            model_seconds=stored.model_seconds,
            generated_at=stored.generated_at,
            note_count=stored.note_count,
            stale=stored.fingerprint != digest.notes_fingerprint,
        )

    job = latest_job(session)
    # A job is worth showing while it is under way, and after it failed until a later
    # pick has been stored.
    show_job = job is not None and (
        job.status in (job_queue.QUEUED, job_queue.RUNNING)
        or (
            job.status == job_queue.FAILED
            and (stored is None or (job.finished_at or now) > stored.generated_at)
        )
    )
    return schemas.FeedbackSummary(
        feedback_count=digest.feedback_count,
        facts=[schemas.SummaryFact(id=fact.id, text=fact.text) for fact in digest.facts],
        notes=[schemas.SummaryNote(about=about, text=note) for about, note in digest.notes],
        note_count=digest.note_count,
        pickable_notes=len(digest.candidates),
        min_notes=MIN_NOTES,
        picked=pick_made,
        job=job_queue.to_status(session, job, now, data_dir) if show_job else None,
    )
