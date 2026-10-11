"""Checks the language model's wording against what was actually measured.

The model is told to copy figures from the findings. This file does not take its word for
it: every figure with a unit, every timestamp and every "segment 4" in its answer is looked
up in the text the model was given. Anything that is not there counts as a problem.

Words the model puts in quotation marks are checked too: four or more quoted words in a row
must appear, in that order, in the transcript.

What this cannot check: whether a sentence without figures is good advice. The phrase shown
under "Practise on" is always taken from the transcript by code, never from the model's wording.
"""

import re
from dataclasses import dataclass, field

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip

# Longer spellings first, so "seconds" is not read as "s" followed by "econds".
UNITS: dict[str, str] = {
    "wpm": r"(?:wpm|words?\s*(?:per|a|/)\s*min(?:ute)?)",
    "milliseconds": r"(?:milliseconds?|ms)",
    "seconds": r"(?:seconds?|secs?|s)",
    "db": r"(?:decibels?|db)",
    "hz": r"(?:hertz|hz)",
    "semitones": r"semitones?",
    "percent": r"(?:%|percent|per\s+cent)",
}

_NUMBER = r"(?P<number>\d+(?:\.\d+)?|" + "|".join(NUMBER_WORDS) + r")"
_FIGURES = {
    unit: re.compile(rf"(?<![\w.:]){_NUMBER}[\s-]*{pattern}(?![a-z])", re.IGNORECASE)
    for unit, pattern in UNITS.items()
}
_TIMECODE = re.compile(r"(?<![\w.:])(\d{1,2}):(\d{2})(?:\.(\d))?(?![\w:])")
_SEGMENT = re.compile(r"\bseg(?:ment)?s?[\s-]*(\d+)\b", re.IGNORECASE)
_PAUSE = re.compile(r"\bpause[\s-]+(\d+)\b", re.IGNORECASE)

# Text inside "double", “curly” or 'single' quotation marks. An apostrophe inside a word
# (don't, Shelby's) neither opens nor closes a quotation.
_QUOTED = re.compile(r"\"([^\"]+)\"|“([^”]+)”|(?<!\w)'([^']+)'(?!\w)")
_NOT_A_WORD = re.compile(r"[^\w\s]|_")
# Shorter quotations are usually a single stressed word or a label, not a line of the speech.
MIN_QUOTED_WORDS = 4
# Counting aloud in a drill is not a claim about what was said.
COUNTING_WORDS = {"one", "two", "three", "four", "five", "thousand", "and", "a"}

# A quoted figure matches a measured one within this share of it, or within half of its own
# last written digit, whichever is larger: "about 220 WPM" passes for 223, "200 WPM" does not.
RELATIVE_TOLERANCE = 0.03
TIMECODE_TOLERANCE_SECONDS = 0.6
# Not a measurement: "give it 100%".
ALWAYS_ALLOWED = {("percent", 100.0)}


@dataclass(frozen=True)
class Figure:
    unit: str
    value: float
    # The spelling found in the text, for error messages.
    text: str
    # Half of the last written digit: 0.5 for "220", 0.05 for "1.6".
    half_step: float


@dataclass
class Facts:
    """Everything a piece of text may refer to."""

    figures: dict[str, list[float]] = field(default_factory=dict)
    timecodes: list[float] = field(default_factory=list)
    segment_count: int = 0
    pause_count: int = 0
    # The transcript as a list of bare words, for checking quotations.
    spoken_words: list[str] = field(default_factory=list)


def find_figures(text: str) -> list[Figure]:
    found: list[Figure] = []
    for unit, pattern in _FIGURES.items():
        for match in pattern.finditer(text):
            raw = match.group("number").lower()
            value = float(NUMBER_WORDS.get(raw, raw))
            decimals = len(raw.split(".")[1]) if "." in raw else 0
            half_step = 0.5 * 10**-decimals
            if unit == "milliseconds":
                unit_name, value, half_step = "seconds", value / 1000, half_step / 1000
            else:
                unit_name = unit
            found.append(Figure(unit_name, value, match.group(0).strip(), half_step))
    return found


def find_timecodes(text: str) -> list[tuple[float, str]]:
    return [
        (int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3) or 0) / 10, m.group(0))
        for m in _TIMECODE.finditer(text)
    ]


def bare_words(text: str) -> list[str]:
    """Lower-case words with punctuation removed, so quotations compare on words alone."""
    return _NOT_A_WORD.sub(" ", text.lower()).split()


def _contains(words: list[str], run: list[str]) -> bool:
    return any(words[i : i + len(run)] == run for i in range(len(words) - len(run) + 1))


def misquotes(text: str, spoken_words: list[str]) -> list[str]:
    """Quotations in `text` that are not in the transcript."""
    wrong: list[str] = []
    for match in _QUOTED.finditer(text):
        quoted = next(group for group in match.groups() if group)
        words = bare_words(quoted)
        if len(words) < MIN_QUOTED_WORDS or all(word in COUNTING_WORDS for word in words):
            continue
        if not _contains(spoken_words, words):
            wrong.append(quoted)
    return wrong


def collect_facts(
    text: str, *, segment_count: int, pause_count: int, transcript: str | None = None
) -> Facts:
    """Reads the allowed figures out of the text the model was given."""
    facts = Facts(
        segment_count=segment_count,
        pause_count=pause_count,
        spoken_words=bare_words(transcript or ""),
    )
    for figure in find_figures(text):
        facts.figures.setdefault(figure.unit, []).append(figure.value)
    facts.timecodes = [seconds for seconds, _ in find_timecodes(text)]
    return facts


def _is_known(figure: Figure, facts: Facts) -> bool:
    if (figure.unit, figure.value) in ALWAYS_ALLOWED:
        return True
    return any(
        abs(figure.value - known) <= max(RELATIVE_TOLERANCE * known, figure.half_step)
        for known in facts.figures.get(figure.unit, [])
    )


def problems_in(text: str, facts: Facts) -> list[str]:
    """Everything in `text` that does not match the facts. Empty when the text is clean."""
    problems = [
        f"“{figure.text}” is not one of the measured figures"
        for figure in find_figures(text)
        if not _is_known(figure, facts)
    ]
    problems += [
        f"“{written}” is not a time that appears in the measurements"
        for seconds, written in find_timecodes(text)
        if not any(abs(seconds - known) <= TIMECODE_TOLERANCE_SECONDS for known in facts.timecodes)
    ]
    problems += [
        f"there is no segment {match.group(1)}"
        for match in _SEGMENT.finditer(text)
        if not 1 <= int(match.group(1)) <= facts.segment_count
    ]
    problems += [
        f"there is no pause {match.group(1)}"
        for match in _PAUSE.finditer(text)
        if not 1 <= int(match.group(1)) <= facts.pause_count
    ]
    problems += [
        f"the quoted words “{quoted}” are not in the transcript"
        for quoted in misquotes(text, facts.spoken_words)
    ]
    return problems
