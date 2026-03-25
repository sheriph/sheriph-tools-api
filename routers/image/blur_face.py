import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, UploadFile, Form
from fastapi.responses import Response

router = APIRouter()


@router.post("/blur-face")
async def blur_face(
    file: UploadFile,
    blur_strength: int = Form(25),
):
    """Detect faces in an image and blur them using OpenCV Haar cascades."""
    if not 1 <= blur_strength <= 50:
        raise HTTPException(status_code=400, detail="blur_strength must be between 1 and 50")

    raw = await file.read()

    try:
        import os as _os

        cascade_path = _os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        face_cascade = cv2.CascadeClassifier(cascade_path)

        arr = np.frombuffer(raw, dtype=np.uint8)
        img_bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img_bgr is None:
            raise HTTPException(status_code=400, detail="Invalid or corrupted image file")

        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        kernel = blur_strength * 2 + 1
        for (x, y, w, h) in faces:
            face_region = img_bgr[y : y + h, x : x + w]
            blurred = cv2.GaussianBlur(face_region, (kernel, kernel), 0)
            img_bgr[y : y + h, x : x + w] = blurred

        original_name = (file.filename or "image.jpg").lower()
        if original_name.endswith(".png"):
            ext, mime = "png", "image/png"
            success, encoded_arr = cv2.imencode(".png", img_bgr)
        elif original_name.endswith(".webp"):
            ext, mime = "webp", "image/webp"
            success, encoded_arr = cv2.imencode(".webp", img_bgr)
        else:
            ext, mime = "jpg", "image/jpeg"
            success, encoded_arr = cv2.imencode(".jpg", img_bgr, [cv2.IMWRITE_JPEG_QUALITY, 92])

        if not success:
            raise HTTPException(status_code=400, detail="Failed to encode output image")

        output_bytes = encoded_arr.tobytes()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Face blur failed: {exc}")

    return Response(
        content=output_bytes,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="blurred-faces.{ext}"'},
    )
