"""Speech to text with word-level timestamps, using a local faster-whisper model."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from app.pipeline.errors import PipelineError
from app.pipeline.segmentation import Word

LanguageHint = Literal["auto", "en", "hi", "hinglish"]

# Whisper's own ladder: a first attempt with no randomness, then retries with more.
RETRY_TEMPERATURES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
# A window whose text compresses more than this (it repeats itself that much) is retried.
REPETITION_THRESHOLD = 3.0

# A "word" longer than this, or with one character repeated this many times in a row, is the
# recogniser stuck in a loop rather than something that was said.
GARBLED_LENGTH = 40
GARBLED_REPEAT = re.compile(r"(.)\1{7,}")


def looks_garbled(text: str) -> bool:
    """True for output such as "हुँँँँँँँँँँ" or "aaaaaaaaaaaa": a known failure of the recogniser."""
    return len(text) > GARBLED_LENGTH or GARBLED_REPEAT.search(text) is not None


# What the recogniser is told for each choice. Whisper has no "Hinglish" mode; Hindi is the
# closest, and writes English words in Devanagari.
WHISPER_LANGUAGE: dict[str, str | None] = {"auto": None, "en": "en", "hi": "hi", "hinglish": "hi"}


@dataclass(frozen=True)
class Transcription:
    words: list[Word]
    text: str
    # ISO code such as "en" or "hi", as given by the user or detected by the model.
    language: str | None
    language_probability: float | None


class Transcriber(Protocol):
    name: str

    def transcribe(
        self, samples: np.ndarray, language: LanguageHint, check: Callable[[], None]
    ) -> Transcription: ...


class WhisperTranscriber:
    """Loads the model on first use and keeps it in memory for later jobs."""

    def __init__(self, model_name: str, compute_type: str) -> None:
        self.name = model_name
        self._compute_type = compute_type
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        from app.speech_model import local_model_path

        path = local_model_path(self.name)
        if path is None:
            raise PipelineError(
                "speech_model_missing",
                f"The speech model '{self.name}' is not downloaded yet. In the backend folder, "
                "run: uv run python -m app.speech_model download — then retry.",
                retryable=True,
            )
        try:
            self._model = WhisperModel(
                str(path), device="cpu", compute_type=self._compute_type, local_files_only=True
            )
        except Exception as error:
            raise PipelineError(
                "speech_model_failed",
                f"The speech model '{self.name}' could not be loaded ({type(error).__name__}).",
                retryable=True,
            ) from error
        return self._model

    def transcribe(
        self, samples: np.ndarray, language: LanguageHint, check: Callable[[], None]
    ) -> Transcription:
        model = self._load()
        check()
        segments, info = model.transcribe(
            samples,
            language=WHISPER_LANGUAGE[language],
            word_timestamps=True,
            # Skips silence before recognising, which stops the model inventing words there.
            vad_filter=True,
            # Each window is recognised on its own, so one mistake cannot snowball.
            condition_on_previous_text=False,
            beam_size=5,
            # When a 30-second window comes out badly, Whisper redoes it with a little more
            # randomness ("temperature"), up to five times. That safeguard matters: without
            # it, one Hindi MP3 came out as a single character repeated for five seconds.
            temperature=RETRY_TEMPERATURES,
            # What counts as "badly": text that compresses more than this is treated as the
            # recogniser stuck in a loop. Whisper's default of 2.4 also catches a practised
            # passage said several times over, and retrying that made one test clip six
            # times slower for no gain. The stuck output measured 5.0 and genuine repeated
            # speech 2.7, so the line is drawn between them.
            compression_ratio_threshold=REPETITION_THRESHOLD,
        )

        words: list[Word] = []
        texts: list[str] = []
        # `segments` is lazy: the model works window by window as this loop pulls results,
        # so checking between windows is a real, safe place to stop.
        for segment in segments:
            check()
            texts.append(segment.text.strip())
            for word in segment.words or []:
                text = word.word.strip()
                if text:
                    words.append(
                        Word(text, float(word.start), float(word.end), float(word.probability))
                    )

        return Transcription(
            words=words,
            text=" ".join(text for text in texts if text),
            language=info.language,
            language_probability=float(info.language_probability),
        )
