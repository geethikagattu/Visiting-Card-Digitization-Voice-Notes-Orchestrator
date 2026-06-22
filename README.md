# Visiting Card Digitization & Voice Notes Orchestrator

An end-to-end assistant for turning visiting cards into structured contact records, storing them in Google Sheets, de-duplicating entries, sending manager notifications on WhatsApp, and later attaching voice notes to the same contact row.

## What this project does

- Accepts visiting card images and voice notes from a chat UI
- Uses a single LangGraph agent to coordinate the workflow
- Extracts `Name`, `Phone`, `Email`, and `Company` from card images
- Checks Google Sheets for duplicates before creating a new row
- Logs unique contacts to Google Sheets
- Sends a WhatsApp notification when a new contact is saved
- Links a later voice note to the original sheet row

## Architecture

- Frontend: React + Vite chat UI
- Backend: FastAPI
- Agent orchestration: LangGraph
- Extraction: Gemini vision/audio
- Primary storage: Google Sheets
- Audio hosting: Cloudinary
- Notifications: WhatsApp Business API
- Session state: LangGraph checkpointing

## Repository Layout

```text
backend/
  src/
    graph/
    integrations/
    storage/
    server.py
    settings.py
  tests/
frontend/
  src/
```

Note: use the top-level `backend/` app. The nested `backend/backend/` directory is a placeholder copy and should not be deployed.

## Features Matched To The Assignment

### Task 1: Chat UI
- Upload visiting card images
- Upload audio/voice notes
- Support multiple chat sessions

### Task 2: Single LangGraph Agent
- One graph manages the workflow
- Session state keeps the card row ID for later voice-note updates

### Task 3: AI Data Extraction
- Gemini parses card images into structured contact data

### Task 4: Google Sheets + Deduplication
- Google Sheet acts as the source of truth
- Email and phone are normalized before duplicate checks

### Task 5: Voice Recording Handling
- Voice notes are uploaded, transcribed, and written back to the same row

### Task 6: WhatsApp Notification
- Manager alert is sent after a unique card is logged

### Task 7: Cloud Deployment
- Backend is container-ready
- Secrets are handled through environment variables

## Local Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

Start the API:

```bash
uvicorn src.server:app --reload
```

Backend URL:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/docs
```

### Frontend

```bash
cd "frontend "
npm install
npm run dev
```

Because the folder name currently has a trailing space, make sure to quote it exactly.

## Environment Variables

Set these in `backend/.env` locally or in Render for deployment:

```env
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
MODEL_NAME=google_genai:gemini-2.5-flash

GOOGLE_SA_JSON_FILE=/absolute/path/to/service-account.json
SHEET_ID=...

CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...

WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_TOKEN=...
MANAGER_PHONE_NUMBER=...
WHATSAPP_MESSAGE_MODE=text
WHATSAPP_TEMPLATE_NAME=new_contact_alert
WHATSAPP_TEMPLATE_LANGUAGE=en_US

CORS_ORIGINS=http://localhost:5173
USE_MONGODB_CHECKPOINTER=false
USE_POSTGRES_CHECKPOINTER=false
ENABLE_HUMAN_IN_THE_LOOP=false
```

## Google Sheets Setup

1. Create a Google Cloud project
2. Enable the Google Sheets API
3. Create a service account and download the JSON key
4. Share the target sheet with the service account email
5. Put the sheet ID into `SHEET_ID`

Expected columns:

| Name | Phone | Email | Company | Audio URL | Transcript |

## WhatsApp Setup

- Use `WHATSAPP_MESSAGE_MODE=text` for the custom alert currently used by the app
- If you want template mode, switch `WHATSAPP_MESSAGE_MODE=template` and set a real approved template name
- Do not use Meta's sample `hello_world` template for the production alert

## Testing

```bash
cd backend
./.venv/bin/python -m pytest tests
```

## Render Deployment

Create a Render Web Service from the GitHub repo.

Settings:

```text
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn src.server:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Add these environment variables in Render:

- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `MODEL_NAME`
- `GOOGLE_SA_JSON`
- `SHEET_ID`
- `CLOUDINARY_CLOUD_NAME`
- `CLOUDINARY_API_KEY`
- `CLOUDINARY_API_SECRET`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_TOKEN`
- `MANAGER_PHONE_NUMBER`
- `WHATSAPP_MESSAGE_MODE`
- `CORS_ORIGINS`

## Demo Flow

1. Open the chat UI
2. Create a session
3. Upload a visiting card image
4. Confirm the contact is extracted and logged to Google Sheets
5. Confirm the WhatsApp alert is sent
6. Upload a voice note in the same session
7. Confirm the transcript and audio URL are written back to the same sheet row

## Notes

- The backend passes tests locally, and the current WhatsApp flow is set back to the normal custom alert path.
- If you are preparing a submission, remove any real secrets from committed files before pushing.

