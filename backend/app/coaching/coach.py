"""Produces the coaching for one analysed recording.

    measurements -> findings -> language model -> checks -> coaching
                                     │ unavailable, or its answer fails the checks
                                     └──────────▶ templates -> coaching

The measurements are finished before this runs and are never changed by it. Whatever happens
here, a result still gets saved: at worst with template coaching and a note saying why.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app import schemas
from app.coaching import rules
from app.coaching.findings import (
    FindingSet,
    build_findings,
    known_labels,
    profile_wants,
    segment_evidence,
)
from app.coaching.grounding import Facts, collect_facts, problems_in
from app.coaching.prompt import MAX_ANSWER_TOKENS, Prompt, build_prompt
from app.coaching.settings import DEFAULT_COACHING_SETTINGS, CoachingSettings
from app.llm import STATUS_MESSAGES, ChatModel, LlmError, Message

logger = logging.getLogger("app.coaching")

# The model gets one chance to fix an answer that failed the checks.
MAX_ATTEMPTS = 2
MAX_TITLE_CHARACTERS = 120
MAX_TEXT_CHARACTERS = 700

NOT_COACHABLE = {
    "no_speech": "No speech was detected, so there is nothing to coach on.",
    "very_short": (
        "The recording is too short to coach on. Record at least ten seconds of speech."
    ),
}
NOTHING_TO_CORRECT = (
    "Nothing that was measured works against this profile, so there are no corrections."
)
NOTHING_STANDS_OUT = (
    "Nothing that was measured stands out as a problem, so there are no corrections. Choose "
    "a delivery profile for coaching aimed at a particular style."
)
AI_OFF = "AI coaching is switched off in the settings."
NOT_ASKED = "The AI model has not been asked to word this result yet."
BAD_ANSWER = "The AI model's answer could not be read."
UNGROUNDED = "The AI model's answer quoted figures that were not measured, so none of it was used."
SHORTENED_CAVEAT = (
    "The recording is long, so the AI model was shown only the opening words of each phrase."
)


class CoachingUnavailable(Exception):
    """The language model could not write coaching, and a template answer was not wanted."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Checked:
    """A model answer after the checks: what survived, and what was wrong with the rest."""

    corrections: list[schemas.Correction]
    working: list[schemas.Strength]
    problems: list[str]
    removed: int


class Coach:
    def __init__(
        self, llm: ChatModel | None, settings: CoachingSettings = DEFAULT_COACHING_SETTINGS
    ) -> None:
        self.llm = llm
        self.settings = settings

    @property
    def model_name(self) -> str | None:
        return self.llm.name if self.llm else None

    def status(self) -> str:
        """Whether AI coaching could be written right now."""
        return self.llm.status() if self.llm else "off"

    def generate(
        self,
        body: schemas.AnalysisBody,
        *,
        now: datetime,
        check: Callable[[], None] = lambda: None,
        require_model: bool = False,
        settings: CoachingSettings | None = None,
        labels: dict[str, str] | None = None,
        use_model: bool = True,
    ) -> schemas.Coaching:
        """Coaching for a measured recording.

        Always returns something usable, unless `require_model` is set: then anything short
        of an answer from the language model raises CoachingUnavailable instead.

        `settings` replaces this coach's own bands for one call, which is how the user's
        calibration reaches the coaching. `labels` are the user's labels on pauses.
        `use_model=False` writes from the templates without asking the language model.
        """
        coaching = self._generate(
            body, now, check, settings or self.settings, known_labels(body, labels), use_model
        )
        if require_model and coaching.source != "ai":
            notice = coaching.notice
            raise CoachingUnavailable(
                notice.code if notice else "unavailable",
                notice.message if notice else "AI coaching could not be written.",
            )
        return coaching

    def _generate(
        self,
        body: schemas.AnalysisBody,
        now: datetime,
        check: Callable[[], None],
        settings: CoachingSettings,
        labels: dict[str, str],
        use_model: bool,
    ) -> schemas.Coaching:
        finding_set = build_findings(body, settings, labels)
        wants = profile_wants(body.profile)

        def result(source: str, **fields) -> schemas.Coaching:
            return schemas.Coaching(
                source=source,
                summary=finding_set.summary,
                findings=finding_set.findings,
                settings=settings.to_dict(),
                labels_used=labels,
                generated_at=now,
                **{"caveats": finding_set.caveats, **fields},
            )

        codes = {warning.code for warning in body.warnings}
        for code, message in NOT_COACHABLE.items():
            if code in codes or (code == "no_speech" and not body.segments):
                return result(
                    "none",
                    notice=schemas.CoachingNotice(code=code, message=message),
                    corrections=[],
                    working=[],
                    next_take=[],
                )

        plan = rules.plan(body, finding_set, wants, settings)

        def from_rules(code: str, message: str) -> schemas.Coaching:
            return result(
                "rules",
                notice=schemas.CoachingNotice(code=code, message=message),
                corrections=plan.corrections,
                working=plan.working,
                next_take=plan.next_take,
            )

        if not finding_set.issues:
            return from_rules(
                "nothing_to_correct",
                NOTHING_STANDS_OUT if body.profile == "custom" else NOTHING_TO_CORRECT,
            )
        if not use_model:
            return from_rules("not_asked", NOT_ASKED)
        if self.llm is None:
            return from_rules("ai_off", AI_OFF)

        prompt = build_prompt(
            body,
            finding_set,
            wants,
            settings,
            context_tokens=self.llm.context_tokens,
            labels=labels,
        )
        try:
            checked, seconds = self._ask(body, finding_set, prompt, check)
        except LlmError as error:
            logger.info("language model not used: %s", error.code)
            return from_rules(error.code, error.message)

        notice = None
        if checked.removed:
            notice = schemas.CoachingNotice(
                code="items_removed",
                message=(
                    f"{checked.removed} of the AI model's suggestions "
                    f"{'was' if checked.removed == 1 else 'were'} left out for failing the "
                    "checks against the measurements."
                ),
            )
        return result(
            "ai",
            model=self.llm.name,
            notice=notice,
            corrections=checked.corrections,
            # The model sometimes skips these; the templates never do.
            working=checked.working or plan.working,
            # Targets are always written by template, so each one can be checked next time.
            next_take=rules.targets_for(
                [c.finding_id for c in checked.corrections],
                body,
                finding_set,
                wants,
                settings,
            ),
            caveats=finding_set.caveats + ([SHORTENED_CAVEAT] if prompt.shortened else []),
            model_seconds=round(seconds, 1),
        )

    def _ask(
        self,
        body: schemas.AnalysisBody,
        finding_set: FindingSet,
        prompt: Prompt,
        check: Callable[[], None],
    ) -> tuple[Checked, float]:
        """Asks the model, checks the answer, and lets it correct itself once."""
        facts = collect_facts(
            prompt.facts_text,
            segment_count=len(body.segments),
            pause_count=len(body.pauses),
            transcript=" ".join(segment.transcript or "" for segment in body.segments),
        )
        messages = prompt.messages
        best: Checked | None = None
        seconds = 0.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            reply = self.llm.complete_json(
                messages, prompt.schema, max_tokens=MAX_ANSWER_TOKENS, check=check
            )
            seconds += reply.seconds
            answer = None if reply.truncated else _parse(reply.text)
            if answer is None:
                logger.info("attempt %d: the answer was cut off or not valid JSON", attempt)
                messages = prompt.messages
                continue
            checked = _check_answer(answer, body, finding_set, prompt, facts)
            if best is None or len(checked.corrections) >= len(best.corrections):
                best = checked
            if not checked.problems:
                break
            logger.info("attempt %d: %d problems in the answer", attempt, len(checked.problems))
            messages = [
                *prompt.messages,
                Message("assistant", reply.text),
                Message("user", _correction_request(checked.problems)),
            ]
        if best is None:
            raise LlmError("bad_answer", BAD_ANSWER)
        if not best.corrections:
            raise LlmError("ungrounded", UNGROUNDED)
        return best, seconds


def _parse(text: str) -> dict | None:
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _clean(value: object) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def _text_problems(text: str, facts: Facts, limit: int) -> list[str]:
    if not text:
        return ["a part of the answer was left empty"]
    if len(text) > limit:
        return ["a part of the answer was far too long"]
    return problems_in(text, facts)


def _check_answer(
    answer: dict,
    body: schemas.AnalysisBody,
    finding_set: FindingSet,
    prompt: Prompt,
    facts: Facts,
) -> Checked:
    """Keeps the parts of the model's answer that match the measurements."""
    segments = {segment.id: segment for segment in body.segments}
    anchor = rules.anchor_segment(body)
    problems: list[str] = []
    removed = 0

    corrections: list[schemas.Correction] = []
    used: set[str] = set()
    for item in _items(answer.get("corrections"))[: rules.MAX_CORRECTIONS]:
        finding_id = item.get("finding")
        title, why, drill = (_clean(item.get(key)) for key in ("title", "why", "drill"))
        found_problems = (
            _text_problems(title, facts, MAX_TITLE_CHARACTERS)
            + _text_problems(why, facts, MAX_TEXT_CHARACTERS)
            + _text_problems(drill, facts, MAX_TEXT_CHARACTERS)
        )
        if finding_id not in prompt.issue_ids:
            found_problems.append("a correction named a finding that is not one of the issues")
        elif finding_id in used:
            found_problems.append("two corrections were about the same finding")
        if found_problems:
            problems += found_problems
            removed += 1
            continue
        used.add(finding_id)
        # A finding about one phrase is practised on that phrase, whatever the model chose.
        own_segment = finding_set.details[finding_id].data.get("segment")
        segment = segments.get(own_segment or item.get("segment")) or anchor
        corrections.append(
            schemas.Correction(
                finding_id=finding_id,
                title=title.rstrip("."),
                why=why,
                drill=drill,
                practise=segment_evidence(segment) if segment else None,
            )
        )

    working: list[schemas.Strength] = []
    for item in _items(answer.get("working"))[: rules.MAX_WORKING]:
        finding_id, note = item.get("finding"), _clean(item.get("note"))
        found_problems = _text_problems(note, facts, MAX_TEXT_CHARACTERS)
        if finding_id not in prompt.strength_ids or finding_id in {w.finding_id for w in working}:
            found_problems.append("“working” named a finding that is not one of the strengths")
        if found_problems:
            problems += found_problems
            removed += 1
            continue
        working.append(schemas.Strength(finding_id=finding_id, note=note))

    return Checked(corrections, working, problems, removed)


def _items(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _correction_request(problems: list[str]) -> str:
    listed = "\n".join(f"- {problem}" for problem in dict.fromkeys(problems))
    return (
        "Parts of that answer cannot be used:\n"
        f"{listed}\n"
        "Write the whole answer again in the same JSON shape. Use only figures that are "
        "written in the findings or the bands, or describe the change in words with no figure. "
        "Copy quoted words exactly from one transcript line."
    )


def status_message(status: str, model: str | None) -> str:
    """Why AI coaching is not available, for the health check."""
    if status == "model_missing" and model:
        return f"The AI model '{model}' is not installed in Ollama."
    return STATUS_MESSAGES.get(status, "")
