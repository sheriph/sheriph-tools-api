import io

from fastapi import HTTPException
from fastapi.responses import Response
from PIL import Image

_FORMAT_MIME = {
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "tiff": "image/tiff",
    "bmp": "image/bmp",
    "avif": "image/avif",
}

_FORMAT_EXT = {
    "jpeg": "jpg",
    "jpg": "jpg",
    "png": "png",
    "webp": "webp",
    "gif": "gif",
    "tiff": "tiff",
    "bmp": "bmp",
    "avif": "avif",
}


def _open_image(data: bytes) -> Image.Image:
    """Open raw bytes as a Pillow image, raise 400 on failure."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        return img
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or corrupted image file")


def _to_jpeg_safe(img: Image.Image) -> Image.Image:
    """Composite RGBA/LA/P images onto a white background before JPEG save."""
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("RGBA", "LA"):
            background.paste(img, mask=img.split()[-1])
        else:
            background.paste(img)
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _encode(img: Image.Image, fmt: str, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    save_fmt = fmt.upper()
    if save_fmt == "JPG":
        save_fmt = "JPEG"
    kwargs = {}
    if save_fmt == "JPEG":
        kwargs["quality"] = quality
        img = _to_jpeg_safe(img)
    elif save_fmt in ("WEBP", "AVIF"):
        kwargs["quality"] = quality
    elif save_fmt == "BMP":
        # BMP does not support alpha; flatten to RGB
        if img.mode not in ("RGB", "L", "1"):
            img = _to_jpeg_safe(img)
    img.save(buf, format=save_fmt, **kwargs)
    return buf.getvalue()


def _response(data: bytes, fmt: str, filename: str) -> Response:
    mime = _FORMAT_MIME.get(fmt.lower(), "application/octet-stream")
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
