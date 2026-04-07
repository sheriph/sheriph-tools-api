"""
Thumbnail Grabber — download the best thumbnail for a video URL.
"""
import asyncio
import subprocess
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse

from ._helpers import YTDLP_PATH, cleanup_tmp_dir, make_tmp_dir

router = APIRouter()


@router.post("/thumbnail")
async def grab_thumbnail(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
) -> FileResponse:
    """
    Download the highest-resolution thumbnail for a video URL.
    No video is downloaded — only the thumbnail image.
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    tmp_dir, _job_id = make_tmp_dir()

    output_template = f"{tmp_dir}/%(title).100B.%(ext)s"
    cmd = [
        YTDLP_PATH,
        "--no-playlist",
        "--write-thumbnail",
        "--skip-download",
        "--convert-thumbnails", "jpg",
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
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=504, detail="Timed out fetching thumbnail")
    except Exception as e:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=f"Thumbnail extraction failed: {e}")

    if result.returncode != 0:
        cleanup_tmp_dir(tmp_dir)
        err = result.stderr.strip() or "Could not fetch thumbnail"
        raise HTTPException(status_code=400, detail=err)

    # Find thumbnail file (jpg/webp/png)
    thumb_exts = {".jpg", ".jpeg", ".webp", ".png"}
    thumb_file: Path | None = None
    for p in Path(tmp_dir).iterdir():
        if p.is_file() and p.suffix.lower() in thumb_exts:
            thumb_file = p
            break

    if not thumb_file or not thumb_file.exists():
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail="Thumbnail file not found")

    background_tasks.add_task(cleanup_tmp_dir, tmp_dir)

    ext = thumb_file.suffix.lower().lstrip(".")
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "png": "image/png"}
    mime = mime_map.get(ext, "image/jpeg")

    return FileResponse(
        path=str(thumb_file),
        media_type=mime,
        filename=thumb_file.name,
    )
