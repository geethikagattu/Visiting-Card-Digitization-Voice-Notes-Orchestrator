from types import SimpleNamespace

from src.graph import tools


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(text=response)


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def post(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.response


def test_card_extraction_uses_gemini(monkeypatch, tmp_path):
    models = FakeModels(['{"name":"Ada","phone":null,"email":"ada@example.com","company":"Example"}'])
    client = SimpleNamespace(models=models)
    image = tmp_path / "card.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(tools, "get_gemini_client", lambda: client)
    monkeypatch.setattr(tools, "file_part", lambda path, data: (path, data))

    result = tools.extract_card_details.invoke({"image_path": str(image)})

    assert result["name"] == "Ada"
    assert models.calls[0]["model"] == tools.settings.GEMINI_MODEL
    assert models.calls[0]["config"]["response_mime_type"] == "application/json"


def test_card_extraction_flattens_list_fields(monkeypatch, tmp_path):
    models = FakeModels([
        '{"name":"Ada","phone":["+123-456-7890","+987-654-3210"],'
        '"email":["ada@example.com"],"company":"Example"}'
    ])
    client = SimpleNamespace(models=models)
    image = tmp_path / "card.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(tools, "get_gemini_client", lambda: client)
    monkeypatch.setattr(tools, "file_part", lambda path, data: (path, data))

    result = tools.extract_card_details.invoke({"image_path": str(image)})

    assert result["phone"] == "+123-456-7890, +987-654-3210"
    assert result["email"] == "ada@example.com"


def test_check_duplicate_accepts_list_phone(monkeypatch):
    class FakeSheet:
        def get_all_records(self):
            return [{"Email": "ada@example.com", "Phone": "+123-456-7890"}]

    class FakeClient:
        def open_by_key(self, sheet_id):
            return SimpleNamespace(sheet1=FakeSheet())

    monkeypatch.setattr(tools, "google_service_account_info", lambda: {})
    monkeypatch.setattr(tools.settings, "SHEET_ID", "sheet-id")
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("gspread.authorize", lambda creds: FakeClient())

    result = tools.check_duplicate.invoke(
        {"email": "", "phone": ["+123-456-7890", "+987-654-3210"]}
    )

    assert result["is_duplicate"] is True
    assert result["matched_field"] == "phone"


def test_check_duplicate_accepts_sheet_header_aliases_and_phone_formatting(monkeypatch):
    class FakeSheet:
        def get_all_records(self):
            return [{"Email Address": "ada@example.com", "Phone Number": "+1 (123) 456-7890"}]

    class FakeClient:
        def open_by_key(self, sheet_id):
            return SimpleNamespace(sheet1=FakeSheet())

    monkeypatch.setattr(tools, "google_service_account_info", lambda: {})
    monkeypatch.setattr(tools.settings, "SHEET_ID", "sheet-id")
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("gspread.authorize", lambda creds: FakeClient())

    result = tools.check_duplicate.invoke(
        {"email": "ADA@EXAMPLE.COM", "phone": "1234567890"}
    )

    assert result["is_duplicate"] is True
    assert result["matched_field"] == "email"


def test_check_duplicate_ignores_duplicate_blank_sheet_headers(monkeypatch):
    class FakeSheet:
        def get(self, pad_values=False):
            assert pad_values is True
            return [
                ["Name", "Phone", "Email", "Company", "", ""],
                ["Ada", "+1 (123) 456-7890", "ada@example.com", "Example", "", ""],
            ]

    class FakeClient:
        def open_by_key(self, sheet_id):
            return SimpleNamespace(sheet1=FakeSheet())

    monkeypatch.setattr(tools, "google_service_account_info", lambda: {})
    monkeypatch.setattr(tools.settings, "SHEET_ID", "sheet-id")
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("gspread.authorize", lambda creds: FakeClient())

    result = tools.check_duplicate.invoke(
        {"email": "ada@example.com", "phone": ""}
    )

    assert result["is_duplicate"] is True
    assert result["matched_field"] == "email"


def test_check_duplicate_scans_values_when_headers_are_missing(monkeypatch):
    class FakeSheet:
        def get(self, pad_values=False):
            assert pad_values is True
            return [
                ["", "", "", ""],
                ["Ada", "+1 (123) 456-7890", "ada@example.com", "Example"],
            ]

    class FakeClient:
        def open_by_key(self, sheet_id):
            return SimpleNamespace(sheet1=FakeSheet())

    monkeypatch.setattr(tools, "google_service_account_info", lambda: {})
    monkeypatch.setattr(tools.settings, "SHEET_ID", "sheet-id")
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("gspread.authorize", lambda creds: FakeClient())

    result = tools.check_duplicate.invoke(
        {"email": "", "phone": "1234567890"}
    )

    assert result["is_duplicate"] is True
    assert result["row_index"] == 2
    assert result["matched_field"] == "phone"


def test_check_duplicate_matches_name_and_company_when_contact_fields_are_missing(monkeypatch):
    class FakeSheet:
        def get(self, pad_values=False):
            assert pad_values is True
            return [
                ["Name", "Phone", "Email", "Company", "Audio URL", "Transcript"],
                ["Ada Lovelace", "", "", "Analytical Engines", "", ""],
            ]

    class FakeClient:
        def open_by_key(self, sheet_id):
            return SimpleNamespace(sheet1=FakeSheet())

    monkeypatch.setattr(tools, "google_service_account_info", lambda: {})
    monkeypatch.setattr(tools.settings, "SHEET_ID", "sheet-id")
    monkeypatch.setattr(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr("gspread.authorize", lambda creds: FakeClient())

    result = tools.check_duplicate.invoke(
        {
            "email": "",
            "phone": "",
            "name": "Ada Lovelace",
            "company": "Analytical Engines",
        }
    )

    assert result["is_duplicate"] is True
    assert result["matched_field"] == "name_company"


def test_first_contact_value_skips_empty_list_items():
    assert tools.first_contact_value(["", None, "+123-456-7890"]) == "+123-456-7890"


def test_error_message_includes_cause_for_blank_exception():
    try:
        try:
            raise ValueError("inner detail")
        except ValueError as inner:
            raise PermissionError() from inner
    except PermissionError as error:
        assert tools.error_message(error) == "PermissionError: inner detail"


def test_whatsapp_recipient_strips_formatting():
    assert tools.whatsapp_recipient("+91-123-456-7890") == "911234567890"


def test_mask_contact_shows_only_last_four_digits():
    assert tools.mask_contact("911234567890") == "***7890"


def test_notify_whatsapp_returns_message_id(monkeypatch):
    http_client = FakeHttpClient(
        SimpleNamespace(
            status_code=200,
            json=lambda: {
                "contacts": [{"wa_id": "911234567890"}],
                "messages": [{"id": "wamid.test"}],
            },
        )
    )
    response = SimpleNamespace(
        status_code=200,
        json=lambda: {
            "contacts": [{"wa_id": "911234567890"}],
            "messages": [{"id": "wamid.test"}],
        },
    )
    monkeypatch.setattr(tools.settings, "WHATSAPP_PHONE_NUMBER_ID", "phone-id")
    monkeypatch.setattr(tools.settings, "WHATSAPP_TOKEN", "token")
    monkeypatch.setattr(tools.settings, "MANAGER_PHONE_NUMBER", "+91-123-456-7890")
    monkeypatch.setattr(tools.settings, "WHATSAPP_MESSAGE_MODE", "text")
    monkeypatch.setattr(tools.settings, "WHATSAPP_TEMPLATE_NAME", "hello_world")
    monkeypatch.setattr(tools.settings, "WHATSAPP_TEMPLATE_LANGUAGE", "en_US")
    monkeypatch.setattr("httpx.Client", lambda: http_client)

    result = tools.notify_whatsapp.invoke(
        {"contact_name": "Ada", "company": "Example"}
    )

    assert result["status"] == "sent"
    assert result["message_id"] == "wamid.test"
    assert result["wa_id"] == "911234567890"
    assert result["recipient"] == "***7890"
    assert result["mode"] == "text"
    assert result["template"] is None
    payload = http_client.calls[0]["kwargs"]["json"]
    assert payload["type"] == "text"
    assert payload["text"]["body"] == "New contact logged: Ada from Example"


def test_audio_transcription_uses_gemini(monkeypatch, tmp_path):
    models = FakeModels(["Met at the conference."])
    client = SimpleNamespace(models=models)
    audio = tmp_path / "note.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(tools, "get_gemini_client", lambda: client)
    monkeypatch.setattr(tools, "file_part", lambda path, data: (path, data))

    result = tools.transcribe_voice_note.invoke({"audio_path": str(audio)})

    assert result == "Met at the conference."
    assert models.calls[0]["model"] == tools.settings.GEMINI_MODEL


def test_audio_transcription_retries_temporary_gemini_overload(monkeypatch, tmp_path):
    models = FakeModels([RuntimeError("503 UNAVAILABLE high demand"), "Retry worked."])
    client = SimpleNamespace(models=models)
    audio = tmp_path / "note.wav"
    audio.write_bytes(b"audio")
    monkeypatch.setattr(tools, "get_gemini_client", lambda: client)
    monkeypatch.setattr(tools, "file_part", lambda path, data: (path, data))
    monkeypatch.setattr(tools.time, "sleep", lambda seconds: None)

    result = tools.transcribe_voice_note.invoke({"audio_path": str(audio)})

    assert result == "Retry worked."
    assert len(models.calls) == 2


def test_webm_voice_note_is_sent_as_audio(monkeypatch, tmp_path):
    captured = {}

    class FakePart:
        @staticmethod
        def from_bytes(data, mime_type):
            captured["mime_type"] = mime_type
            return {"data": data, "mime_type": mime_type}

    audio = tmp_path / "voice-note.webm"
    audio.write_bytes(b"audio")
    monkeypatch.setattr("google.genai.types.Part", FakePart)

    part = tools.file_part(str(audio), audio.read_bytes())

    assert part["mime_type"] == "audio/webm"
    assert captured["mime_type"] == "audio/webm"
