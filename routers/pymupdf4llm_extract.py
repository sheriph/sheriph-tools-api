import asyncio
import base64
import io
import os

import fitz
import httpx
import pymupdf4llm
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi import Form
from typing import Optional

router = APIRouter()

# ─── Zhipu Vision Config ──────────────────────────────────────────────────────
ZHIPU_API_KEY = os.environ.get("ZHIPU_API_KEY", "")
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
VISION_MODEL = "glm-4.6v-flash"   # free vision model (32K output); glm-4.7-flash is text-only

# ─── Scan-detection thresholds ────────────────────────────────────────────────
TEXT_THRESHOLD = 100       # chars — below this AND no fonts → scanned
OCR_PAGE_LIMIT = 5          # max pages to process with LLM vision OCR (cost control)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def format_vision_error(exc: Exception) -> str:
    """Return a compact, useful error string for failed vision OCR requests."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = f"{exc.response.status_code} {exc.response.reason_phrase}".strip()
        body = exc.response.text.strip()
        return f"{status}: {body}" if body else status

    if isinstance(exc, httpx.TimeoutException):
        return f"Vision request timed out: {exc}"

    if isinstance(exc, httpx.RequestError):
        return f"Vision request failed: {exc}"

    return str(exc)


def classify_page(page: fitz.Page) -> str:
    """
    Classifies a page as 'digital' or 'scanned'.

    Two-step check (ordered by reliability):

    1. Text content:  page.get_text() > 100 chars  → digital (or already has OCR layer)
    2. Fonts present: page.get_fonts() is non-empty → digital (has font data, even if sparse)

    If NEITHER condition is met (no meaningful text AND no fonts) the page is
    almost certainly a pure scanned image — route to vision OCR.

    The full-page-image area check is intentionally omitted: it has lower
    accuracy (~85-90%) and causes false positives on design-exported PDFs.
    """
    # 1. Primary: substantial extractable text → digital / pre-OCR'd
    text = page.get_text("text").strip()
    if len(text) > TEXT_THRESHOLD:
        return "digital"

    # 2. Secondary: fonts present → digital (could be sparse title/separator page)
    if page.get_fonts():
        return "digital"

    # 3. No text AND no fonts → pure scanned image
    return "scanned"


async def ocr_page_with_vision(
    client: httpx.AsyncClient,
    page: fitz.Page,
    page_index: int,
    max_retries: int = 4,
) -> str:
    """
    Renders a scanned page to a 200 DPI PNG and sends it to the Zhipu
    vision model for high-quality OCR.
    Retries up to max_retries times with exponential backoff on 429.
    Returns the extracted text as a string.
    """
    # Render page to PNG at 200 DPI (fitz default = 72 DPI, so scale = 200/72 ≈ 2.78)
    mat = fitz.Matrix(2.78, 2.78)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png_bytes = pix.tobytes("png")
    b64_image = base64.b64encode(png_bytes).decode("utf-8")

    payload = {
        "model": VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"This is page {page_index + 1} of a scanned document. "
                            "Extract ALL text from this image exactly as it appears, preserving "
                            "the logical reading order and document structure. "
                            "For form fields, output: 'Field Name: Value'. "
                            "For tables, output as a markdown table. "
                            "Output only the extracted text — no explanations or commentary."
                        ),
                    },
                ],
            }
        ],
        "max_tokens": 2048,
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = await client.post(
                f"{ZHIPU_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {ZHIPU_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code == 429:
                wait = 2 ** attempt  # 1s, 2s, 4s, 8s
                print(f"[vision] page {page_index + 1}: 429 rate-limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(wait)
                last_exc = httpx.HTTPStatusError(
                    f"429 Too Many Requests: {response.text}",
                    request=response.request,
                    response=response,
                )
                continue
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 2 ** attempt
                print(f"[vision] page {page_index + 1}: 429 rate-limited, retrying in {wait}s")
                await asyncio.sleep(wait)
                last_exc = e
                continue
            raise
    raise last_exc or RuntimeError("Vision OCR failed after retries")


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/api/pymupdf4llm")
async def extract_markdown(
    file: UploadFile,
    pages_per_chunk: Optional[int] = Form(None),
    force_legacy: bool = Form(False),
    force_vision: bool = Form(False),
):
    """
    Smart PDF text extraction with per-page scan detection.

    - Digital pages  → pymupdf4llm (fast, structured markdown, tables preserved)
    - Scanned pages  → Zhipu GLM-4.7-flash vision model (high-quality OCR)
    - Scanned-page vision calls run concurrently for speed.
    - Falls back to pymupdf4llm-only if ZHIPU_API_KEY is not configured.
    - force_legacy=True skips scan detection and routes all pages through pymupdf4llm.

    Returns:
        {
            "success": bool,
            "chunks": [str],
            "pageCount": int,
            "usedOCR": bool,          # true if any vision OCR was triggered
            "scannedPages": [int],    # 0-indexed page numbers processed by vision
            "visionErrors": {         # per-page vision failures, if any
                "<pageIndex>": "error details"
            },
            "pageAnalysis": [         # per-page classification details
                {
                    "pageIndex": int,
                    "type": "digital" | "scanned",
                    "method": "pymupdf4llm" | "vision" | "vision_fallback",
                    "textLength": int,
                    "visionError": str | None,
                }
            ],
            "metadata": {...}
        }
    """
    try:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)
        chunk_size = pages_per_chunk if pages_per_chunk and pages_per_chunk > 0 else 20

        # ── Phase 1: Classify every page ──────────────────────────────────────
        if force_legacy:
            # Legacy mode: treat every page as digital (pymupdf4llm only)
            page_types = ["digital"] * page_count
        elif force_vision:
            # Force-vision mode: treat every page as scanned (Zhipu Vision for all)
            page_types = ["scanned"] * page_count
        else:
            page_types = [classify_page(doc[i]) for i in range(page_count)]

        scanned_indices = [i for i, t in enumerate(page_types) if t == "scanned"]
        digital_indices = [i for i, t in enumerate(page_types) if t == "digital"]
        # Split scanned pages: only first OCR_PAGE_LIMIT get vision OCR; rest are skipped
        scanned_to_ocr = [i for i in scanned_indices if i < OCR_PAGE_LIMIT]
        scanned_skipped = [i for i in scanned_indices if i >= OCR_PAGE_LIMIT]
        use_vision = bool(scanned_to_ocr) and (force_vision or bool(ZHIPU_API_KEY)) and (not force_legacy)
        print(
            "[debug-ocr] "
            f"force_legacy={force_legacy} "
            f"force_vision={force_vision} "
            f"use_vision={use_vision} "
            f"ZHIPU_API_KEY_set={bool(ZHIPU_API_KEY)} "
            f"scanned={scanned_indices}"
        )

        # ── Phase 2: Build per-page text dict ─────────────────────────────────
        page_texts: dict[int, str] = {}
        # Track which method was actually used per page
        page_methods: dict[int, str] = {}
        page_errors: dict[int, str] = {}

        # Digital pages via pymupdf4llm (per-page calls; local so fast)
        for i in digital_indices:
            try:
                md = pymupdf4llm.to_markdown(doc, pages=[i], header=False, footer=False)
                page_texts[i] = md
                page_methods[i] = "pymupdf4llm"
            except Exception as e:
                page_texts[i] = f"<!-- pymupdf4llm failed for page {i + 1}: {e} -->"
                page_methods[i] = "pymupdf4llm"

        # Scanned pages beyond OCR limit — insert placeholder (no vision OCR)
        for i in scanned_skipped:
            page_texts[i] = f"<!-- Page {i + 1}: Scanned image — LLM OCR skipped (page limit of {OCR_PAGE_LIMIT} reached). Content not extracted. -->"
            page_methods[i] = "skipped"

        # Scanned pages via Zhipu vision (sequential to respect free-tier rate limits)
        if use_vision:
            async with httpx.AsyncClient(timeout=120.0) as client:
                results = []
                for idx, i in enumerate(scanned_to_ocr):
                    if idx > 0:
                        await asyncio.sleep(1)  # 1s pause between pages
                    try:
                        result = await ocr_page_with_vision(client, doc[i], i)
                        results.append(result)
                    except Exception as exc:
                        results.append(exc)
                for i, result in zip(scanned_to_ocr, results):
                    if isinstance(result, Exception):
                        # Vision failed — fall back to pymupdf4llm for this page
                        err_str = format_vision_error(result)
                        print(f"[debug-ocr] Vision OCR failed for page {i + 1}: {err_str}")
                        page_errors[i] = err_str
                        try:
                            md = pymupdf4llm.to_markdown(doc, pages=[i], header=False, footer=False)
                            page_texts[i] = md
                            page_methods[i] = "vision_fallback"
                        except Exception as fe:
                            page_texts[i] = f"<!-- OCR failed for page {i + 1}: {fe} -->"
                            page_methods[i] = "vision_fallback"
                    else:
                        page_texts[i] = f"## Page {i + 1} (Vision OCR)\n\n{result}"
                        page_methods[i] = "vision"
        else:
            # No vision (force_legacy, no key, or no scanned pages) — use pymupdf4llm for scanned too
            for i in scanned_to_ocr:
                try:
                    md = pymupdf4llm.to_markdown(doc, pages=[i], header=False, footer=False)
                    page_texts[i] = md
                    page_methods[i] = "pymupdf4llm"
                except Exception as e:
                    page_texts[i] = f"<!-- pymupdf4llm failed for page {i + 1}: {e} -->"
                    page_methods[i] = "pymupdf4llm"

        # ── Phase 3: Assemble into chunks ─────────────────────────────────────
        chunks: list[str] = []
        for start in range(0, page_count, chunk_size):
            end = min(start + chunk_size, page_count)
            chunk = "\n\n---\n\n".join(page_texts.get(p, "") for p in range(start, end))
            chunks.append(chunk)

        # Append a tail note if any scanned pages were skipped due to OCR limit
        if scanned_skipped:
            first_skipped = scanned_skipped[0] + 1  # 1-indexed
            last_skipped = scanned_skipped[-1] + 1
            range_str = str(first_skipped) if first_skipped == last_skipped else f"{first_skipped}–{last_skipped}"
            chunks[-1] += (
                f"\n\n---\n\n"
                f"**[EXTRACTION NOTE — Pages {range_str} skipped]**\n"
                f"This document has {page_count} pages. Pages {range_str} are scanned images and were "
                f"not processed by LLM OCR (cost limit: first {OCR_PAGE_LIMIT} scanned pages only). "
                f"Their content is unknown. "
                f"If this is a bank statement or multi-page financial document, request a digital PDF export — "
                f"not a scan — so all pages can be extracted without OCR charges."
            )

        # ── Phase 4: Build per-page analysis ──────────────────────────────────
        page_analysis = [
            {
                "pageIndex": i,
                "type": page_types[i],
                "method": page_methods.get(i, "pymupdf4llm"),
                "textLength": len(page_texts.get(i, "")),
                "visionError": page_errors.get(i),
            }
            for i in range(page_count)
        ]

        metadata = doc.metadata or {}
        doc.close()

        return {
            "success": True,
            "chunks": chunks,
            "pageCount": page_count,
            "usedOCR": use_vision,
            "scannedPages": scanned_to_ocr,
            "skippedOcrPages": scanned_skipped,
            "visionErrors": {str(k): v for k, v in page_errors.items()},
            "pageAnalysis": page_analysis,
            "metadata": {
                "title": metadata.get("title", ""),
                "author": metadata.get("author", ""),
                "subject": metadata.get("subject", ""),
                "creator": metadata.get("creator", ""),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF extraction failed: {str(e)}",
        )
