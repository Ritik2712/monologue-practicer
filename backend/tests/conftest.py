"""Shared test tools: a temporary database and data folder, a controllable clock, generated
audio files, and stand-ins for the slow parts of the pipeline."""

import io
import json
import math
import struct
import wave
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import job_queue, schemas, uploads
from app.coaching.coach import Coach
from app.db import Base, get_session, make_engine
from app.dependencies import get_data_dir, get_now
from app.llm import LlmError, Message, Reply
from app.main import app
from app.pipeline import acoustics
from app.pipeline.runner import PipelineDeps
from app.pipeline.segmentation import SpeechRegion, Word
from app.pipeline.transcribe import Transcription
from app.worker import Worker


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 11, 9, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


class FakeTranscriber:
    """Returns prepared words instead of running a speech model."""

    name = "fake-model"

    def __init__(self, words: list[Word] | None = None, language: str = "en") -> None:
        self.words = words or []
        self.language = language
        self.language_probability = 0.99
        self.calls = 0
        self.error: Exception | None = None
        # Runs in the middle of transcription, e.g. to request cancellation at that moment.
        self.during: Callable[[], None] | None = None

    def transcribe(self, samples, language, check) -> Transcription:
        self.calls += 1
        check()
        if self.during:
            self.during()
        check()
        if self.error:
            raise self.error
        return Transcription(
            words=list(self.words),
            text=" ".join(word.text for word in self.words),
            language=self.language,
            language_probability=self.language_probability,
        )


class FakeChat:
    """Stands in for the language model: gives prepared answers and records what it was asked."""

    name = "fake-llm"
    context_tokens = 8192

    def __init__(self, *replies: str | dict | Exception, model_status: str = "ready") -> None:
        # Each call takes the next reply; the last one is repeated if more calls come.
        self.replies = list(replies)
        self.model_status = model_status
        self.calls: list[tuple[list[Message], dict]] = []
        # Runs in the middle of answering, e.g. to request cancellation at that moment.
        self.during: Callable[[], None] | None = None

    def status(self) -> str:
        return self.model_status

    def complete_json(self, messages, schema, *, max_tokens, check=lambda: None) -> Reply:
        self.calls.append((list(messages), schema))
        if self.model_status != "ready":
            raise LlmError(self.model_status, f"The model is {self.model_status}.")
        if self.during:
            self.during()
        check()
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            reply = reply(schema)
        if isinstance(reply, dict):
            reply = json.dumps(reply)
        return Reply(text=reply, truncated=False, seconds=1.5)


def answer_within(schema: dict) -> dict:
    """A well-behaved model answer: one correction per allowed slot, naming real findings."""
    corrections = schema["properties"]["corrections"]
    fields = corrections["items"]["properties"]
    working = schema["properties"]["working"]
    return {
        "corrections": [
            {
                "finding": finding,
                "segment": fields["segment"]["enum"][0],
                "title": f"Work on {finding}",
                "why": "A listener loses the thread here.",
                "drill": "Say the line again, slowly, 3 times.",
            }
            for finding in fields["finding"]["enum"][: corrections["maxItems"]]
        ],
        "working": [
            {"finding": finding, "note": "Keep this."}
            for finding in working.get("items", {})
            .get("properties", {})
            .get("finding", {})
            .get("enum", [])[:1]
        ],
    }


def metric(value: float | None, unit: str = "", quality: str = "measured") -> schemas.MetricValue:
    return schemas.MetricValue(
        value=value, unit=unit, quality="unavailable" if value is None else quality
    )


def make_segment(
    index: int, start: float, end: float, text: str, **fields
) -> schemas.SpeechSegment:
    words = len(text.split())
    values = {
        "id": f"seg-{index + 1}",
        "index": index,
        "section_index": 0,
        "start_seconds": start,
        "end_seconds": end,
        "speech_active_seconds": end - start,
        "transcript": text or None,
        "word_count": words,
        "segment_wpm": round(words / ((end - start) / 60), 1) if words else None,
        "pace_vs_typical": None,
        "quality": "measured",
        "reliable": True,
        "flags": [],
        "confidence": 0.9,
        "mean_energy_db": -20.0,
        "energy_delta_db": 0.0,
        "median_pitch_hz": 180.0,
        "pitch_delta_semitones": 0.0,
    }
    return schemas.SpeechSegment(**{**values, **fields})


def make_pause(index: int, start: float, end: float) -> schemas.PauseEvent:
    duration = round(end - start, 3)
    return schemas.PauseEvent(
        id=f"pause-{index + 1}",
        index=index,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=duration,
        significance="short" if duration < 1 else "medium" if duration < 5 else "long",
        after_segment_id=f"seg-{index + 1}",
        before_segment_id=f"seg-{index + 2}",
        starts_new_section=duration >= 5,
    )


def make_silence(start: float, end: float, segment_id: str) -> schemas.ShortSilence:
    """A silence too short to be a pause, lying inside the given segment."""
    return schemas.ShortSilence(
        start_seconds=start,
        end_seconds=end,
        duration_seconds=round(end - start, 3),
        segment_id=segment_id,
    )


# A 17-second take of four phrases. The third is rushed; the pauses are 0.6, 0.7 and 0.8 s.
TAKE_SEGMENTS = (
    (0.0, 4.0, "You clearly do not know who you are talking to"),
    (4.6, 8.6, "so let me clue you in on one small thing"),
    (9.3, 12.3, "I am not in danger Skylar I am the danger and you should know that by now"),
    (13.1, 17.1, "a guy opens his door and gets shot"),
)


def make_body(profile: str = "custom", **overrides) -> schemas.AnalysisBody:
    """A complete measured recording for the coaching tests, built without any audio.

    Keyword arguments named after a metric (snake_case) replace that metric's value; `None`
    makes it unavailable. `segments`, `pauses`, `words`, `warnings`, `hesitations`,
    `emphasis_candidates` and `short_silences` replace those lists, and `settings` adds to
    the settings the result says it was made with.
    """
    duration_seconds = overrides.pop("duration_seconds", 17.3)
    short_silences = overrides.pop("short_silences", None)
    settings = {"version": 1, "min_pause_ms": 500, **overrides.pop("settings", {})}
    segments = overrides.pop("segments", None)
    if segments is None:
        segments = [make_segment(i, a, b, text) for i, (a, b, text) in enumerate(TAKE_SEGMENTS)]
        segments[2].pace_vs_typical = "faster"
    pauses = overrides.pop("pauses", None)
    if pauses is None:
        pauses = [
            make_pause(i, segments[i].end_seconds, segments[i + 1].start_seconds)
            for i in range(len(segments) - 1)
        ]
    words = overrides.pop("words", None)
    if words is None:
        words = [
            schemas.WordTiming(
                text=text,
                start_seconds=s.start_seconds,
                end_seconds=s.end_seconds,
                confidence=0.9,
                segment_id=s.id,
            )
            for s in segments
            for text in (s.transcript or "").split()
        ]
    values = {
        "total_word_count": metric(len(words), "words"),
        "speech_active_seconds": metric(sum(s.speech_active_seconds for s in segments), "seconds"),
        "speech_active_wpm": metric(160.0, "words/minute"),
        "whole_clip_wpm": metric(120.0, "words/minute"),
        "pace_variation": metric(24.0, "words/minute"),
        "pace_min_wpm": metric(120.0, "words/minute"),
        "pace_max_wpm": metric(340.0, "words/minute"),
        "typical_segment_wpm": metric(150.0, "words/minute"),
        "pause_count": metric(float(len(pauses)), "count"),
        "total_pause_seconds": metric(sum(p.duration_seconds for p in pauses), "seconds"),
        "average_pause_seconds": metric(0.7, "seconds"),
        "median_pause_seconds": metric(0.7, "seconds") if pauses else metric(None, "seconds"),
        "longest_pause_seconds": metric(0.8, "seconds") if pauses else metric(None, "seconds"),
        "pause_ratio": metric(0.105, "ratio"),
        "leading_silence_seconds": metric(0.0, "seconds"),
        "trailing_silence_seconds": metric(0.2, "seconds"),
        "energy_variation": metric(4.5, "dB"),
        "signal_to_noise": metric(40.0, "dB", "estimated"),
        "pitch_median_hz": metric(180.0, "Hz"),
        "pitch_range_hz": metric(60.0, "Hz"),
        "pitch_range_semitones": metric(6.0, "semitones"),
        "pitch_variation_semitones": metric(3.0, "semitones"),
        "filler_word_count": metric(0.0, "count", "estimated"),
        "breath_count": metric(None, "count"),
        "clipping_ratio": metric(0.0, "ratio"),
    }
    lists = {
        key: overrides.pop(key, []) for key in ("warnings", "hesitations", "emphasis_candidates")
    }
    for name in list(overrides):
        if name in values:
            value = overrides.pop(name)
            values[name] = (
                value
                if isinstance(value, schemas.MetricValue)
                else metric(value, values[name].unit)
            )
    assert not overrides, f"unknown fields: {sorted(overrides)}"
    return schemas.AnalysisBody(
        profile=profile,
        language=schemas.LanguageInfo(code="en", source="declared", confidence=None),
        duration_seconds=duration_seconds,
        transcript=" ".join(s.transcript or "" for s in segments) or None,
        segments=segments,
        pauses=pauses,
        short_silences=short_silences,
        words=words,
        metrics=schemas.Metrics(**values),
        energy_timeline=schemas.EnergyTimeline(seconds_per_point=0.25, unit="dBFS", values=[]),
        settings=settings,
        pipeline=schemas.PipelineInfo(
            speech_model="fake-model", voice_activity_detector="silero-vad", pitch_tracker="pyin"
        ),
        **lists,
    )


def make_recording(
    phrases: list[tuple[float, float, str]], profile: str = "custom", **overrides
) -> schemas.AnalysisBody:
    """A measured recording built from phrases given as (start, end, "the words").

    The gaps between phrases become its pauses, and each phrase's words are spread evenly
    across it, which is what the comparison tests need to reason about exact times.
    """
    segments = [make_segment(i, a, b, text) for i, (a, b, text) in enumerate(phrases)]
    pauses = [
        make_pause(i, segments[i].end_seconds, segments[i + 1].start_seconds)
        for i in range(len(segments) - 1)
    ]
    words = []
    for segment in segments:
        spoken = (segment.transcript or "").split()
        step = (segment.end_seconds - segment.start_seconds) / max(1, len(spoken))
        words += [
            schemas.WordTiming(
                text=text,
                start_seconds=round(segment.start_seconds + k * step, 4),
                end_seconds=round(segment.start_seconds + (k + 1) * step, 4),
                confidence=0.9,
                segment_id=segment.id,
            )
            for k, text in enumerate(spoken)
        ]
    overrides.setdefault("duration_seconds", (segments[-1].end_seconds + 0.5) if segments else 1.0)
    return make_body(profile, segments=segments, pauses=pauses, words=words, **overrides)


def make_words(start: float, end: float, count: int, probability: float = 0.9) -> list[Word]:
    """`count` evenly spaced words filling the time from `start` to `end`."""
    step = (end - start) / count
    return [
        Word(f"word{i}", start + i * step, start + (i + 1) * step, probability)
        for i in range(count)
    ]


def fake_vad(regions: list[tuple[float, float]]):
    return lambda samples, settings: [SpeechRegion(start, end) for start, end in regions]


def no_pitch(samples, segments) -> acoustics.PitchTrack:
    return acoustics.PitchTrack(np.array([]), np.array([]))


def steady_pitch(samples, segments) -> acoustics.PitchTrack:
    """A voice that stays at 200 Hz for the whole of every segment."""
    times = np.concatenate([np.arange(s.start, s.end, 0.016) for s in segments] or [np.array([])])
    return acoustics.PitchTrack(times, np.full(times.shape, 200.0))


def wav_bytes(
    seconds: float = 1.0,
    *,
    rate: int = 16_000,
    channels: int = 1,
    frequency: float | None = 220.0,
    amplitude: float = 0.3,
    sounding: list[tuple[float, float]] | None = None,
) -> bytes:
    """A WAV file in memory: a sine tone, or silence when `frequency` is None.

    With `sounding`, the tone plays only during those (start, end) stretches and the rest is
    silent, which is the shape of speech with pauses.
    """
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        for index in range(frames):
            value = 0.0
            audible = sounding is None or any(a <= index / rate < b for a, b in sounding)
            if frequency is not None and audible:
                value = amplitude * math.sin(2 * math.pi * frequency * index / rate)
            output.writeframesraw(struct.pack("<h", int(value * 32767)) * channels)
    return buffer.getvalue()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "data"


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def session(session_factory):
    with session_factory() as active:
        yield active


@pytest.fixture
def client(session_factory, data_dir: Path, clock: FakeClock):
    def override_session():
        with session_factory() as active:
            yield active

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_data_dir] = lambda: data_dir
    app.dependency_overrides[get_now] = clock
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def transcriber() -> FakeTranscriber:
    # 12 words in the first 4 seconds and 6 words in the last 2: see `make_worker`.
    return FakeTranscriber(make_words(0.5, 4.5, 12) + make_words(6.0, 8.0, 6))


@pytest.fixture
def make_worker(session_factory, data_dir: Path, clock: FakeClock, transcriber: FakeTranscriber):
    """A worker whose speech detection and transcription are scripted.

    The scripted recording has speech at 0.5-4.5 s and 6.0-8.0 s, with a 1.5 s pause between.
    """

    def build(llm: FakeChat | None = None, **overrides) -> Worker:
        deps = PipelineDeps(
            transcriber=transcriber,
            detect_speech=fake_vad([(0.5, 4.5), (6.0, 8.0)]),
            measure_pitch=no_pitch,
        )
        # Without a language model, coaching comes from the templates.
        overrides.setdefault("coach", Coach(llm))
        return Worker(session_factory, deps, data_dir=data_dir, clock=clock, **overrides)

    return build


@pytest.fixture
def add_job(session_factory, data_dir: Path, clock: FakeClock):
    """Queues a job directly, with a real audio file on disk, bypassing the HTTP layer."""

    def add(content: bytes | None = None, **fields) -> str:
        job_id = job_queue.new_id()
        audio_path, _ = uploads.save_upload(
            io.BytesIO(wav_bytes(9.0) if content is None else content),
            job_id,
            fields.pop("extension", ".wav"),
            10_000_000,
            data_dir,
        )
        with session_factory() as active:
            job_queue.create_job(
                active,
                job_id=job_id,
                profile=fields.pop("profile", "custom"),
                language_hint=fields.pop("language_hint", "auto"),
                retain_audio=fields.pop("retain_audio", False),
                original_filename=fields.pop("original_filename", "take.wav"),
                audio_path=audio_path,
                idempotency_key=fields.pop("idempotency_key", None),
                now=clock(),
                role=fields.pop("role", "take"),
                title=fields.pop("title", None),
            )
        # Later jobs must sort after earlier ones.
        clock.advance(seconds=1)
        return job_id

    return add


@pytest.fixture
def store_result(session_factory, data_dir: Path, clock: FakeClock, add_job):
    """Stores a prepared result as a finished analysis and returns its ID.

    For tests that need exact pauses and silences, which the scripted worker cannot give.
    The coaching comes from the templates, as it does when no language model is set up.
    """

    def store(body: schemas.AnalysisBody, **job_fields) -> str:
        add_job(profile=body.profile, **job_fields)
        with session_factory() as active:
            job = job_queue.claim_next_job(active, clock())
            coaching = None if job.role == "reference" else Coach(None).generate(body, now=clock())
            analysis = job_queue.complete_job(
                active, job, body, 1, clock(), data_dir, coaching=coaching
            )
        clock.advance(seconds=1)
        return analysis.id

    return store
