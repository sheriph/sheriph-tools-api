from fastapi import APIRouter, HTTPException, UploadFile, Form

from ._helpers import _FORMAT_MIME, _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()


@router.post("/compress")
async def compress_image(
    file: UploadFile,
    quality: int = Form(80),
    format: str = Form("jpeg"),
):
    """Compress an image with the given quality and output format."""
    if not 1 <= quality <= 95:
        raise HTTPException(status_code=400, detail="quality must be between 1 and 95")

    fmt = format.lower().lstrip(".")
    if fmt not in _FORMAT_MIME:
        raise HTTPException(status_code=400, detail="Unsupported image format")

    raw = await file.read()
    img = _open_image(raw)

    try:
        encoded = _encode(img, fmt, quality)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to encode image: {exc}")

    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"compressed.{ext}")
