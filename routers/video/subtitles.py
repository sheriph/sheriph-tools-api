"""
Subtitle & Caption Downloader.
"""
import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ._helpers import YTDLP_PATH, cleanup_tmp_dir, make_tmp_dir

router = APIRouter()


@router.post("/subtitle-languages")
async def list_subtitle_languages(url: str = Form(...)) -> JSONResponse:
    """Return available subtitle languages for a video URL."""
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
            subprocess.run, cmd, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Timed out fetching subtitle info")

    if result.returncode != 0:
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "Could not fetch subtitle info")

    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="Invalid response from yt-dlp")

    manual_subs: dict = info.get("subtitles", {})
    auto_subs: dict = info.get("automatic_captions", {})

    langs: list[dict] = []
    for lang, data in manual_subs.items():
        ext_list = [f.get("ext", "vtt") for f in data] if isinstance(data, list) else ["vtt"]
        langs.append({"code": lang, "auto": False, "formats": list(set(ext_list))})

    for lang, data in auto_subs.items():
        if lang in {l["code"] for l in langs}:
            continue
        ext_list = [f.get("ext", "vtt") for f in data] if isinstance(data, list) else ["vtt"]
        langs.append({"code": lang, "auto": True, "formats": list(set(ext_list))})

    if not langs:
        raise HTTPException(status_code=404, detail="No subtitles found for this video")

    return JSONResponse({"languages": langs, "title": info.get("title", "")})


@router.post("/subtitle")
async def download_subtitle(
    background_tasks: BackgroundTasks,
    url: str = Form(...),
    lang: str = Form("en"),
    fmt: str = Form("srt"),
    auto: bool = Form(False),
) -> FileResponse:
    """Download a subtitle file for the given URL, language, and format."""
    allowed_fmts = {"srt", "vtt", "ass", "lrc"}
    fmt = fmt.lower().strip()
    if fmt not in allowed_fmts:
        raise HTTPException(status_code=400, detail=f"Unsupported format. Choose: {', '.join(sorted(allowed_fmts))}")

    if not url.strip():
        raise HTTPException(status_code=400, detail="URL is required")

    tmp_dir, _job_id = make_tmp_dir()
    output_template = f"{tmp_dir}/%(title).100B.%(ext)s"

    sub_flags = ["--write-auto-subs"] if auto else ["--write-subs"]
    cmd = [
        YTDLP_PATH,
        "--no-playlist",
        "--skip-download",
        *sub_flags,
        "--sub-langs", lang,
        "--sub-format", fmt,
        "--convert-subs", fmt,
        "--output", output_template,
        "--no-progress",
        "--quiet",
        url.strip(),
    ]

    try:
        result = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=504, detail="Subtitle download timed out")
    except Exception as e:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=500, detail=f"Subtitle download failed: {e}")

    if result.returncode != 0:
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=400, detail=result.stderr.strip() or "yt-dlp error")

    sub_exts = {".srt", ".vtt", ".ass", ".lrc"}
    sub_file: Path | None = None
    for p in Path(tmp_dir).iterdir():
        if p.is_file() and p.suffix.lower() in sub_exts:
            sub_file = p
            break

    if not sub_file or not sub_file.exists():
        cleanup_tmp_dir(tmp_dir)
        raise HTTPException(status_code=404, detail="Subtitle file not found — may not be available for this video/language")

    background_tasks.add_task(cleanup_tmp_dir, tmp_dir)

    mime_map = {".srt": "text/plain", ".vtt": "text/vtt", ".ass": "text/plain", ".lrc": "text/plain"}
    mime = mime_map.get(sub_file.suffix.lower(), "text/plain")

    return FileResponse(path=str(sub_file), media_type=mime, filename=sub_file.name)
