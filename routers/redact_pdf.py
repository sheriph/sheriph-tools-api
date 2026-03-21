import json
import fitz
from fastapi import APIRouter, UploadFile, Form, HTTPException
from fastapi.responses import Response

router = APIRouter()


@router.post("/api/redact-pdf")
async def redact_pdf(
    file: UploadFile,
    redactions: str = Form(...)
):
    """
    Permanently redact areas of a PDF with black rectangles.

    Args:
        file: The PDF file to redact
        redactions: JSON string array:
                    [{"page": 0, "x_pct": 0.1, "y_pct": 0.2,
                      "w_pct": 0.4, "h_pct": 0.05}]

    Returns:
        Redacted PDF file
    """
    try:
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        try:
            marks = json.loads(redactions)
            if not isinstance(marks, list):
                raise ValueError("redactions must be an array")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in redactions: {str(e)}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if len(marks) == 0:
            raise HTTPException(status_code=400, detail="At least one redaction is required")

        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for idx, m in enumerate(marks):
            try:
                required = ["page", "x_pct", "y_pct", "w_pct", "h_pct"]
                if not all(k in m for k in required):
                    raise ValueError(f"Redaction {idx} missing required fields")

                page_num = m["page"]
                if page_num < 0 or page_num >= len(doc):
                    raise ValueError(f"Page {page_num} out of range (document has {len(doc)} pages)")

                page = doc[page_num]
                w = page.rect.width
                h = page.rect.height

                rect = fitz.Rect(
                    m["x_pct"] * w,
                    m["y_pct"] * h,
                    (m["x_pct"] + m["w_pct"]) * w,
                    (m["y_pct"] + m["h_pct"]) * h,
                )
                page.add_redact_annot(rect, fill=(0, 0, 0))

            except (KeyError, ValueError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error processing redaction {idx}: {str(e)}"
                )

        for page in doc:
            page.apply_redactions()

        buf = doc.tobytes(garbage=4, deflate=True)
        doc.close()

        return Response(
            content=buf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=redacted_{file.filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF redaction failed: {str(e)}"
        )
