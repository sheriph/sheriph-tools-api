"""
Video Metadata Extractor — returns structured JSON metadata for a video URL.
"""
import asyncio
import json
import subprocess

from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import JSONResponse

from ._helpers import YTDLP_PATH

router = APIRouter()

# Fields to expose (whitelist to avoid leaking internal yt-dlp noise)
EXPOSED_FIELDS = [
    "id", "title", "fulltitle", "description", "webpage_url",
    "uploader", "uploader_id", "uploader_url", "channel", "channel_id", "channel_url",
    "channel_follower_count", "channel_is_verified",
    "upload_date", "timestamp", "duration", "duration_string",
    "view_count", "like_count", "comment_count",
    "width", "height", "fps", "dynamic_range", "vcodec", "acodec",
    "thumbnail", "categories", "tags", "age_limit",
    "live_status", "availability", "ext", "extractor", "playable_in_embed",
]


@router.post("/metadata")
async def extract_metadata(url: str = Form(...)) -> JSONResponse:
    """
    Extract metadata from a video URL and return a clean JSON object.
    Uses yt-dlp --dump-json (no download).
    """
    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    cmd = [
        YTDLP_PATH,
        "--dump-json",
        "--no-playlist",
        "--no-download",
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
        raise HTTPException(status_code=504, detail="Timed out fetching metadata")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch metadata: {e}")

    if result.returncode != 0:
        err = result.stderr.strip() or "Could not fetch metadata"
        raise HTTPException(status_code=400, detail=err)

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Invalid response from yt-dlp")

    # Build clean response
    meta: dict = {}
    for field in EXPOSED_FIELDS:
        val = raw.get(field)
        if val is not None:
            meta[field] = val

    # Format upload date for readability
    if "upload_date" in meta and len(meta["upload_date"]) == 8:
        d = meta["upload_date"]
        meta["upload_date_formatted"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"

    return JSONResponse(meta)
