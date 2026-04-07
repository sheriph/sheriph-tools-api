"""
Shared helpers for yt-dlp video routers.
"""
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path


YTDLP_PATH = shutil.which("yt-dlp") or "yt-dlp"
FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"


def make_tmp_dir() -> tuple[str, str]:
    """Create a unique temp directory. Returns (dir_path, job_id)."""
    job_id = uuid.uuid4().hex
    tmp = tempfile.mkdtemp(prefix=f"sheriph_video_{job_id}_")
    return tmp, job_id


def cleanup_tmp_dir(path: str) -> None:
    """Remove temp dir, ignoring errors."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def find_output_file(directory: str) -> Path | None:
    """Return the first non-.part, non-.ytdl file in a directory."""
    skip_exts = {".part", ".ytdl", ".json", ".description", ".srt", ".vtt", ".ass"}
    candidates: list[Path] = []
    for p in Path(directory).iterdir():
        if p.is_file() and p.suffix.lower() not in skip_exts:
            candidates.append(p)
    if not candidates:
        return None
    # Prefer the largest file (actual video/audio vs thumbnails)
    return max(candidates, key=lambda f: f.stat().st_size)
