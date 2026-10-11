"""Where audio files live on disk, and the only code that creates or deletes them.

    <data dir>/uploads/   files waiting to be analysed (temporary)
    <data dir>/audio/     recordings the user asked to keep

Paths stored in the database are relative to the data folder, so the folder can be moved.
"""

import os
import shutil
import time
from pathlib import Path
from typing import BinaryIO

from app.config import settings

UPLOADS_DIR = "uploads"
RETAINED_DIR = "audio"

# Extensions accepted for upload. Decoding, not the name, has the final say on validity.
ALLOWED_EXTENSIONS = frozenset(
    {".wav", ".mp3", ".m4a", ".aac", ".mp4", ".ogg", ".oga", ".opus", ".webm", ".flac", ".aiff", ".aif"}
)  # fmt: skip
EXTENSION_BY_CONTENT_TYPE = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aiff": ".aiff",
    "audio/x-aiff": ".aiff",
}
# What to tell the browser a kept recording is, so that it will play it.
CONTENT_TYPE_BY_EXTENSION = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".webm": "audio/webm",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}
COPY_CHUNK_BYTES = 1024 * 1024


class UploadTooLarge(Exception):
    pass


def pick_extension(filename: str | None, content_type: str | None) -> str | None:
    """The extension to store the upload under, or None if it is not an accepted audio type."""
    suffix = Path(filename or "").suffix.lower()
    if suffix in ALLOWED_EXTENSIONS:
        return suffix
    # Browsers add parameters, e.g. "audio/webm;codecs=opus".
    base_type = (content_type or "").split(";")[0].strip().lower()
    return EXTENSION_BY_CONTENT_TYPE.get(base_type)


def display_name(filename: str | None) -> str | None:
    """The bare file name for showing in the UI: no folders, no control characters."""
    if not filename:
        return None
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(character for character in name if character.isprintable()).strip()
    return name[:255] or None


def absolute(relative_path: str, data_dir: Path | None = None) -> Path:
    """Resolves a stored path, refusing anything that would land outside the data folder."""
    root = (data_dir or settings.data_dir).resolve()
    path = (root / relative_path).resolve()
    if root != path and root not in path.parents:
        raise ValueError("path escapes the data folder")
    return path


def save_upload(
    source: BinaryIO, job_id: str, extension: str, max_bytes: int, data_dir: Path | None = None
) -> tuple[str, int]:
    """Copies an upload to disk. Returns (relative path, size). Leaves nothing behind on error."""
    relative = f"{UPLOADS_DIR}/{job_id}{extension}"
    target = absolute(relative, data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := source.read(COPY_CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge
                output.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return relative, size


def delete_audio(relative_path: str | None, data_dir: Path | None = None) -> None:
    if not relative_path:
        return
    try:
        absolute(relative_path, data_dir).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def audio_exists(relative_path: str | None, data_dir: Path | None = None) -> bool:
    if not relative_path:
        return False
    try:
        return absolute(relative_path, data_dir).is_file()
    except ValueError:
        return False


def retain_audio(relative_path: str, analysis_id: str, data_dir: Path | None = None) -> str:
    """Moves an upload into the kept-recordings folder. Returns its new relative path."""
    source = absolute(relative_path, data_dir)
    kept = f"{RETAINED_DIR}/{analysis_id}{source.suffix}"
    target = absolute(kept, data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, target)
    return kept


def duplicate_audio(
    relative_path: str, folder: str, name: str, data_dir: Path | None = None, *, link: bool
) -> str:
    """Gives a stored recording a second file of its own. Returns its relative path.

    With `link`, the second file is another name for the same bytes on disk, which takes no
    extra space; deleting either name leaves the other playable. Where the disk cannot do
    that, or without `link`, the bytes are copied.
    """
    source = absolute(relative_path, data_dir)
    relative = f"{folder}/{name}{source.suffix}"
    target = absolute(relative, data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    if link:
        try:
            os.link(source, target)
            return relative
        except OSError:
            pass
    shutil.copyfile(source, target)
    return relative


def delete_stray_uploads(
    known_paths: set[str], older_than_seconds: float, data_dir: Path | None = None
) -> int:
    """Removes upload files no job refers to, e.g. left by a crash between saving and queueing."""
    folder = absolute(UPLOADS_DIR, data_dir)
    if not folder.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - older_than_seconds
    for path in folder.iterdir():
        relative = f"{UPLOADS_DIR}/{path.name}"
        if path.is_file() and relative not in known_paths and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed
