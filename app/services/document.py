import base64
import io
import mimetypes
from fastapi import UploadFile, HTTPException

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

DOCX_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _extract_docx_text(content: bytes) -> str:
    """Extract plain text from a .doc/.docx file."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also grab table cell text
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text.strip():
                        paragraphs.append(cell.text.strip())
        return "\n\n".join(paragraphs)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read Word document: {e}")


async def process_upload(file: UploadFile) -> tuple[str, str]:
    """
    Returns (payload, mime_type).
    - For binary files (PDF/image): payload is base64-encoded bytes.
    - For Word docs: payload is extracted plain text, mime_type is 'text/plain'.
    """
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 100MB.")

    mime_type = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""

    # Normalise .doc guessed as octet-stream by filename
    filename = (file.filename or "").lower()
    if mime_type == "application/octet-stream":
        if filename.endswith(".docx"):
            mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        elif filename.endswith(".doc"):
            mime_type = "application/msword"

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {mime_type}. Accepted: PDF, JPEG, PNG, WEBP, HEIC, DOC, DOCX."
        )

    if mime_type in DOCX_MIME_TYPES:
        text = _extract_docx_text(content)
        return text, "text/plain"

    return base64.b64encode(content).decode("utf-8"), mime_type
