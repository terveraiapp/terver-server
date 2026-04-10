import io
from unittest.mock import patch, MagicMock


def test_analyze_returns_stream():
    from app.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    async def fake_astream(messages):
        for token in ['{"risk_score":', ' "LOW",', ' "overall_score": 10}']:
            mock = MagicMock()
            mock.content = token
            yield mock

    with patch("app.api.analyze.get_llm") as mock_get_llm:
        mock_llm = MagicMock()
        mock_llm.astream = fake_astream
        mock_get_llm.return_value = mock_llm

        pdf_bytes = b"%PDF-1.4 fake"
        response = client.post(
            "/analyze",
            files={"file": ("test.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
        )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


def test_analyze_rejects_invalid_file():
    from app.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    response = client.post(
        "/analyze",
        files={"file": ("notes.txt", io.BytesIO(b"some text"), "text/plain")},
    )
    assert response.status_code == 400
