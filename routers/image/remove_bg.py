from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response
from rembg import remove

router = APIRouter()


@router.post("/remove-bg")
async def remove_background(file: UploadFile):
    """Remove the background from an image using rembg."""
    try:
        input_bytes = await file.read()
        output_bytes = remove(input_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Background removal failed: {exc}")

    return Response(
        content=output_bytes,
        media_type="image/png",
        headers={"Content-Disposition": 'attachment; filename="removed-bg.png"'},
    )
