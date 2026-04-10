from unittest.mock import patch, MagicMock


def test_chat_streams_response():
    from app.main import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    async def fake_astream(state, stream_mode=None):
        for token in ["The", " document", " looks", " risky."]:
            mock = MagicMock()
            mock.content = token
            yield mock

    with patch("app.api.chat.get_llm") as mock_llm_fn, \
         patch("app.api.chat.load_state_from_history") as mock_history, \
         patch("app.api.chat.persist_message"):

        mock_llm_fn.return_value = MagicMock()
        mock_history.return_value = {
            "messages": [],
            "document_context": "Risk: HIGH",
            "session_id": "550e8400-e29b-41d4-a716-446655440000",
            "summary": "",
        }

        with patch("app.api.chat._get_graph") as mock_graph_fn:
            mock_graph = MagicMock()
            mock_graph.astream = fake_astream
            mock_graph_fn.return_value = mock_graph

            response = client.post(
                "/chat/550e8400-e29b-41d4-a716-446655440000",
                json={
                    "message": "Is this document safe?",
                    "session_id": "550e8400-e29b-41d4-a716-446655440000",
                    "document_context": "Risk: HIGH"
                },
            )

    assert response.status_code == 200
