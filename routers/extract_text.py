import fitz
from fastapi import APIRouter, UploadFile, HTTPException

router = APIRouter()


@router.post("/api/extract-text")
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
