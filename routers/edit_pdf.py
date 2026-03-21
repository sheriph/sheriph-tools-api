import json
import io
import fitz
from fastapi import APIRouter, UploadFile, Form, HTTPException
from fastapi.responses import Response

router = APIRouter()


@router.post("/api/edit-pdf")
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
        if not file.filename.endswith('.pdf'):
            raise HTTPException(status_code=400, detail="File must be a PDF")

        try:
            edits_list = json.loads(edits)
            if not isinstance(edits_list, list):
                raise ValueError("Edits must be an array")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON in edits: {str(e)}")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        pdf_bytes = await file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        for idx, edit in enumerate(edits_list):
            try:
                if not all(key in edit for key in ["page", "rect", "text", "font_size"]):
                    raise ValueError(f"Edit {idx} missing required fields")

                page_num = edit["page"]
                rect_coords = edit["rect"]
                text = edit["text"]
                font_size = edit["font_size"]

                if page_num < 0 or page_num >= len(doc):
                    raise ValueError(f"Page {page_num} out of range (document has {len(doc)} pages)")

                page = doc[page_num]

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

        output_stream = io.BytesIO()
        doc.save(output_stream, garbage=3, deflate=True)
        doc.close()

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
