from fastapi import APIRouter, HTTPException, UploadFile, Form

from ._helpers import _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()


@router.post("/crop")
async def crop_image(
    file: UploadFile,
    x: int = Form(...),
    y: int = Form(...),
    width: int = Form(...),
    height: int = Form(...),
):
    """Crop an image to the given rectangle."""
    raw = await file.read()
    img = _open_image(raw)
    orig_fmt = img.format or "PNG"

    if x < 0 or y < 0 or x + width > img.width or y + height > img.height:
        raise HTTPException(status_code=400, detail="Crop dimensions exceed image bounds")

    try:
        cropped = img.crop((x, y, x + width, y + height))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Crop failed: {exc}")

    fmt = orig_fmt.lower()
    encoded = _encode(cropped, fmt)
    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"cropped.{ext}")
