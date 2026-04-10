import base64
import mimetypes
from fastapi import UploadFile, HTTPException

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


async def process_upload(file: UploadFile) -> tuple[str, str]:
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 100MB.")

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {mime_type}. Accepted: PDF, JPEG, PNG, WEBP, HEIC.")

    return base64.b64encode(content).decode("utf-8"), mime_type
