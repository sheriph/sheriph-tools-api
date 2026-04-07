"""
Universal Video Downloader — wraps yt-dlp to download a video.
Supports quality selection and streams the file back as a download.
"""
import asyncio
import json
import subprocess

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ._helpers import FFMPEG_PATH, YTDLP_PATH, cleanup_tmp_dir, find_output_file, make_tmp_dir

router = APIRouter()


@router.post("/formats")
async def get_video_formats(url: str = Form(...)) -> JSONResponse:
    """
    Return available formats for a URL so the frontend can offer a quality picker.
    Runs yt-dlp --dump-json and returns a curated list of formats.
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    cmd = [YTDLP_PATH, "--dump-json", "--no-playlist", "--quiet", url.strip()]
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timed out fetching video info")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch info: {e}")

    if result.returncode != 0:
        err = result.stderr.strip() or "Could not fetch video information"
        raise HTTPException(status_code=400, detail=err)

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Invalid response from yt-dlp")

    formats = info.get("formats", [])
    # Build a deduplicated list of useful quality options
    seen_heights: set[int | None] = set()
    quality_options: list[dict] = []

    # Best combined first
    quality_options.append({"format_id": "bestvideo+bestaudio/best", "label": "Best quality (auto)", "note": "Recommended"})

    # Then per-resolution options from actual formats
    resolutions = [2160, 1440, 1080, 720, 480, 360, 240, 144]
    for res in resolutions:
        has_res = any(
            f.get("height") == res and f.get("vcodec", "none") != "none"
            for f in formats
        )
        if has_res:
            quality_options.append({
                "format_id": f"bestvideo[height<={res}]+bestaudio/best[height<={res}]",
                "label": f"{res}p",
            })

    # Audio-only as last option
    quality_options.append({"format_id": "bestaudio/best", "label": "Audio only (best)"})

    return JSONResponse({
        "title": info.get("title", ""),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url", url),
        "formats": quality_options,
    })


@router.post("/download")
async def download_video(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    format_id: str = Form("bestvideo+bestaudio/best"),
) -> FileResponse:
    """
    Download a video at the requested quality and stream it back as a file.
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    tmp_dir, _job_id = make_tmp_dir()

    output_template = f"{tmp_dir}/%(title).100B.%(ext)s"
    cmd = [
        YTDLP_PATH,
        "--no-playlist",
        "--format", format_id,
        "--merge-output-format", "mp4",
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
        raise HTTPException(status_code=504, detail="Download timed out (300 s)")
    except Exception as e:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=f"Download failed: {e}")

    if result.returncode != 0:
        cleanup_tmp_dir(tmp_dir)
        err = result.stderr.strip() or "yt-dlp reported an error"
        raise HTTPException(status_code=400, detail=err)

    output_file = find_output_file(tmp_dir)
    if not output_file or not output_file.exists():
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail="Output file not found after download")

    background_tasks.add_task(cleanup_tmp_dir, tmp_dir)

    mime = "video/mp4"
    if output_file.suffix.lower() in (".webm",):
        mime = "video/webm"
    elif output_file.suffix.lower() in (".mkv",):
        mime = "video/x-matroska"

    return FileResponse(
        path=str(output_file),
        media_type=mime,
        filename=output_file.name,
        background=None,  # background_tasks handles cleanup
    )
