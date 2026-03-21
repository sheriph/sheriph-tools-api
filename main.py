import json
import io
from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
import fitz  # PyMuPDF

app = FastAPI(title="PyMuPDF Edit Service", version="1.0.0")

# Configure CORS to allow Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "PyMuPDF Edit Service"}


@app.post("/api/edit-pdf")
async def edit_pdf(
    file: UploadFile,
    edits: str = Form(...)
):
    """
    Edit a PDF file based on provided instructions.

    Args:
        file: The PDF file to edit
        edits: JSON string containing edit instructions
               Format: [{"page": 0, "rect": [x0, y0, x1, y1], "text": "New text", "font_size": 12}]

    Returns:
        Modified PDF file
    """
    try:
        # Validate file type
        if not file.filename.endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        # Parse the edits JSON
        try:
            edits_list = json.loads(edits)
            if not isinstance(edits_list, list):
                raise ValueError("Edits must be an array")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in edits: {str(e)}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Read the uploaded PDF file
        pdf_bytes = await file.read()

        # Open PDF with PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        # Process each edit instruction
        for idx, edit in enumerate(edits_list):
            try:
                # Validate edit structure
                if not all(key in edit for key in ["page", "rect", "text", "font_size"]):
                    raise ValueError(f"Edit {idx} missing required fields")

                page_num = edit["page"]
                rect_coords = edit["rect"]
                text = edit["text"]
                font_size = edit["font_size"]

                # Validate page number
                if page_num < 0 or page_num >= len(doc):
                    raise ValueError(f"Page {page_num} out of range (document has {len(doc)} pages)")

                # Get the page
                page = doc[page_num]

                # Create rectangle from coordinates
                if not isinstance(rect_coords, list) or len(rect_coords) != 4:
                    raise ValueError(f"Edit {idx}: rect must be [x0, y0, x1, y1]")

                rect = fitz.Rect(rect_coords)

                # Use a Shape so the white cover rect and replacement text
                # are written in one atomic content stream entry, eliminating
                # any layer-ordering race between erase and new text.
                shape = page.new_shape()

                # 1. White rectangle erases the original text
                shape.draw_rect(rect)
                shape.finish(fill=(1, 1, 1), color=(1, 1, 1), width=0)

                # 2. Replacement text at the baseline of the rect.
                #    insert_text never fails due to insufficient rect height.
                baseline_y = rect.y0 + font_size
                shape.insert_text(
                    fitz.Point(rect.x0, baseline_y),
                    text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )

                shape.commit()

            except (KeyError, ValueError, IndexError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error processing edit {idx}: {str(e)}"
                )

        # Save the modified PDF to a byte stream
        output_stream = io.BytesIO()
        doc.save(output_stream, garbage=3, deflate=True)
        doc.close()

        # Get the bytes and return as response
        output_stream.seek(0)
        pdf_output = output_stream.read()

        return Response(
            content=pdf_output,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=edited_{file.filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF processing failed: {str(e)}"
        )


@app.post("/api/extract-text")
async def extract_text(file: UploadFile):
    """
    Extract text spans and coordinates from a PDF using PyMuPDF.

    Returns:
        {
            "success": bool,
            "text_items": [
                {
                    "text": str,
                    "bbox": [x0, y0, x1, y1],
                    "font_size": float,
                    "font_name": str,
                    "page": int,
                }
            ],
            "page_dimensions": [
                {"page": int, "width": float, "height": float}
            ]
        }
    """
    try:
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        text_items = []
        page_dimensions = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_dimensions.append(
                {
                    "page": page_num,
                    "width": float(page.rect.width),
                    "height": float(page.rect.height),
                }
            )

            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = (span.get("text") or "").strip()
                        if not text:
                            continue

                        bbox = span.get("bbox", [0, 0, 0, 0])
                        text_items.append(
                            {
                                "text": text,
                                "bbox": [float(v) for v in bbox],
                                "font_size": float(span.get("size", 0)),
                                "font_name": span.get("font", ""),
                                "page": page_num,
                            }
                        )

        doc.close()

        return {
            "success": True,
            "text_items": text_items,
            "page_dimensions": page_dimensions,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Text extraction failed: {str(e)}"
        )


@app.post("/api/add-signatures")
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
    import base64 as _base64

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

                img_bytes = _base64.b64decode(sig["image_data"])
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


@app.post("/api/redact-pdf")
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
