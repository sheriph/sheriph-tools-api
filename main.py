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

                # Redact (erase) the underlying text
                page.add_redact_annot(rect)
                page.apply_redactions()

                # Insert new text at the specified location
                page.insert_textbox(
                    rect,
                    text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                    align=0  # Left align
                )

            except (KeyError, ValueError, IndexError) as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error processing edit {idx}: {str(e)}"
                )

        # Save the modified PDF to a byte stream
        output_stream = io.BytesIO()
        doc.save(output_stream)
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
