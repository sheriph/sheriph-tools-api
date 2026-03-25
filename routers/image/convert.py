from fastapi import APIRouter, HTTPException, UploadFile, Form
from fastapi.responses import Response

from ._helpers import _FORMAT_MIME, _FORMAT_EXT, _open_image, _encode

router = APIRouter()


@router.post("/convert")
async def convert_image(
    file: UploadFile,
    format: str = Form(...),
):
    """Convert an image to a different format."""
    fmt = format.lower().lstrip(".")
    if fmt not in _FORMAT_MIME:
        raise HTTPException(status_code=400, detail="Unsupported image format")

    raw = await file.read()
    img = _open_image(raw)

    try:
        encoded = _encode(img, fmt)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Conversion failed: {exc}")

    ext = _FORMAT_EXT.get(fmt, fmt)
    mime = _FORMAT_MIME[fmt]
    return Response(
        content=encoded,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="converted.{ext}"'},
    )
