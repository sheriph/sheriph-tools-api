import os
from typing import Optional, Union

from fastapi import APIRouter, HTTPException, UploadFile, Form
from PIL import Image, ImageDraw, ImageFont

from ._helpers import _FORMAT_EXT, _open_image, _encode, _response

router = APIRouter()

# ── Font lookup helpers ────────────────────────────────────────────────────────

_FONT_SEARCH_DIRS = [
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/truetype/ubuntu",
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/freefont",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype",
    "/usr/share/fonts/opentype",
    "/usr/share/fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
    "C:/Windows/Fonts",
]

# Map family name → candidate file stems (tried in order; first match wins)
_FAMILY_STEMS: dict = {
    "sans-serif":        ["LiberationSans-Regular", "DejaVuSans", "Ubuntu-R", "Arial", "FreeSans"],
    "serif":             ["LiberationSerif-Regular", "DejaVuSerif", "Georgia", "FreeSerif"],
    "monospace":         ["LiberationMono-Regular", "DejaVuSansMono", "CourierNew", "FreeMono"],
    "Arial":             ["Arial", "LiberationSans-Regular"],
    "Helvetica":         ["Helvetica", "LiberationSans-Regular"],
    "Verdana":           ["Verdana", "LiberationSans-Regular"],
    "Tahoma":            ["Tahoma", "LiberationSans-Regular"],
    "Trebuchet MS":      ["TrebuchetMS", "LiberationSans-Regular"],
    "Impact":            ["Impact", "LiberationSans-Regular"],
    "Comic Sans MS":     ["ComicSansMS", "LiberationSans-Regular"],
    "Georgia":           ["Georgia", "LiberationSerif-Regular"],
    "Times New Roman":   ["TimesNewRoman", "LiberationSerif-Regular"],
    "Palatino":          ["Palatino", "LiberationSerif-Regular"],
    "Garamond":          ["EBGaramond-Regular", "LiberationSerif-Regular"],
    "Courier New":       ["CourierNew", "LiberationMono-Regular"],
    "Liberation Sans":   ["LiberationSans-Regular", "LiberationSans"],
    "Liberation Serif":  ["LiberationSerif-Regular", "LiberationSerif"],
    "DejaVu Sans":       ["DejaVuSans", "DejaVuSans-Regular"],
    "DejaVu Serif":      ["DejaVuSerif", "DejaVuSerif-Regular"],
    "Arimo":             ["Arimo-Regular", "Arimo"],
    "Carlito":           ["Carlito-Regular", "Carlito"],
    "Caladea":           ["Caladea-Regular", "Caladea"],
    "Droid Serif":       ["DroidSerif-Regular", "DroidSerif"],
    "EB Garamond":       ["EBGaramond-Regular", "EBGaramond"],
    "Fira Sans":         ["FiraSans-Regular", "FiraSans"],
}

_BOLD_SUFFIXES =        ["-Bold", "Bold", "_Bold"]
_ITALIC_SUFFIXES =      ["-Italic", "Italic", "-Oblique", "Oblique"]
_BOLD_ITALIC_SUFFIXES = ["-BoldItalic", "BoldItalic", "-BoldOblique", "BoldOblique"]


def _find_font(family: str, bold: bool, italic: bool, size: int):
    """Return the best-matching TrueType font; falls back to load_default()."""
    stems = _FAMILY_STEMS.get(family, [family, "LiberationSans-Regular"])
    for stem in stems:
        # Strip trailing "-Regular" so we can reattach style suffixes cleanly
        base = stem
        for reg_suffix in ("-Regular", "_Regular"):
            if base.endswith(reg_suffix):
                base = base[: -len(reg_suffix)]
                break

        candidates: list = []
        if bold and italic:
            candidates += [base + s for s in _BOLD_ITALIC_SUFFIXES]
        if bold:
            candidates += [base + s for s in _BOLD_SUFFIXES]
        if italic:
            candidates += [base + s for s in _ITALIC_SUFFIXES]
        candidates.append(stem)  # plain / regular fallback

        for font_dir in _FONT_SEARCH_DIRS:
            for candidate in candidates:
                for ext in (".ttf", ".otf", ".ttc"):
                    path = os.path.join(font_dir, candidate + ext)
                    if os.path.exists(path):
                        try:
                            return ImageFont.truetype(path, size)
                        except (IOError, OSError):
                            continue
    return ImageFont.load_default()


def _hex_to_rgb(hex_color: str):
    """Parse '#rrggbb' → (r, g, b), defaulting to white on error."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (255, 255, 255)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return (255, 255, 255)


# ── Route ──────────────────────────────────────────────────────────────────────

@router.post("/watermark")
async def watermark_image(
    file: UploadFile,
    mode: str = Form("text"),
    # ── text mode params ──────────────────────────────────────────────────────
    text: Optional[str] = Form(None),
    x_pct: float = Form(50.0),      # 0–100: horizontal center as % of image width
    y_pct: float = Form(50.0),      # 0–100: vertical center as % of image height
    font_size: int = Form(36),
    opacity: int = Form(60),        # 10–100
    color: str = Form("#ffffff"),
    bold: bool = Form(False),
    italic: bool = Form(False),
    font_family: str = Form("sans-serif"),
    # ── image mode params ─────────────────────────────────────────────────────
    logo: Optional[UploadFile] = None,
    logo_x_pct: float = Form(0.25),  # 0–1: left edge as fraction of image width
    logo_y_pct: float = Form(0.25),  # 0–1: top edge as fraction of image height
    logo_w_pct: float = Form(0.5),   # 0–1: logo width as fraction of image width
    logo_h_pct: float = Form(0.5),   # 0–1: logo height as fraction of image height
    logo_opacity: int = Form(80),    # 10–100
):
    """Add a text or image watermark to an image."""
    raw = await file.read()
    img = _open_image(raw)
    orig_fmt = img.format or "PNG"
    fmt = orig_fmt.lower()

    try:
        if mode == "image":
            # ── Image watermark ────────────────────────────────────────────
            if logo is None:
                raise HTTPException(
                    status_code=400,
                    detail="A logo file is required for image watermark mode.",
                )
            logo_raw = await logo.read()
            logo_img = _open_image(logo_raw)

            iw, ih = img.size
            logo_w = max(1, int(iw * logo_w_pct))
            logo_h = max(1, int(ih * logo_h_pct))
            logo_x = int(iw * logo_x_pct)
            logo_y = int(ih * logo_y_pct)

            logo_resized = logo_img.resize((logo_w, logo_h), Image.LANCZOS)

            # Apply opacity to the logo's alpha channel
            alpha_val = int(255 * max(10, min(100, logo_opacity)) / 100)
            if logo_resized.mode != "RGBA":
                logo_resized = logo_resized.convert("RGBA")
            r_ch, g_ch, b_ch, a_ch = logo_resized.split()
            a_ch = a_ch.point(lambda v: int(v * alpha_val / 255))
            logo_resized = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

            base = img.convert("RGBA")
            base.paste(logo_resized, (logo_x, logo_y), logo_resized)
            if fmt in ("jpeg", "jpg"):
                base = base.convert("RGB")
            encoded = _encode(base, fmt)

        else:
            # ── Text watermark ─────────────────────────────────────────────
            if not text or not text.strip():
                raise HTTPException(status_code=400, detail="Watermark text is required.")
            if not 8 <= font_size <= 120:
                raise HTTPException(
                    status_code=400, detail="font_size must be between 8 and 120."
                )

            alpha_val = int(255 * max(10, min(100, opacity)) / 100)
            r_val, g_val, b_val = _hex_to_rgb(color)
            font = _find_font(font_family, bold, italic, font_size)

            base = img.convert("RGBA")
            overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)

            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]

            iw, ih = base.size
            # x_pct / y_pct is the CENTER of the text (0–100)
            cx = int(iw * x_pct / 100)
            cy = int(ih * y_pct / 100)
            tx = cx - text_w // 2
            ty = cy - text_h // 2

            draw.text((tx, ty), text, font=font, fill=(r_val, g_val, b_val, alpha_val))
            watermarked = Image.alpha_composite(base, overlay)
            if fmt in ("jpeg", "jpg"):
                watermarked = watermarked.convert("RGB")
            encoded = _encode(watermarked, fmt)

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Watermark failed: {exc}")

    ext = _FORMAT_EXT.get(fmt, fmt)
    return _response(encoded, fmt, f"watermarked.{ext}")
