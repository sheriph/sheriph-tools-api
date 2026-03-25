from fastapi import APIRouter

from .compress import router as compress_router
from .resize import router as resize_router
from .crop import router as crop_router
from .rotate import router as rotate_router
from .convert import router as convert_router
from .watermark import router as watermark_router
from .remove_bg import router as remove_bg_router
from .upscale import router as upscale_router
from .blur_face import router as blur_face_router

router = APIRouter()
router.include_router(compress_router)
router.include_router(resize_router)
router.include_router(crop_router)
router.include_router(rotate_router)
router.include_router(convert_router)
router.include_router(watermark_router)
router.include_router(remove_bg_router)
router.include_router(upscale_router)
router.include_router(blur_face_router)
