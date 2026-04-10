import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock
from app.services.document import process_upload, ALLOWED_MIME_TYPES


@pytest.mark.asyncio
async def test_process_upload_valid_pdf():
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"%PDF-1.4 fake content")
    mock_file.content_type = "application/pdf"
    mock_file.filename = "title.pdf"

    b64, mime = await process_upload(mock_file)
    assert mime == "application/pdf"
    assert len(b64) > 0


@pytest.mark.asyncio
async def test_process_upload_rejects_unsupported_type():
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"some content")
    mock_file.content_type = "text/plain"
    mock_file.filename = "notes.txt"

    with pytest.raises(HTTPException) as exc:
        await process_upload(mock_file)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_process_upload_rejects_oversized_file():
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(return_value=b"x" * (101 * 1024 * 1024))
    mock_file.content_type = "application/pdf"
    mock_file.filename = "huge.pdf"

    with pytest.raises(HTTPException) as exc:
        await process_upload(mock_file)
    assert exc.value.status_code == 400
