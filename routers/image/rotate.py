from fastapi import APIRouter, HTTPException, UploadFile, Form

from ._helpers import _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()


@router.post("/rotate")
async def rotate_image(
    file: UploadFile,
    angle: int = Form(...),
    expand: bool = Form(True),
):
    """Rotate an image by 90, 180, or 270 degrees."""
    if angle not in (90, 180, 270):
        raise HTTPException(status_code=400, detail="angle must be 90, 180, or 270")

    raw = await file.read()
    img = _open_image(raw)
    orig_fmt = img.format or "PNG"

    try:
        rotated = img.rotate(-angle, expand=expand)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Rotation failed: {exc}")

    fmt = orig_fmt.lower()
    encoded = _encode(rotated, fmt)
    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"rotated.{ext}")
