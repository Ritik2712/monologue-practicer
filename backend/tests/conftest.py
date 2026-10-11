"""Shared test tools: a temporary database and data folder, a controllable clock, generated
audio files, and stand-ins for the slow parts of the pipeline."""

import io
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

from app import job_queue, uploads
from app.db import Base, get_session, make_engine
from app.dependencies import get_data_dir, get_now
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

    def build(**overrides) -> Worker:
        deps = PipelineDeps(
            transcriber=transcriber,
            detect_speech=fake_vad([(0.5, 4.5), (6.0, 8.0)]),
            measure_pitch=no_pitch,
        )
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
            )
        # Later jobs must sort after earlier ones.
        clock.advance(seconds=1)
        return job_id

    return add
