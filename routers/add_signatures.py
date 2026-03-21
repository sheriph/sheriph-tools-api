import base64
import io
import json
import fitz
from fastapi import APIRouter, UploadFile, Form, HTTPException
from fastapi.responses import Response

router = APIRouter()


@router.post("/api/add-signatures")
async def add_signatures(
    file: UploadFile,
    signatures: str = Form(...)
):
    """
    Add image-based signatures to a PDF file.

    Args:
        file: The PDF file to sign
        signatures: JSON string array:
                    [{"page": 0, "x_pct": 0.1, "y_pct": 0.8,
                      "w_pct": 0.25, "h_pct": 0.10,
                      "image_data": "<base64-png-without-prefix>"}]

    Returns:
        Signed PDF file
    """
    try:
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        try:
            sigs = json.loads(signatures)
            if not isinstance(sigs, list):
                raise ValueError("signatures must be an array")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in signatures: {str(e)}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if len(sigs) == 0:
            raise HTTPException(status_code=400, detail="At least one signature is required")

        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for idx, sig in enumerate(sigs):
            try:
                required = ["page", "x_pct", "y_pct", "w_pct", "h_pct", "image_data"]
                if not all(k in sig for k in required):
                    raise ValueError(f"Signature {idx} missing required fields")

                page_num = sig["page"]
                if page_num < 0 or page_num >= len(doc):
                    raise ValueError(f"Page {page_num} out of range (document has {len(doc)} pages)")

                page = doc[page_num]
                w = page.rect.width
                h = page.rect.height

                x0 = sig["x_pct"] * w
                y0 = sig["y_pct"] * h
                x1 = (sig["x_pct"] + sig["w_pct"]) * w
                y1 = (sig["y_pct"] + sig["h_pct"]) * h
                rect = fitz.Rect(x0, y0, x1, y1)

                img_bytes = base64.b64decode(sig["image_data"])
                page.insert_image(rect, stream=img_bytes, overlay=True)

            except (KeyError, ValueError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error processing signature {idx}: {str(e)}"
                )

        output_stream = io.BytesIO()
        doc.save(output_stream, garbage=3, deflate=True)
        doc.close()

        output_stream.seek(0)
        pdf_output = output_stream.read()

        return Response(
            content=pdf_output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=signed_{file.filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF signing failed: {str(e)}"
        )
