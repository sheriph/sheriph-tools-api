from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, Form
from PIL import Image

from ._helpers import _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()


@router.post("/resize")
async def resize_image(
    file: UploadFile,
    width: Optional[int] = Form(None),
    height: Optional[int] = Form(None),
    mode: str = Form("fit"),
    unit: str = Form("px"),
    no_enlarge: bool = Form(False),
):
    """Resize an image."""
    if width is None and height is None:
        raise HTTPException(status_code=400, detail="At least one of width or height is required")
    if mode not in ("exact", "fit", "fill"):
        raise HTTPException(status_code=400, detail="mode must be 'exact', 'fit', or 'fill'")
    if unit not in ("px", "percent"):
        raise HTTPException(status_code=400, detail="unit must be 'px' or 'percent'")

    raw = await file.read()
    img = _open_image(raw)
    orig_fmt = img.format or "PNG"

    orig_w, orig_h = img.size

    if unit == "percent":
        width = int(orig_w * (width / 100)) if width is not None else None
        height = int(orig_h * (height / 100)) if height is not None else None

    if width is None:
        width = int(orig_w * (height / orig_h))
    if height is None:
        height = int(orig_h * (width / orig_w))

    # Prevent upscaling when requested
    if no_enlarge:
        width = min(width, orig_w)
        height = min(height, orig_h)

    try:
        if mode == "exact":
            resized = img.resize((width, height), Image.LANCZOS)
        elif mode == "fit":
            resized = img.copy()
            resized.thumbnail((width, height), Image.LANCZOS)
        else:
            scale = max(width / orig_w, height / orig_h)
            scaled_w = int(orig_w * scale)
            scaled_h = int(orig_h * scale)
            scaled = img.resize((scaled_w, scaled_h), Image.LANCZOS)
            left = (scaled_w - width) // 2
            top = (scaled_h - height) // 2
            resized = scaled.crop((left, top, left + width, top + height))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Resize failed: {exc}")

    fmt = orig_fmt.lower()
    encoded = _encode(resized, fmt)
    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"resized.{ext}")
