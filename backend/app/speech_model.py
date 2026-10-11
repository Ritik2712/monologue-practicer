"""The local speech-recognition model: where it is, and the one command that downloads it.

The worker never downloads anything on its own. It only loads a model that is already on
disk, so analysing a recording makes no network request. Downloading is this explicit step:

    uv run python -m app.speech_model download
    uv run python -m app.speech_model status
"""

import os
import sys
from pathlib import Path

# Must be set before huggingface_hub is imported anywhere in this process.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

from app.config import settings


def local_model_path(model: str | None = None) -> Path | None:
    """Folder of the model if it is already on this computer, otherwise None. No network."""
    from faster_whisper.utils import download_model

    name = model or settings.whisper_model
    if Path(name).is_dir():
        return Path(name)
    try:
        return Path(download_model(name, local_files_only=True))
    except Exception:  # noqa: BLE001 - whatever went wrong, the model is not usable from disk
        return None


def download(model: str | None = None) -> Path:
    """Fetches the model from Hugging Face into the local cache. The only networked step."""
    from faster_whisper.utils import download_model

    return Path(download_model(model or settings.whisper_model))


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else "status"
    name = settings.whisper_model

    if command == "status":
        path = local_model_path()
        if path:
            print(f"Speech model '{name}' is ready.")
            return 0
        print(f"Speech model '{name}' is not downloaded.")
        print("Download it once with:  uv run python -m app.speech_model download")
        return 1

    if command == "download":
        if local_model_path():
            print(f"Speech model '{name}' is already downloaded.")
            return 0
        print(f"Downloading speech model '{name}' from Hugging Face. This happens once.")
        try:
            download()
        except Exception as error:  # noqa: BLE001 - any failure is reported the same way
            print(f"Download failed ({type(error).__name__}). Check the connection and retry.")
            return 1
        print(f"Speech model '{name}' is ready.")
        return 0

    print("Usage: python -m app.speech_model [status|download]")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
