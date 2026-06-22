"""LangGraph tools for visiting card orchestration workflow.

Each tool handles a step in the agent's action sequence:
- extract_card_details: OCR + vision → contact fields
- check_duplicate: Query sheet by email/phone
- log_contact: Append new row to sheet
- notify_whatsapp: Alert manager
- transcribe_voice_note: Gemini audio understanding
- update_contact_audio: Write back to sheet
"""
import os
import json
import mimetypes
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any
from langchain_core.tools import tool

from ..settings import settings


def normalize(s: str) -> str:
    """Normalize string for deduplication: lowercase, strip, remove spaces."""
    return s.strip().lower().replace(" ", "")


def normalize_email(value: Any) -> str:
    """Normalize email values for deduplication."""
    return normalize(first_contact_value(value))


def phone_digits(value: Any) -> str:
    """Return only phone digits, preserving the useful suffix for matching."""
    return re.sub(r"\D", "", first_contact_value(value))


def row_value(row: dict, *names: str) -> str:
    """Read a value from a Google Sheets row using case-insensitive header aliases."""
    normalized = {normalize(str(key)): value for key, value in row.items()}
    for name in names:
        value = normalized.get(normalize(name))
        if value:
            return contact_value(value)
    return ""


def contact_value(value: Any) -> str:
    """Convert model-extracted contact fields into a sheet-friendly string."""
    if value is None:
        return ""
    if isinstance(value, list):
        values = [contact_value(item) for item in value]
        return ", ".join(item for item in values if item)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def first_contact_value(value: Any) -> str:
    """Pick the first available value for matching-oriented tool inputs."""
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            item_value = first_contact_value(item)
            if item_value:
                return item_value
        return ""
    return contact_value(value)


def error_message(error: Exception) -> str:
    """Return a useful exception message even when str(error) is empty."""
    message = str(error).strip()
    if message:
        return message
    cause = getattr(error, "__cause__", None) or getattr(error, "__context__", None)
    if cause:
        cause_message = str(cause).strip() or repr(cause)
        return f"{type(error).__name__}: {cause_message}"
    return repr(error)


def is_retryable_gemini_error(message: str) -> bool:
    """Return True for temporary Gemini capacity/service errors."""
    if any(token in message for token in ["503", "UNAVAILABLE", "high demand", "temporarily"]):
        return True
    return is_gemini_quota_error(message) and not is_gemini_daily_quota_error(message)


def is_gemini_quota_error(message: str) -> bool:
    """Return True when Gemini reports a quota or rate-limit failure."""
    return any(
        token in message
        for token in ["429", "RESOURCE_EXHAUSTED", "Quota exceeded", "quota exceeded"]
    )


def is_gemini_daily_quota_error(message: str) -> bool:
    """Return True for Gemini quota errors that are unlikely to clear with a short retry."""
    return is_gemini_quota_error(message) and any(
        token in message for token in ["PerDay", "per day", "requests per day"]
    )


def gemini_retry_delay_seconds(message: str) -> float | None:
    """Extract Gemini's suggested retry delay from an exception message."""
    patterns = [
        r"retry in (?P<seconds>\d+(?:\.\d+)?)s",
        r"retryDelay['\"]?:\s*['\"](?P<seconds>\d+(?:\.\d+)?)s",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return float(match.group("seconds"))
    return None


def generate_content_with_retry(**kwargs):
    """Call Gemini with a short retry for temporary capacity spikes."""
    last_error = None
    for attempt in range(3):
        try:
            return get_gemini_client().models.generate_content(**kwargs)
        except Exception as error:
            message = error_message(error)
            last_error = message
            if attempt == 2 or not is_retryable_gemini_error(message):
                raise
            retry_delay = gemini_retry_delay_seconds(message)
            time.sleep(retry_delay if retry_delay is not None else 1.5 * (attempt + 1))
    raise RuntimeError(last_error or "Gemini request failed")


def whatsapp_recipient(value: str) -> str:
    """Return WhatsApp Cloud API recipient format: country code plus digits."""
    return re.sub(r"\D", "", value or "")


def mask_contact(value: str) -> str:
    """Mask a phone-like identifier for user-facing diagnostics."""
    value = value or ""
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"


@lru_cache(maxsize=1)
def get_gemini_client():
    """Keep one client alive for the application lifetime."""
    if not settings.GEMINI_API_KEY:
        raise ValueError("Set GEMINI_API_KEY in backend/.env")
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def file_part(path: str, data: bytes):
    """Build a Gemini inline-data part with the file's detected media type."""
    from google.genai import types

    mime_type = media_mime_type(path)
    return types.Part.from_bytes(data=data, mime_type=mime_type)


def media_mime_type(path: str) -> str:
    """Return a Gemini-friendly MIME type for image and voice-note uploads."""
    suffix = Path(path).suffix.lower()
    audio_mime_types = {
        ".aac": "audio/aac",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".oga": "audio/ogg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }
    return audio_mime_types.get(suffix) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def google_service_account_info() -> dict:
    """Load service-account credentials from a file or legacy inline JSON."""
    if settings.GOOGLE_SA_JSON_FILE:
        service_account_path = Path(settings.GOOGLE_SA_JSON_FILE)
        if service_account_path.exists():
            return json.loads(service_account_path.read_text(encoding="utf-8"))
    if settings.GOOGLE_SA_JSON:
        return json.loads(settings.GOOGLE_SA_JSON)
    if settings.GOOGLE_SA_JSON_FILE:
        raise ValueError(
            f"GOOGLE_SA_JSON_FILE does not exist: {settings.GOOGLE_SA_JSON_FILE}. "
            "Set GOOGLE_SA_JSON instead for deployed environments."
        )
    raise ValueError("Set GOOGLE_SA_JSON or GOOGLE_SA_JSON_FILE in backend/.env")


def sheet_records(sheet) -> list[dict]:
    """Return records from a worksheet while ignoring blank/duplicate headers."""
    if not hasattr(sheet, "get"):
        return sheet.get_all_records()

    values = sheet_values(sheet)
    if not values or values == [[]]:
        return []

    headers = [str(header).strip() for header in values[0]]
    header_columns = []
    seen_headers = set()
    for index, header in enumerate(headers):
        normalized_header = normalize(header)
        if not normalized_header or normalized_header in seen_headers:
            continue
        seen_headers.add(normalized_header)
        header_columns.append((index, header))

    records = []
    for row in values[1:]:
        record = {}
        for index, header in header_columns:
            record[header] = row[index] if index < len(row) else ""
        records.append(record)
    return records


def sheet_values(sheet) -> list[list[Any]]:
    """Return raw worksheet values with padded rows when the client supports it."""
    if hasattr(sheet, "get"):
        return sheet.get(pad_values=True)
    return []


def row_has_duplicate_value(row_values: list[Any], norm_email: str, norm_phone_suffix: str) -> str:
    """Find a duplicate by scanning all cell values in a row."""
    for value in row_values:
        cell = first_contact_value(value)
        if norm_email and normalize_email(cell) == norm_email:
            return "email"
        digits = phone_digits(cell)
        if norm_phone_suffix and digits.endswith(norm_phone_suffix):
            return "phone"
    return ""


def name_company_match(row: dict, norm_name: str, norm_company: str) -> bool:
    """Return True when a row has the same normalized name and company."""
    if not norm_name or not norm_company:
        return False
    row_name = normalize(row_value(row, "Name", "Full Name", "Contact Name"))
    row_company = normalize(row_value(row, "Company", "Organization", "Organisation"))
    return bool(row_name and row_company and row_name == norm_name and row_company == norm_company)


@tool
def extract_card_details(image_path: str) -> dict:
    """Extract Name, Phone, Email, Company from a visiting card image.
    
    Uses Gemini vision to parse the card and return structured JSON.
    
    Args:
        image_path: Path to the uploaded visiting card image file.
        
    Returns:
        dict with keys: name, phone, email, company, extraction_confidence.
        Returns empty dict on extraction failure.
    """
    if not os.path.exists(image_path):
        return {"error": f"Image file not found: {image_path}"}
    
    try:
        # Send the original image bytes to Gemini as inline multimodal content.
        with open(image_path, "rb") as f:
            image_data = f.read()

        response = generate_content_with_retry(
            model=settings.GEMINI_MODEL,
            contents=[
                "Extract this visiting card as JSON with name, phone, email, and company. Use null for missing fields.",
                file_part(image_path, image_data),
            ],
            config={"response_mime_type": "application/json"},
        )
        
        # Parse response and extract JSON
        content = response.text or ""
        # Extract JSON block from response
        import re
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            extracted = json.loads(json_match.group())
            return {
                "name": contact_value(extracted.get("name")),
                "phone": contact_value(extracted.get("phone")),
                "email": contact_value(extracted.get("email")),
                "company": contact_value(extracted.get("company")),
                "extraction_confidence": "high",
                "raw_response": content,
            }
        return {"error": "Could not parse JSON from vision response", "raw": content}
    
    except Exception as e:
        return {"error": error_message(e)}


@tool
def check_duplicate(email: Any = "", phone: Any = "", name: Any = "", company: Any = "") -> dict:
    """Check Google Sheet for existing contact by email or phone.
    
    Deduplication logic: normalize both email and phone (last 10 digits for phone),
    then check if either matches an existing row. Treats as duplicate if either matches.
    
    Args:
        email: Email address to check (may be empty or a list).
        phone: Phone number to check (may be empty or a list).
        name: Contact name to use as a fallback match.
        company: Company name to use as a fallback match.
        
    Returns:
        dict with: is_duplicate (bool), row_index (int or None), matched_field (str or None).
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Load Google Sheet credentials from environment
        creds = Credentials.from_service_account_info(
            google_service_account_info(),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        if not settings.SHEET_ID:
            return {"error": "SHEET_ID environment variable not set"}
        sheet = client.open_by_key(settings.SHEET_ID).sheet1
        
        # Normalize inputs
        email_value = first_contact_value(email)
        phone_value = first_contact_value(phone)
        name_value = first_contact_value(name)
        company_value = first_contact_value(company)
        norm_email = normalize_email(email_value) if email_value else ""
        norm_phone = phone_digits(phone_value)
        norm_phone_suffix = norm_phone[-10:] if norm_phone else ""
        norm_name = normalize(name_value) if name_value else ""
        norm_company = normalize(company_value) if company_value else ""
        
        # Iterate rows and check for duplicates
        rows = sheet_records(sheet)
        for idx, row in enumerate(rows, start=2):  # Start at row 2 (after header)
            row_email = normalize_email(row_value(row, "Email", "Email Address", "E-mail"))
            row_phone = phone_digits(row_value(row, "Phone", "Phone Number", "Mobile", "Mobile Number", "Contact"))
            
            # Check if either email or phone matches
            if (norm_email and norm_email == row_email) or (
                norm_phone_suffix and row_phone.endswith(norm_phone_suffix)
            ):
                return {
                    "is_duplicate": True,
                    "row_index": idx,
                    "matched_field": "email" if norm_email and norm_email == row_email else "phone",
                    "existing_row": row,
                }
            if name_company_match(row, norm_name, norm_company):
                return {
                    "is_duplicate": True,
                    "row_index": idx,
                    "matched_field": "name_company",
                    "existing_row": row,
                }

        # Fallback for messy sheets with missing/incorrect headers: scan every cell.
        for idx, values in enumerate(sheet_values(sheet)[1:], start=2):
            matched_field = row_has_duplicate_value(values, norm_email, norm_phone_suffix)
            if matched_field:
                return {
                    "is_duplicate": True,
                    "row_index": idx,
                    "matched_field": matched_field,
                    "existing_row": values,
                }
        
        return {"is_duplicate": False, "row_index": None, "matched_field": None}
    
    except Exception as e:
        return {"error": error_message(e)}


@tool
def log_contact(data: dict) -> dict:
    """Append a new validated contact row to Google Sheets.
    
    Args:
        data: dict with keys: name, email, phone, company.
        
    Returns:
        dict with row_id (email as key) and status.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        creds = Credentials.from_service_account_info(
            google_service_account_info(),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        if not settings.SHEET_ID:
            return {"error": "SHEET_ID environment variable not set"}
        sheet = client.open_by_key(settings.SHEET_ID).sheet1
        
        # Append row
        new_row = [
            contact_value(data.get("name", "")),
            contact_value(data.get("phone", "")),
            contact_value(data.get("email", "")),
            contact_value(data.get("company", "")),
            "",  # Placeholder for voice note URL
            "",  # Placeholder for transcription
        ]
        result = sheet.append_row(new_row)
        updated_range = result.get("updates", {}).get("updatedRange", "")
        import re
        row_match = re.search(r"![A-Z]+(\d+):", updated_range)
        row_index = int(row_match.group(1)) if row_match else len(sheet.get_all_values())
        
        # Return row_id (email used as unique key)
        return {
            "status": "logged",
            "row_id": row_index,
            "data": data,
        }
    
    except Exception as e:
        return {"error": error_message(e)}


@tool
def notify_whatsapp(contact_name: str, company: str) -> dict:
    """Send WhatsApp alert to manager about new contact logged.
    
    Args:
        contact_name: Name of the newly logged contact.
        company: Company of the contact.
        
    Returns:
        dict with message_id and status.
    """
    try:
        import httpx
        
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        whatsapp_token = settings.WHATSAPP_TOKEN
        manager_phone = whatsapp_recipient(settings.MANAGER_PHONE_NUMBER)

        if not all([phone_number_id, whatsapp_token, manager_phone]):
            return {"error": "Missing WhatsApp credentials in environment"}

        message_text = f"New contact logged: {contact_name} from {company}"
        message_mode = settings.WHATSAPP_MESSAGE_MODE.strip().lower()
        template_name = settings.WHATSAPP_TEMPLATE_NAME.strip()
        template_language = settings.WHATSAPP_TEMPLATE_LANGUAGE

        url = f"https://graph.facebook.com/v25.0/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {whatsapp_token}"}
        if message_mode == "template":
            if not template_name or template_name.lower() == "hello_world":
                return {
                    "error": (
                        "Set WHATSAPP_TEMPLATE_NAME to a real approved template. "
                        "The sample hello_world template is not suitable for production alerts."
                    )
                }
            payload = {
                "messaging_product": "whatsapp",
                "to": manager_phone,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": template_language},
                    "components": [
                        {
                            "type": "body",
                            "parameters": [
                                {"type": "text", "text": contact_name},
                                {"type": "text", "text": company},
                            ],
                        }
                    ],
                },
            }
        elif message_mode == "text":
            payload = {
                "messaging_product": "whatsapp",
                "to": manager_phone,
                "type": "text",
                "text": {"preview_url": False, "body": message_text},
            }
        else:
            return {
                "error": (
                    f"Unsupported WHATSAPP_MESSAGE_MODE: {settings.WHATSAPP_MESSAGE_MODE!r}. "
                    "Use 'text' or 'template'."
                )
            }
        
        with httpx.Client() as client:
            response = client.post(url, headers=headers, json=payload)
        
        if response.status_code == 200:
            body = response.json()
            messages = body.get("messages", [])
            contacts = body.get("contacts", [])
            return {
                "status": "sent",
                "message": message_text,
                "mode": message_mode,
                "template": template_name if message_mode == "template" else None,
                "message_id": messages[0].get("id") if messages else None,
                "wa_id": contacts[0].get("wa_id") if contacts else None,
                "recipient": mask_contact(contacts[0].get("wa_id", "")) if contacts else None,
            }
        else:
            return {"error": f"WhatsApp API returned {response.status_code}", "response": response.text}
    
    except Exception as e:
        return {"error": error_message(e)}


@tool
def transcribe_voice_note(audio_path: str) -> str:
    """Transcribe an uploaded voice note with Gemini audio understanding.
    
    Args:
        audio_path: Path to the uploaded audio file.
        
    Returns:
        Transcribed text string. Empty string on failure.
    """
    if not os.path.exists(audio_path):
        return ""
    
    try:
        with open(audio_path, "rb") as audio_file:
            audio_data = audio_file.read()
        response = generate_content_with_retry(
            model=settings.GEMINI_MODEL,
            contents=[
                "Transcribe this voice note accurately. Return only the transcript.",
                file_part(audio_path, audio_data),
            ],
        )
        return response.text or ""
    except Exception as e:
        return f"Transcription error: {error_message(e)}"


@tool
def update_contact_audio(row_index: int, audio_url: str, transcript: str) -> dict:
    """Update the existing sheet row with the voice note URL and transcript.
    
    Args:
        row_index: Row number in Google Sheets (1-indexed).
        audio_url: Public Cloudinary URL for the audio file.
        transcript: Transcribed text of the voice note.
        
    Returns:
        dict with status and updated row data.
    """
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        
        creds = Credentials.from_service_account_info(
            google_service_account_info(),
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        client = gspread.authorize(creds)
        if not settings.SHEET_ID:
            return {"error": "SHEET_ID environment variable not set"}
        sheet = client.open_by_key(settings.SHEET_ID).sheet1
        
        # Update columns (assuming columns 5 & 6 are for audio URL & transcript)
        sheet.update_cell(row_index, 5, audio_url)
        sheet.update_cell(row_index, 6, transcript)
        
        return {
            "status": "updated",
            "row_index": row_index,
            "audio_url": audio_url,
            "transcript": transcript[:100],
        }
    
    except Exception as e:
        return {"error": error_message(e)}
