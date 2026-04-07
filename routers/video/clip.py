"""
Video Clip Downloader — download a specific time segment of a video.
Requires ffmpeg for the --download-sections feature.
"""
import asyncio
import subprocess

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse

from ._helpers import FFMPEG_PATH, YTDLP_PATH, cleanup_tmp_dir, find_output_file, make_tmp_dir

router = APIRouter()


def _parse_time(t: str) -> bool:
    """Validate HH:MM:SS or MM:SS or seconds format."""
    t = t.strip()
    if not t:
        return False
    parts = t.split(":")
    if len(parts) > 3:
        return False
    try:
        for p in parts:
            int(p)
        return True
    except ValueError:
        return False


@router.post("/clip")
async def download_clip(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
) -> FileResponse:
    """
    Download a specific segment of a video between start_time and end_time.
    Both times must be in HH:MM:SS, MM:SS, or integer seconds format.
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    if not _parse_time(start_time):
        raise HTTPException(status_code=400, detail="Invalid start_time format. Use HH:MM:SS, MM:SS, or seconds.")

    if not _parse_time(end_time):
        raise HTTPException(status_code=400, detail="Invalid end_time format. Use HH:MM:SS, MM:SS, or seconds.")

    tmp_dir, _job_id = make_tmp_dir()
    output_template = f"{tmp_dir}/%(title).100B.%(ext)s"

    section = f"*{start_time.strip()}-{end_time.strip()}"
    cmd = [
        YTDLP_PATH,
        "--no-playlist",
        # Cap at 1080p to avoid expensive 4K transcoding failures (exit 222)
        "--format", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "--download-sections", section,
        "--force-keyframes-at-cuts",
        "--ffmpeg-location", FFMPEG_PATH,
        "--output", output_template,
        "--no-progress",
        url.strip(),
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=504, detail="Clip download timed out (600 s)")
    except Exception as e:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=f"Clip download failed: {e}")

    if result.returncode != 0:
        cleanup_tmp_dir(tmp_dir)
        # Combine stdout + stderr; yt-dlp writes errors to both
        raw = (result.stderr.strip() or result.stdout.strip() or "yt-dlp reported an error")
        # Surface the last ERROR: line if present (most informative)
        for line in reversed(raw.splitlines()):
            if line.strip().startswith("ERROR:"):
                raw = line.strip()
                break
        raise HTTPException(status_code=400, detail=raw)

    output_file = find_output_file(tmp_dir)
    if not output_file or not output_file.exists():
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail="Output clip file not found after download")

    background_tasks.add_task(cleanup_tmp_dir, tmp_dir)

    return FileResponse(
        path=str(output_file),
        media_type="video/mp4",
        filename=f"clip_{start_time.replace(':', '-')}–{end_time.replace(':', '-')}_{output_file.name}",
    )
