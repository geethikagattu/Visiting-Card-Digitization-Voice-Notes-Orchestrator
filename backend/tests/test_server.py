from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

import src.server as server


client = TestClient(server.app)


def fake_tool(value):
    return Mock(invoke=Mock(return_value=value))


def test_health_and_session():
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/chat/session")
    assert response.status_code == 200
    assert response.json()["session_id"]


def test_card_then_audio_keeps_sheet_row(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    monkeypatch.setattr(
        server,
        "extract_card_details",
        fake_tool(
            {
                "name": "Test User",
                "email": "test@example.com",
                "phone": "9999999999",
                "company": "Example",
            }
        ),
    )
    monkeypatch.setattr(server, "check_duplicate", fake_tool({"is_duplicate": False}))
    monkeypatch.setattr(server, "log_contact", fake_tool({"status": "logged", "row_id": 2}))
    monkeypatch.setattr(server, "notify_whatsapp", fake_tool({"status": "sent"}))

    card = client.post(
        f"/chat/{session_id}/upload-image",
        files={"image": ("card.jpg", b"fake image", "image/jpeg")},
    )
    assert card.status_code == 200
    assert card.json()["last_sheet_row_id"] == 2

    monkeypatch.setattr(server, "transcribe_voice_note", fake_tool("Conference notes"))
    monkeypatch.setattr(server, "update_contact_audio", fake_tool({"status": "updated"}))
    monkeypatch.setattr(
        server,
        "upload_to_cloudinary",
        AsyncMock(return_value="https://res.cloudinary.com/demo/video/upload/note.wav"),
    )
    audio = client.post(
        f"/chat/{session_id}/upload-audio",
        files={"audio": ("note.wav", b"fake audio", "audio/wav")},
    )
    assert audio.status_code == 200
    assert audio.json()["last_sheet_row_id"] == 2
    assert audio.json()["transcript"] == "Conference notes"


def test_image_upload_reports_missing_logged_row_id(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    monkeypatch.setattr(
        server,
        "extract_card_details",
        fake_tool(
            {
                "name": "Test User",
                "email": "test@example.com",
                "phone": "9999999999",
                "company": "Example",
            }
        ),
    )
    monkeypatch.setattr(server, "check_duplicate", fake_tool({"is_duplicate": False}))
    monkeypatch.setattr(server, "log_contact", fake_tool({"status": "logged"}))

    response = client.post(
        f"/chat/{session_id}/upload-image",
        files={"image": ("card.jpg", b"fake image", "image/jpeg")},
    )

    assert response.status_code == 502
    assert "did not return a row_id" in response.json()["detail"]


def test_image_upload_reports_empty_tool_error(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    monkeypatch.setattr(
        server,
        "extract_card_details",
        fake_tool(
            {
                "name": "Test User",
                "email": "test@example.com",
                "phone": "9999999999",
                "company": "Example",
            }
        ),
    )
    monkeypatch.setattr(server, "check_duplicate", fake_tool({"is_duplicate": False}))
    monkeypatch.setattr(server, "log_contact", fake_tool({"error": ""}))

    response = client.post(
        f"/chat/{session_id}/upload-image",
        files={"image": ("card.jpg", b"fake image", "image/jpeg")},
    )

    assert response.status_code == 502
    assert "Tool failed without an error message" in response.json()["detail"]


def test_image_upload_reports_gemini_quota_as_rate_limit(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    monkeypatch.setattr(
        server,
        "extract_card_details",
        fake_tool(
            {
                "error": (
                    "429 RESOURCE_EXHAUSTED. Quota exceeded for metric: "
                    "generativelanguage.googleapis.com/generate_content_free_tier_requests. "
                    "Please retry in 12.9750747s."
                )
            }
        ),
    )

    response = client.post(
        f"/chat/{session_id}/upload-image",
        files={"image": ("card.jpg", b"fake image", "image/jpeg")},
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "12"
    assert "Gemini card extraction failed" in response.json()["detail"]


def test_audio_requires_a_card_first():
    session_id = client.post("/chat/session").json()["session_id"]
    response = client.post(
        f"/chat/{session_id}/upload-audio",
        files={"audio": ("note.wav", b"fake audio", "audio/wav")},
    )
    assert response.status_code == 409


def test_tool_error_detail_includes_provider_response():
    detail = server.tool_error_detail(
        {
            "error": "WhatsApp API returned 401",
            "response": '{"error":{"message":"Invalid OAuth access token"}}',
        }
    )

    assert "WhatsApp API returned 401" in detail
    assert "Invalid OAuth access token" in detail


def test_audio_requires_cloudinary_url_before_sheet_update(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    config = {"configurable": {"thread_id": session_id}}
    server.graph.update_state(
        config,
        {
            **server.initial_state(session_id),
            "last_sheet_row_id": 3,
        },
    )

    async def failed_upload(*args, **kwargs):
        raise server.HTTPException(status_code=500, detail="Cloudinary upload failed: missing config")

    monkeypatch.setattr(server, "transcribe_voice_note", fake_tool("Follow up tomorrow"))
    update_contact_audio = Mock(invoke=Mock(return_value={"status": "updated"}))
    monkeypatch.setattr(server, "update_contact_audio", update_contact_audio)
    monkeypatch.setattr(server, "upload_to_cloudinary", failed_upload)

    response = client.post(
        f"/chat/{session_id}/upload-audio",
        files={"audio": ("note.wav", b"fake audio", "audio/wav")},
    )

    assert response.status_code == 500
    assert "Cloudinary upload failed" in response.json()["detail"]
    update_contact_audio.invoke.assert_not_called()


def test_audio_updates_sheet_with_cloudinary_url(monkeypatch):
    session_id = client.post("/chat/session").json()["session_id"]
    config = {"configurable": {"thread_id": session_id}}
    server.graph.update_state(
        config,
        {
            **server.initial_state(session_id),
            "last_sheet_row_id": 3,
        },
    )
    updated_calls = []

    def update_audio(payload):
        updated_calls.append(payload)
        return {"status": "updated"}

    monkeypatch.setattr(server, "transcribe_voice_note", fake_tool("Follow up tomorrow"))
    monkeypatch.setattr(server, "update_contact_audio", Mock(invoke=Mock(side_effect=update_audio)))
    monkeypatch.setattr(
        server,
        "upload_to_cloudinary",
        AsyncMock(return_value="https://res.cloudinary.com/demo/video/upload/follow-up.webm"),
    )

    response = client.post(
        f"/chat/{session_id}/upload-audio",
        files={"audio": ("note.webm", b"fake audio", "audio/webm")},
    )

    assert response.status_code == 200
    assert response.json()["transcript"] == "Follow up tomorrow"
    assert response.json()["audio_url"] == "https://res.cloudinary.com/demo/video/upload/follow-up.webm"
    assert updated_calls[0]["row_index"] == 3
    assert updated_calls[0]["audio_url"] == "https://res.cloudinary.com/demo/video/upload/follow-up.webm"
    assert updated_calls[0]["transcript"] == "Follow up tomorrow"
