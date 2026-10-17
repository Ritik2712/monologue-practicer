"""Writes stored analyses out as Markdown, to read, keep or hand to someone else.

    stored results -> one text document

Nothing is measured or judged here. Every figure in an export is one the result already
holds, written out in full: the settings it was measured with, each phrase with both its
paces and the pauses inside it, each pause, where the voice sat, the coaching with the
findings and the bands behind it, the feedback given, and for a take of a monologue the
comparison with its original. An export changes nothing that is stored.

The first half of this file turns results into text and knows nothing about the database.
The second half gathers which results go into a document.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import feedback, job_queue, monologues, revisions, schemas, stretches
from app.coaching.findings import build_findings, pause_place, timecode
from app.coaching.settings import DEFAULT_COACHING_SETTINGS
from app.comparison.compare import compare
from app.comparison.settings import DEFAULT_COMPARISON_SETTINGS
from app.models import Analysis, Job

MISSING = "—"
MEDIA_TYPE = "text/markdown; charset=utf-8"

KIND_REFERENCE = "The original recording of a monologue"
KIND_FREE_TAKE = "A General Practice take (no original to compare with)"

REVISION_REASONS = {
    "transcript_corrected": "its transcript was corrected",
    "reanalysed": "analysed again",
}
PAUSE_STATUS = {
    "both": "in both",
    "reference_only": "only in the original",
    "take_only": "only in the take",
    "unplaced": "could not be located in the take",
}
PACE_NOTE = (
    "Delivery pace is the phrase's words ÷ its whole length, the pauses inside it counted. "
    "Speaking speed is its words ÷ the time spent speaking in it. A pause inside a phrase "
    "is shown in the text as ‖ with its length."
)
BANDS_NOTE = (
    "An original gets no coaching. These are the facts a coaching would start from, worked "
    "out now with the app's bands as they are today, so that the bands can be judged "
    "against a real performance. They are written as if to the speaker, and nothing here "
    "is stored with the result."
)
OLDER_PACE_NOTE = (
    "This result was made when every pause ended a phrase, so no phrase holds a pause and "
    "each has one pace: its words ÷ its length."
)


# --- Small pieces of text ----------------------------------------------------------------


def number(value: float | None, digits: int = 1) -> str:
    """A figure as written in a table. A missing one is a dash, never a zero."""
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return "yes" if value else "no"
    rounded = round(float(value), digits)
    return f"{rounded:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{rounded:.0f}"


def cell(text: object) -> str:
    """Text made safe for one cell of a Markdown table."""
    shown = MISSING if text is None or text == "" else str(text)
    return shown.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def table(headers: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    lines += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return lines


def moment(when: datetime) -> str:
    return when.strftime("%Y-%m-%d %H:%M UTC")


def slug(text: str | None, fallback: str) -> str:
    """A file-name-safe version of a title: plain letters, digits and hyphens."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", plain.lower())
    return "-".join(words)[:48].strip("-") or fallback


# --- One analysis ------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One analysis, with what belongs beside it in an export."""

    result: schemas.AnalysisResult
    kind: str
    filename: str | None = None
    feedback: list[schemas.FeedbackItem] = field(default_factory=list)
    comparison: schemas.Comparison | None = None


def _phrase_text(result: schemas.AnalysisResult, segment: schemas.SpeechSegment) -> str:
    """A phrase's words, with each pause inside it marked where it fell."""
    runs = [s for s in stretches.stretches_of(result) if s.segment_id == segment.id]
    if len(runs) < 2:
        return segment.transcript or ""
    inside = {pause.index: pause for pause in stretches.pauses_inside(result, segment.id)}
    said: dict[int, list[str]] = {}
    for word in result.words:
        index = stretches.stretch_index_of(result, word)
        if index is not None:
            said.setdefault(index, []).append(word.text)
    pieces: list[str] = []
    for run in runs:
        pieces.append(" ".join(said.get(run.index, [])))
        pause = inside.get(run.index)
        if pause is not None and run is not runs[-1]:
            pieces.append(f"‖{number(pause.duration_seconds, 2)} s‖")
    return " ".join(piece for piece in pieces if piece) or (segment.transcript or "")


def _voice_cell(placement: schemas.VoicePlacement | None) -> str:
    if placement is None:
        return MISSING
    estimate = ", estimate" if placement.quality == "estimated" else ""
    return f"{number(placement.value_hz, 0)} Hz {placement.band} {placement.percent}%{estimate}"


def _header(entry: Entry) -> list[str]:
    result = entry.result
    of = len(result.revisions) or 1
    reason = REVISION_REASONS.get(result.revision_reason or "", "the first analysis")
    language = result.language.code + (
        f" ({result.language.source})" if result.language.source != "none" else ""
    )
    rows: list[list[object]] = [
        ["What this is", entry.kind],
        ["Analysis ID", result.analysis_id],
        ["Analysed", moment(result.created_at)],
        ["Revision", f"{result.revision} of {of} ({reason})"],
        ["File", entry.filename],
        ["Profile", result.profile],
        ["Language", language],
        ["Length", f"{number(result.duration_seconds, 2)} s"],
        ["Recording kept", "yes" if result.audio_retained else "no"],
    ]
    if result.voice_range is not None:
        rows.append(["Voice goal", result.voice_range.goal])
    return table(["", ""], rows)


def _measurements(result: schemas.AnalysisResult) -> list[str]:
    rows = []
    for name, metric in result.metrics.model_dump(by_alias=True).items():
        if metric is None:
            continue
        digits = 0 if metric["unit"] in ("count", "words") else 3
        rows.append([name, number(metric["value"], digits), metric["unit"], metric["quality"]])
    return table(["Measurement", "Value", "Unit", "Quality"], rows)


def _phrases(result: schemas.AnalysisResult) -> list[str]:
    if not result.segments:
        return ["No speech was detected, so there are no phrases."]
    with_delivery = stretches.has_delivery_pace(result)
    headers = ["#", "Start", "End", "Length s", "Words"]
    headers += (
        ["Speaking s", "Pauses inside", "Pause s", "Delivery WPM", "Speaking WPM"]
        if with_delivery
        else ["WPM"]
    )
    headers += ["Vs typical", "Trusted", "Flags", "Loudness Δ dB", "Pitch Δ semitones"]
    with_voice = any(segment.voice for segment in result.segments)
    if with_voice:
        headers += ["Pitch", "Resonance", "Voice"]
    headers.append("What was said")

    rows = []
    for segment in result.segments:
        row: list[object] = [
            segment.index + 1,
            timecode(segment.start_seconds),
            timecode(segment.end_seconds),
            number(segment.end_seconds - segment.start_seconds, 2),
            segment.word_count,
        ]
        if with_delivery:
            row += [
                number(segment.speech_active_seconds, 2),
                segment.pause_count,
                number(segment.pause_seconds, 2),
                number(segment.delivery_wpm),
                number(segment.segment_wpm),
            ]
        else:
            row.append(number(segment.segment_wpm))
        row += [
            segment.pace_vs_typical,
            "yes" if segment.reliable else "no",
            ", ".join(segment.flags),
            number(segment.energy_delta_db),
            number(segment.pitch_delta_semitones),
        ]
        if with_voice:
            voice = segment.voice
            row += [
                _voice_cell(voice.pitch if voice else None),
                _voice_cell(voice.resonance if voice else None),
                voice.marker if voice else None,
            ]
        row.append(_phrase_text(result, segment))
        rows.append(row)
    return [PACE_NOTE if with_delivery else OLDER_PACE_NOTE, "", *table(headers, rows)]


def _pauses(entry: Entry) -> list[str]:
    result = entry.result
    if not result.pauses:
        return ["No pause was detected."]
    said: dict[int, list[str]] = {}
    for word in result.words:
        index = stretches.stretch_index_of(result, word)
        if index is not None:
            said.setdefault(index, []).append(word.text)
    given = {
        item.target_id: item.category.removeprefix("pause_").replace("_", " ")
        for item in entry.feedback
        if item.target_kind == "pause"
    }
    rows = [
        [
            pause.index + 1,
            timecode(pause.start_seconds),
            number(pause.duration_seconds, 3),
            pause.significance,
            pause_place(result, pause),
            " ".join(said.get(pause.index, [])[-5:]),
            given.get(pause.id),
        ]
        for pause in result.pauses
    ]
    return table(["#", "At", "Length s", "Kind", "Where", "After the words", "Feedback"], rows)


def _voice(result: schemas.AnalysisResult) -> list[str]:
    voice = result.voice_range
    if voice is None:
        return []
    counts = voice.phrases
    lines = [
        *table(
            ["", ""],
            [
                ["Pitch", _voice_cell(voice.pitch)],
                ["Resonance", _voice_cell(voice.resonance)],
                ["Together", voice.marker],
                ["Goal", voice.goal],
                [
                    "Phrases",
                    (
                        f"{counts.lower} lower, {counts.neutral} neutral, "
                        f"{counts.higher} higher, {counts.mixed} mixed, "
                        f"{counts.unmeasured} not measured"
                    ),
                ],
                ["Note on resonance", voice.resonance_note],
            ],
        ),
        "",
        "Ranges used: "
        + ", ".join(f"{name} = {number(value)}" for name, value in voice.bands.items()),
    ]
    return lines


def _coaching(result: schemas.AnalysisResult) -> list[str]:
    coaching = result.coaching
    if coaching is None:
        return ["This result has no coaching."]
    writer = {"ai": "the AI model", "rules": "fixed rules", "none": "nobody"}[coaching.source]
    if coaching.model:
        writer += f" ({coaching.model}"
        writer += f", {number(coaching.model_seconds)} s)" if coaching.model_seconds else ")"
    lines = [f"Written by {writer} on {moment(coaching.generated_at)}."]
    if coaching.notice:
        lines.append(f"Notice ({coaching.notice.code}): {coaching.notice.message}")
    lines += ["", "**The bands behind the wording**", ""]
    lines += table(
        ["Band", "Value"],
        [
            [name, number(value, 3) if isinstance(value, (int, float)) else value]
            for name, value in coaching.settings.items()
        ],
    )
    if coaching.labels_used:
        lines += [
            "",
            "Pause labels taken into account: "
            + ", ".join(f"{pause} = {label}" for pause, label in coaching.labels_used.items()),
        ]
    if coaching.summary:
        lines += ["", "**Delivery summary**", ""]
        lines += [f"- **{line.label}:** {line.text}" for line in coaching.summary]
    if coaching.findings:
        lines += ["", "**Findings** (every fact the coaching rests on, written by code)", ""]
        lines += table(
            ["ID", "Kind", "Level", "Role", "Statement"],
            [[f.id, f.kind, f.level, f.role, f.statement] for f in coaching.findings],
        )
    kinds = {finding.id: finding.kind for finding in coaching.findings}
    lines += ["", "**Corrections**", ""]
    if not coaching.corrections:
        lines.append("None.")
    for position, correction in enumerate(coaching.corrections, start=1):
        about = kinds.get(correction.finding_id, "?")
        lines += [
            f"{position}. **{correction.title}** (finding {correction.finding_id}, {about})",
            f"   - Why: {correction.why}",
            f"   - Drill: {correction.drill}",
        ]
        if correction.practise:
            lines.append(f"   - Practise on: {correction.practise.label}")
    if coaching.working:
        lines += ["", "**What is already working**", ""]
        lines += [f"- ({item.finding_id}) {item.note}" for item in coaching.working]
    if coaching.next_take:
        lines += ["", "**Targets for the next take**", ""]
        lines += [f"- {target}" for target in coaching.next_take]
    if coaching.caveats:
        lines += ["", "**Uncertain or not measured**", ""]
        lines += [f"- {caveat}" for caveat in coaching.caveats]
    return lines


def _bands_reading(result: schemas.AnalysisResult) -> list[str]:
    """How today's coaching bands read a recording that has no coaching of its own."""
    found = build_findings(result, DEFAULT_COACHING_SETTINGS).findings
    if not found:
        return []
    bands = DEFAULT_COACHING_SETTINGS.to_dict()
    return [
        BANDS_NOTE,
        "",
        *table(
            ["Kind", "Level", "Statement"],
            [[finding.kind, finding.level, finding.statement] for finding in found],
        ),
        "",
        "Bands used: "
        + ", ".join(
            f"{name} = {number(value, 3)}"
            for name, value in bands.items()
            if isinstance(value, (int, float))
        ),
    ]


def _feedback(items: list[schemas.FeedbackItem]) -> list[str]:
    return table(
        ["About", "What was said", "Note", "What it does"],
        [
            [
                item.target_id or "the whole recording",
                item.category.replace("_", " "),
                item.note,
                item.message,
            ]
            for item in items
        ],
    )


def _comparison(comparison: schemas.Comparison) -> list[str]:
    lines = [comparison.alignment.note]
    if comparison.settings_note:
        lines += ["", f"Note: {comparison.settings_note}"]
    lines += ["", "**The biggest differences**", ""]
    lines += [f"- {difference.statement}" for difference in comparison.differences] or [
        "None large enough to list."
    ]
    lines += ["", "**The recordings as wholes**", ""]
    lines += table(
        ["Measurement", "Take", "Original", "Difference", "Unit", "Estimate"],
        [
            [
                row.label,
                number(row.take, row.digits),
                number(row.reference, row.digits),
                number(row.difference, row.digits),
                row.unit,
                "yes" if row.estimated else "",
            ]
            for row in comparison.metrics
        ],
    )
    if comparison.pauses:
        lines += ["", "**Pause by pause**", ""]
        lines += table(
            ["After the words", "Where", "Original s", "Take s", "Difference s"],
            [
                [
                    pause.after_words,
                    PAUSE_STATUS[pause.status],
                    number(pause.reference.duration_seconds, 2) if pause.reference else None,
                    number(pause.take.duration_seconds, 2) if pause.take else None,
                    number(pause.difference_seconds, 2),
                ]
                for pause in comparison.pauses
            ],
        )
    if comparison.phrases:
        lines += ["", "**Phrase by phrase** (delivery pace over the same words)", ""]
        lines += table(
            ["Phrase of the original", "Words found", "Original WPM", "Take WPM", "Difference"],
            [
                [
                    phrase.text,
                    f"{round(phrase.coverage * 100)}%",
                    number(phrase.reference_wpm),
                    number(phrase.take_wpm),
                    f"{round(phrase.difference_ratio * 100):+d}%"
                    if phrase.difference_ratio is not None
                    else None,
                ]
                for phrase in comparison.phrases
            ],
        )
    return lines


def analysis_markdown(entry: Entry, title: str, level: int = 1) -> str:
    """One analysis as Markdown. `level` is how deep its own heading sits in the document."""
    result = entry.result
    top, sub = "#" * level, "#" * (level + 1)

    def part(heading: str, body: list[str]) -> list[str]:
        return ["", f"{sub} {heading}", "", *body] if body else []

    lines = [f"{top} {title}", "", *_header(entry)]
    if result.warnings:
        lines += part(
            "Read these before trusting the numbers",
            [f"- ({warning.code}) {warning.message}" for warning in result.warnings],
        )
    lines += part(
        "Settings it was measured with",
        table(["Setting", "Value"], [[k, number(v, 3)] for k, v in result.settings.items()]),
    )
    lines += part("Measurements", _measurements(result))
    lines += part("Phrases", _phrases(result))
    lines += part("Pauses", _pauses(entry))
    lines += part("Where the voice sits", _voice(result))
    if result.emphasis_candidates:
        lines += part(
            "Words that stood out",
            [
                ", ".join(
                    f"“{word.text}” at {timecode(word.start_seconds)} ({' and '.join(word.reasons)})"
                    for word in result.emphasis_candidates
                )
            ],
        )
    if result.hesitations:
        lines += part(
            "Hesitation sounds",
            [", ".join(f"“{h.text}” at {timecode(h.start_seconds)}" for h in result.hesitations)],
        )
    if result.transcript:
        lines += part("Transcript", [result.transcript])
    if result.role != job_queue.REFERENCE:
        lines += part("Coaching", _coaching(result))
    else:
        lines += part("How the app's bands read this recording", _bands_reading(result))
    if entry.feedback:
        lines += part("Feedback given on this result", _feedback(entry.feedback))
    if entry.comparison is not None:
        lines += part("Against the original", _comparison(entry.comparison))
    return "\n".join(lines) + "\n"


# --- Gathering what goes into a document ---------------------------------------------------


def _latest(analyses: list[Analysis]) -> list[Analysis]:
    """One result per recording, its newest revision, in the order the recordings were made."""
    newest: dict[str, Analysis] = {}
    first_made: dict[str, datetime] = {}
    for analysis in sorted(analyses, key=lambda a: (a.revision, a.created_at, a.id)):
        root = job_queue.recording_root(analysis)
        newest[root] = analysis
        first_made.setdefault(root, analysis.created_at)
    return sorted(newest.values(), key=lambda a: first_made[job_queue.recording_root(a)])


def _result(session: Session, analysis: Analysis) -> schemas.AnalysisResult:
    result = schemas.AnalysisResult.model_validate(analysis.result)
    result.audio_retained = analysis.audio_path is not None
    if analysis.coaching:
        result.coaching = schemas.Coaching.model_validate(analysis.coaching)
    result.revisions = revisions.revision_infos(session, analysis)
    result.monologue_id = analysis.monologue_id
    return result


def _reference_of(session: Session, monologue_id: str | None) -> Analysis | None:
    """The newest revision of a monologue's original, which is what takes are compared with."""
    if monologue_id is None:
        return None
    found = monologues.reference_revisions(session, monologue_id)
    return found[-1] if found else None


def entry_for(session: Session, analysis: Analysis) -> Entry:
    """An analysis with its feedback and, for a take of a monologue, its comparison."""
    result = _result(session, analysis)
    reference = (
        _reference_of(session, analysis.monologue_id) if analysis.role == job_queue.TAKE else None
    )
    comparison = None
    if reference is not None:
        comparison = compare(
            schemas.AnalysisBody.model_validate(analysis.result),
            schemas.AnalysisBody.model_validate(reference.result),
            DEFAULT_COMPARISON_SETTINGS,
            take_id=analysis.id,
            reference_id=reference.id,
            reference_title=reference.title,
        )
    if analysis.role == job_queue.REFERENCE:
        kind = KIND_REFERENCE
    elif reference is not None:
        kind = f"A take of the monologue “{reference.title or 'Monologue'}”"
    else:
        kind = KIND_FREE_TAKE
    filename = session.execute(
        select(Job.original_filename).where(Job.id == analysis.job_id)
    ).scalar_one_or_none()
    return Entry(
        result=result,
        kind=kind,
        filename=filename,
        feedback=feedback.list_items(session, analysis),
        comparison=comparison,
    )


def _take_title(position: int, analysis: Analysis) -> str:
    return f"Take {position}, analysed {moment(analysis.created_at)}"


def export_analysis(session: Session, analysis: Analysis) -> tuple[str, str]:
    """One analysis as a document of its own. Returns the file name and the text."""
    entry = entry_for(session, analysis)
    if analysis.role == job_queue.REFERENCE:
        title = f"{analysis.title or 'Monologue'}: the original"
        name = slug(analysis.title, "original")
    else:
        title = f"Take, analysed {moment(analysis.created_at)}"
        name = "take"
    stamp = analysis.created_at.strftime("%Y-%m-%d")
    return (
        f"monologue-coach-{name}-{stamp}-{analysis.id[:8]}.md",
        analysis_markdown(entry, title),
    )


def _monologue_section(session: Session, monologue_id: str, level: int) -> list[str]:
    reference = _reference_of(session, monologue_id)
    if reference is None:
        return []
    takes = _latest(
        list(
            session.execute(
                select(Analysis).where(
                    Analysis.role == job_queue.TAKE, Analysis.monologue_id == monologue_id
                )
            ).scalars()
        )
    )
    title = reference.title or "Monologue"
    count = f"{len(takes)} {'take' if len(takes) == 1 else 'takes'}"
    parts = [
        f"{'#' * level} Monologue: {title}",
        "",
        f"Its original recording, and {count} recorded for it, oldest first.",
        "",
        analysis_markdown(entry_for(session, reference), "The original", level + 1),
    ]
    for position, take in enumerate(takes, start=1):
        parts.append(
            analysis_markdown(entry_for(session, take), _take_title(position, take), level + 1)
        )
    return parts


def export_monologue(session: Session, monologue_id: str, now: datetime) -> tuple[str, str]:
    """A monologue's original and every take recorded for it."""
    reference = _reference_of(session, monologue_id)
    title = reference.title if reference else None
    text = "\n".join([_preamble(now), *_monologue_section(session, monologue_id, 1)])
    return f"monologue-coach-{slug(title, 'monologue')}-{now:%Y-%m-%d}.md", text


def _general_section(session: Session, level: int) -> list[str]:
    takes = _latest(
        list(
            session.execute(
                select(Analysis).where(
                    Analysis.role == job_queue.TAKE, Analysis.monologue_id.is_(None)
                )
            ).scalars()
        )
    )
    if not takes:
        return []
    count = f"{len(takes)} {'take' if len(takes) == 1 else 'takes'}"
    parts = [
        f"{'#' * level} General Practice",
        "",
        f"{count} that belong to no monologue, oldest first.",
        "",
    ]
    for position, take in enumerate(takes, start=1):
        parts.append(
            analysis_markdown(entry_for(session, take), _take_title(position, take), level + 1)
        )
    return parts


def _preamble(now: datetime) -> str:
    return (
        f"Exported from Monologue Coach on {moment(now)}. Each recording is given in its "
        "newest revision. Every figure was worked out by the app's own code from the "
        "recording; only the wording of coaching marked as written by the AI model comes "
        "from a language model. A dash means a value was not measured, never zero.\n"
    )


def export_general(session: Session, now: datetime) -> tuple[str, str]:
    """Every take that belongs to no monologue."""
    body = _general_section(session, 1) or ["# General Practice", "", "No takes are stored."]
    return f"monologue-coach-general-practice-{now:%Y-%m-%d}.md", "\n".join([_preamble(now), *body])


def export_everything(session: Session, now: datetime) -> tuple[str, str]:
    """Every monologue with its takes, then the General Practice takes."""
    listed = monologues.list_monologues(session).items
    parts = ["# Monologue Coach: every analysis", "", _preamble(now)]
    if listed:
        parts += ["Monologues in this export:", ""]
        parts += [
            f"- {item.title} ({number(item.duration_seconds, 1)} s, "
            f"{item.take_count} {'take' if item.take_count == 1 else 'takes'})"
            for item in listed
        ]
        parts.append("")
    # Oldest monologue first, so the document reads in the order the work was done.
    for item in sorted(listed, key=lambda item: item.created_at):
        parts += _monologue_section(session, item.monologue_id, 2)
    general = _general_section(session, 2)
    parts += general
    if not listed and not general:
        parts.append("Nothing is stored yet.")
    return f"monologue-coach-all-{now:%Y-%m-%d}.md", "\n".join(parts)
