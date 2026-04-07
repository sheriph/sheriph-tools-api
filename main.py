try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv() -> bool:
        return False

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import edit_pdf, extract_text, add_signatures, redact_pdf, image, video, pymupdf4llm_extract

app = FastAPI(title="PyMuPDF Edit Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(edit_pdf.router)
app.include_router(extract_text.router)
app.include_router(add_signatures.router)
app.include_router(redact_pdf.router)
app.include_router(image.router, prefix="/api/image")
app.include_router(video.router, prefix="/api/video")
app.include_router(pymupdf4llm_extract.router)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "PyMuPDF Edit Service"}

