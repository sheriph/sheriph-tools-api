"""
Video to MP3 / Audio Extractor — extract best audio as MP3.
"""
import asyncio
import subprocess

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path

from ._helpers import FFMPEG_PATH, YTDLP_PATH, cleanup_tmp_dir, make_tmp_dir

router = APIRouter()


@router.post("/audio")
async def extract_audio(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    audio_format: str = Form("mp3"),
    audio_quality: str = Form("0"),  # VBR 0 = best
) -> FileResponse:
    """
    Extract audio from any video URL and return it as an MP3 (or other format).
    """
    allowed_formats = {"mp3", "m4a", "opus", "flac", "wav", "aac"}
    fmt = audio_format.lower().strip()
    if fmt not in allowed_formats:
        raise HTTPException(status_code=400, detail=f"Unsupported format. Choose from: {', '.join(sorted(allowed_formats))}")

    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    tmp_dir, _job_id = make_tmp_dir()

    output_template = f"{tmp_dir}/%(title).100B.%(ext)s"
    cmd = [
        YTDLP_PATH,
        "--no-playlist",
        "--format", "bestaudio/best",
        "--extract-audio",
        "--audio-format", fmt,
        "--audio-quality", audio_quality,
        "--ffmpeg-location", FFMPEG_PATH,
        "--output", output_template,
        "--no-progress",
        "--quiet",
        url.strip(),
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=504, detail="Audio extraction timed out (300 s)")
    except Exception as e:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=f"Audio extraction failed: {e}")

    if result.returncode != 0:
        cleanup_tmp_dir(tmp_dir)
        err = result.stderr.strip() or "yt-dlp reported an error"
        raise HTTPException(status_code=400, detail=err)

    # Find the audio file
    audio_file: Path | None = None
    for p in Path(tmp_dir).iterdir():
        if p.is_file() and p.suffix.lower().lstrip(".") == fmt:
            audio_file = p
            break

    if not audio_file:
        # Fallback: any non-part file
        for p in Path(tmp_dir).iterdir():
            if p.is_file() and not p.suffix.lower().endswith((".part", ".ytdl")):
                audio_file = p
                break

    if not audio_file or not audio_file.exists():
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail="Audio file not found after extraction")

    background_tasks.add_task(cleanup_tmp_dir, tmp_dir)

    mime_map = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "opus": "audio/ogg",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "aac": "audio/aac",
    }
    mime = mime_map.get(fmt, "audio/mpeg")

    return FileResponse(
        path=str(audio_file),
        media_type=mime,
        filename=audio_file.name,
    )
