"""An end-to-end run with the real speech detector and the real speech model.

Skipped by default because it needs the downloaded model and macOS's `say` command, and
takes several seconds. Run it with:

    RUN_SPEECH_TESTS=1 uv run pytest tests/test_real_speech.py
"""

import os
import shutil
import subprocess

import pytest

from app.pipeline.runner import PipelineDeps, run_analysis
from app.pipeline.settings import DEFAULT_SETTINGS
from app.pipeline.transcribe import WhisperTranscriber
from app.speech_model import local_model_path

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_SPEECH_TESTS")
    or shutil.which("say") is None
    or local_model_path("small") is None,
    reason="needs RUN_SPEECH_TESTS=1, the macOS `say` command and the downloaded speech model",
)


def test_synthesised_speech_with_known_silences_is_measured_sensibly(tmp_path):
    path = tmp_path / "speech.aiff"
    # [[slnc N]] tells the synthesiser to insert N milliseconds of silence.
    script = (
        "I am not in danger. I am the danger. [[slnc 1500]] "
        "A guy opens his door and gets shot, and you think that of me? [[slnc 6000]] "
        "I am the one who knocks."
    )
    subprocess.run(["say", "-v", "Samantha", "-o", str(path), script], check=True)

    body = run_analysis(
        path,
        profile="custom",
        language="auto",
        settings=DEFAULT_SETTINGS,
        max_seconds=600,
        deps=PipelineDeps(transcriber=WhisperTranscriber("small", "int8")),
    )

    assert body.language.code == "en"
    assert "danger" in body.transcript.lower()
    assert 25 <= body.metrics.total_word_count.value <= 34

    # The two inserted silences must be found, at about the requested lengths.
    durations = sorted(pause.duration_seconds for pause in body.pauses)
    assert durations[-1] == pytest.approx(6.0, abs=0.5)
    assert any(1.3 <= duration <= 2.0 for duration in durations)
    assert [pause.significance for pause in body.pauses].count("long") == 1
    assert max(segment.section_index for segment in body.segments) == 1

    # Half the clip is silence, so the two rates must differ widely.
    active = body.metrics.speech_active_wpm.value
    whole = body.metrics.whole_clip_wpm.value
    assert 150 < active < 280
    assert whole < active * 0.7
    assert 100 < body.metrics.pitch_median_hz.value < 300
    assert body.warnings == []
