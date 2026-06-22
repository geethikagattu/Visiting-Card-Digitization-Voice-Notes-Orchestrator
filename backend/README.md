# Backend: LangGraph Visiting Card Digitization Agent

This is the orchestration engine for the visiting card digitization workflow, built with **LangGraph** and **FastAPI**.

## Architecture

### Core Components

1. **Graph State** (`src/graph/state.py`)
   - `AgentState`: Persists across turns using LangGraph's checkpoint system
   - Stores: messages, session_id, last_card_data, last_sheet_row_id, image/audio paths

2. **Tools** (`src/graph/tools.py`)
   - `extract_card_details()`: Vision API → structured contact fields
   - `check_duplicate()`: Query sheet for existing email/phone (normalized comparison)
   - `log_contact()`: Append new row to Google Sheets
   - `notify_whatsapp()`: Alert manager via WhatsApp Business API
   - `transcribe_voice_note()`: Gemini audio understanding → text
   - `update_contact_audio()`: Write transcript + audio URL back to sheet row

3. **Agent Graph** (`src/graph/agent.py`)
   - StateGraph with two nodes: `agent` (LLM) and `tools` (ToolNode)
   - LLM decides which tool to call for conversational text turns
   - Conditional routing: if tool calls exist → tools node; else → END
   - Compiled with an in-memory checkpointer for dev, or Postgres checkpointing for cloud deployments

4. **FastAPI Server** (`src/server.py`)
   - POST `/chat/session` → create session_id
   - POST `/chat/{session_id}/message` → send text
   - POST `/chat/{session_id}/upload-image` → orchestrate card extraction, dedupe, Sheets logging, WhatsApp notification, and graph state update
   - POST `/chat/{session_id}/upload-audio` → transcribe, upload audio to Cloudinary, update the linked sheet row, and graph state update
   - GET `/chat/{session_id}/history` → retrieve conversation

### Data Flow

```
User uploads card image
    ↓
[FastAPI upload-image endpoint]
    → extract_card_details(image_path)
    ↓
    → check_duplicate(email, phone)
    ↓
If no duplicate:
    → log_contact(data)
    → notify_whatsapp(name, company)
    ↓
Store last_card_data and last_sheet_row_id in state

Later: User uploads voice note for same card
    ↓
[FastAPI upload-audio endpoint reads last_sheet_row_id from graph state]
    → transcribe_voice_note(audio_path)
    → upload audio to Cloudinary
    → update_contact_audio(row_id, audio_url, transcript)
```

## Setup

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
# Edit .env with your credentials
```

**Required for each task:**

- **Task 2 (State)**: No external setup; local state is persistent via checkpointer
- **Task 3 (Tools)**:
  - `GEMINI_API_KEY` (for chat, card vision, and audio transcription)
  - `GOOGLE_SA_JSON` + `SHEET_ID` (Google Sheets)
  - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` (audio URL hosting)
- **Task 4 (Deduplication)**: Included in check_duplicate(); requires Google Sheets
- **Task 5 (Voice notes)**: Requires Cloudinary credentials for audio URL storage
- **Task 6 (WhatsApp)**: `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_TOKEN`, `MANAGER_PHONE_NUMBER`
- **Task 7 (Deployment)**: `POSTGRES_URI` + `USE_POSTGRES_CHECKPOINTER=true` for persistent LangGraph sessions in a managed SQL database

### 3. Google Sheets Setup

1. Create a Google Cloud project and service account
2. Enable **Sheets API**
3. Download service account JSON and paste into `GOOGLE_SA_JSON` (as single-line string)
4. Create a Google Sheet and share it with the service account email
5. Copy the sheet ID from the URL and set `SHEET_ID`

Expected sheet columns:
| Name | Phone | Email | Company | Audio URL | Transcript |

### 4. Cloudinary Setup

1. Create a free Cloudinary account
2. Copy your Cloud Name, API Key, and API Secret from the Cloudinary dashboard
3. Set `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, and `CLOUDINARY_API_SECRET` in `.env`

Voice notes are uploaded to Cloudinary and the returned `secure_url` is saved in the Google Sheet.

### 5. WhatsApp Business API Setup

1. Go to https://developers.facebook.com/
2. Create a Business App and enable **WhatsApp Cloud API**
3. Get a **Phone Number ID** and **Permanent Access Token**
4. Set environment variables in `.env`
5. Keep `WHATSAPP_MESSAGE_MODE=template` for outbound alerts and set `WHATSAPP_TEMPLATE_NAME` to an approved template such as `new_contact_alert`

Do not use Meta's stock `hello_world` template for the production alert; it is only a sample and will not carry your contact details.

### 6. Persistent LangGraph Checkpointing

```bash
USE_POSTGRES_CHECKPOINTER=true
POSTGRES_URI=postgresql://user:password@host:5432/database?sslmode=require
```

Leave `USE_POSTGRES_CHECKPOINTER=false` for local development. Use a managed Postgres provider such as Cloud SQL, Neon, Supabase, or Render Postgres for deployment.

## Running

### Development

```bash
cd backend
python -m uvicorn src.server:app --reload
```

Server runs on `http://localhost:8000`

API docs: `http://localhost:8000/docs`

### Production

```bash
gunicorn -w 4 -k uvicorn.workers.UvicornWorker src.server:app
```

### Docker

```bash
cd backend
docker build -t visiting-card-orchestrator .
docker run --env-file .env -p 8000:8000 visiting-card-orchestrator
```

For Cloud Run or Render, configure the same environment variables as platform secrets. Do not bake `.env` or service-account JSON into the image.

## API Examples

### 1. Create Session

```bash
curl -X POST http://localhost:8000/chat/session
```

Response:

```json
{
  "session_id": "abc-123-def",
  "message": "Session created..."
}
```

### 2. Send Message

```bash
curl -X POST http://localhost:8000/chat/abc-123-def/message \
  -H "Content-Type: application/json" \
  -d '{"message": "I have a new business card to log"}'
```

### 3. Upload Visiting Card Image

```bash
curl -X POST http://localhost:8000/chat/abc-123-def/upload-image \
  -F "image=@/path/to/card.jpg"
```

### 4. Upload Voice Note (Links to Previous Card)

```bash
curl -X POST http://localhost:8000/chat/abc-123-def/upload-audio \
  -F "audio=@/path/to/note.m4a"
```

The agent automatically uses `last_sheet_row_id` from state to update the same contact row.

### 5. Get Session History

```bash
curl http://localhost:8000/chat/abc-123-def/history
```

## Key Design Decisions

1. **Checkpointing Strategy**: State is persisted per `session_id` (thread_id in LangGraph). This ensures:
   - Multiple concurrent users don't interfere
   - Voice notes link back to the correct card via `last_sheet_row_id`
   - Conversation history is preserved

2. **Deduplication**: Normalize email and phone (last 10 digits) before comparing. Treats as duplicate if **either** matches, reducing false positives.

3. **Tool Authorization**: All tools require environment variables (API keys, credentials). Fail gracefully with error messages if not configured.

4. **Audio URL Storage**: Audio files are uploaded to Cloudinary and the returned `secure_url` is written to the sheet.

5. **LLM System Prompt**: Guides the model to:
   - Process images → extract → check duplicate → log or report
   - Process audio (if last_sheet_row_id exists) → transcribe → update row
   - Respond naturally to text messages

## Testing

```bash
# From backend/
./.venv/bin/python -m pytest tests

# Integration test (requires .env configured)
./.venv/bin/python -m pytest tests -v --tb=short
```

## Troubleshooting

| Error                                   | Fix                                          |
| --------------------------------------- | -------------------------------------------- |
| `ModuleNotFoundError: langchain_google_genai` | Install with `pip install langchain-google-genai google-genai` |
| `GOOGLE_SA_JSON not set`                | Copy service account JSON to .env            |
| `Sheets API not enabled`                | Enable in Google Cloud Console               |
| `WhatsApp API 401`                      | Check token validity and phone number ID     |
| `Audio transcription fails`             | Ensure `GEMINI_API_KEY` is set and has quota |

## Next Steps (Future Enhancements)

- **Human-in-the-Loop** (Task 7): Add approval flow before logging contact
- **Alternate Gemini model**: Switch models via `MODEL_NAME` and `GEMINI_MODEL`
- **Redis Caching**: Cache duplicate checks to reduce API calls
- **Async Processing**: Queue tool calls for high-volume scenarios
- **Metrics & Logging**: Integrate with CloudLogging or ELK

---

Built with ❤️ using LangGraph, FastAPI, and Google Cloud Platform.
