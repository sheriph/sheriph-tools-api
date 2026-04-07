from fastapi import APIRouter

from .download import router as download_router
from .audio import router as audio_router
from .thumbnail import router as thumbnail_router
from .metadata import router as metadata_router
from .subtitles import router as subtitle_router
from .clip import router as clip_router

router = APIRouter()
router.include_router(download_router)
router.include_router(audio_router)
router.include_router(thumbnail_router)
router.include_router(metadata_router)
router.include_router(subtitle_router)
router.include_router(clip_router)
