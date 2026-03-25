from fastapi import APIRouter, HTTPException, UploadFile, Form
from PIL import Image

from ._helpers import _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()


@router.post("/upscale")
async def upscale_image(
    file: UploadFile,
    scale: int = Form(2),
):
    """Upscale an image using high-quality Lanczos resampling."""
    if scale not in (2, 3, 4):
        raise HTTPException(status_code=400, detail="scale must be 2, 3, or 4")

    raw = await file.read()
    img = _open_image(raw)
    orig_fmt = img.format or "PNG"

    try:
        new_w = img.width * scale
        new_h = img.height * scale
        upscaled = img.resize((new_w, new_h), Image.LANCZOS)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Upscale failed: {exc}")

    fmt = orig_fmt.lower()
    encoded = _encode(upscaled, fmt)
    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"upscaled_{scale}x.{ext}")
