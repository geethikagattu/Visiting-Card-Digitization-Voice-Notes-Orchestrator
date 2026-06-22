# Visiting Card Digitization & Voice Notes Orchestrator

An end-to-end system for digitizing visiting cards, logging contacts into Google Sheets, detecting duplicates, sending WhatsApp alerts, and attaching voice notes to the same contact record.

## Overview

This project uses a single LangGraph-based backend agent to orchestrate the workflow:

- upload a visiting card image
- extract structured contact details
- check Google Sheets for duplicates
- log unique contacts to the sheet
- send a WhatsApp notification to a manager
- accept a later voice note and link it to the same sheet row

## Tech Stack

- Frontend: React, Vite
- Backend: FastAPI
- Orchestration: LangGraph
- Extraction: Gemini
- Storage: Google Sheets
- Audio hosting: Cloudinary
- Notifications: WhatsApp Business API
- Deployment: Render

## Project Structure

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

> Note: this repository currently also contains a nested `backend/backend/` placeholder directory. The real application lives in the top-level `backend/` folder.

## Features

- Image upload for visiting cards
- Voice note upload for follow-up details
- Session-based conversation state
- Duplicate detection using Google Sheets
- WhatsApp manager alert after successful logging
- Voice note transcription and row update
- FastAPI health endpoint for deployment checks

## Assignment Coverage

### Task 1: Chat UI
- A chat interface is provided in the frontend
- Supports image uploads
- Supports audio uploads
- Supports multiple chat sessions

### Task 2: Single LangGraph Agent
- One LangGraph agent manages the workflow
- State is preserved across requests using a checkpointing layer
- Voice notes are linked to the correct contact row

### Task 3: AI Data Extraction
- Gemini extracts:
  - Name
  - Phone
  - Email
  - Company

### Task 4: Google Sheets Integration & Deduplication
- Google Sheets is the source of truth
- Duplicate checks are performed before logging
- Email and phone are normalized for matching

### Task 5: Voice Recording Handling
- Voice notes are uploaded and hosted
- Transcript and audio URL are written back to the same Google Sheets row

### Task 6: WhatsApp Notification Integration
- A WhatsApp alert is triggered after a unique contact is saved
- The current setup uses a custom text alert

### Task 7: Cloud Deployment
- Backend is deployable on Render
- Secrets are injected through environment variables
- Docker-ready backend structure is included

## Setup Instructions

### Prerequisites

- Python 3.11+
- Node.js 18+
- A Google Gemini API key
- A Google Sheets service account
- Cloudinary credentials
- WhatsApp Business API credentials

## Backend Setup

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

Edit `backend/.env` with your values.

### Run Backend Locally

```bash
cd backend
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

## Frontend Setup

```bash
cd "frontend "
npm install
npm run dev
```

If you rename the folder to `frontend`, update the command accordingly.

## Environment Variables

### Backend `.env`

```env
# Gemini
GEMINI_API_KEY=your-gemini-api-key
GEMINI_MODEL=gemini-2.5-flash
MODEL_NAME=google_genai:gemini-2.5-flash

# Google Sheets
GOOGLE_SA_JSON_FILE=/absolute/path/to/service-account.json
GOOGLE_SA_JSON=
SHEET_ID=your-google-sheet-id

# Cloudinary
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# WhatsApp
WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
WHATSAPP_TOKEN=your-whatsapp-token
MANAGER_PHONE_NUMBER=+911234567890
WHATSAPP_MESSAGE_MODE=text
WHATSAPP_TEMPLATE_NAME=new_contact_alert
WHATSAPP_TEMPLATE_LANGUAGE=en_US

# CORS
CORS_ORIGINS=http://localhost:5173

# Checkpointing
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB_NAME=langgraph_checkpoints
USE_MONGODB_CHECKPOINTER=false
USE_POSTGRES_CHECKPOINTER=false
POSTGRES_URI=

# Feature flags
ENABLE_HUMAN_IN_THE_LOOP=false
```

### Frontend Environment

For local development, the frontend can use the backend running on `localhost:8000`.

For deployment, set:

```env
VITE_API_URL=https://your-render-backend-url.onrender.com
```

## Google Sheets Setup

1. Create a Google Cloud project.
2. Enable the Google Sheets API.
3. Create a service account.
4. Download the JSON key.
5. Share the target Google Sheet with the service account email.
6. Copy the Sheet ID from the URL and place it in `SHEET_ID`.

Expected sheet columns:

| Name | Phone | Email | Company | Audio URL | Transcript |

## WhatsApp Setup

1. Create a Meta Business app.
2. Enable WhatsApp Cloud API.
3. Get a phone number ID and permanent access token.
4. Add them to the backend environment variables.
5. Keep `WHATSAPP_MESSAGE_MODE=text` for the custom alert currently used by the app.

If you switch to template mode later, set:

```env
WHATSAPP_MESSAGE_MODE=template
WHATSAPP_TEMPLATE_NAME=<approved-template-name>
```

## Render Deployment

### Backend

Create a Render Web Service and configure:

```text
Root Directory: backend
Build Command: pip install -r requirements.txt
Start Command: uvicorn src.server:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Add the backend environment variables in Render.

### Frontend

Create a Render Static Site.

```text
Root Directory: frontend
Build Command: npm install && npm run build
Publish Directory: dist
```

Set:

```env
VITE_API_URL=https://your-render-backend-url.onrender.com
```

## API Endpoints

### Create Session

```http
POST /chat/session
```

### Send Message

```http
POST /chat/{session_id}/message
```

### Upload Visiting Card Image

```http
POST /chat/{session_id}/upload-image
```

### Upload Voice Note

```http
POST /chat/{session_id}/upload-audio
```

### Session History

```http
GET /chat/{session_id}/history
```

### Health Check

```http
GET /health
```

## How It Works

1. User starts a chat session.
2. User uploads a visiting card image.
3. Gemini extracts the contact details.
4. The backend checks Google Sheets for duplicates.
5. If the contact is unique, it is logged to the sheet.
6. A WhatsApp notification is sent to the manager.
7. The user later uploads a voice note in the same session.
8. The transcript and audio URL are attached to the same Google Sheets row.

## Testing

Run backend tests:

```bash
cd backend
./.venv/bin/python -m pytest tests
```

## Notes on Approach

- The workflow is intentionally centered around a single LangGraph agent so session state remains consistent across image and audio uploads.
- Google Sheets is treated as the source of truth, which keeps the system simple and transparent.
- Duplicate detection uses normalized contact fields to reduce repeated rows.
- WhatsApp alerts are sent after successful logging so the manager is notified only when the contact is confirmed.
- Voice notes are linked back to the original contact row using the saved sheet row ID in session state.
- Environment variables are used for all secrets and deployment-specific configuration.

## Security Notes

- Do not commit real secrets to the repository.
- Prefer Render environment variables or another secrets manager in production.
- If a local service-account JSON path is used in development, make sure it is not committed.

## Demo Flow

1. Create a chat session
2. Upload a visiting card image
3. Confirm extracted fields and Google Sheets logging
4. Confirm the WhatsApp alert
5. Upload a voice note in the same session
6. Confirm the transcript and audio URL were written back to the same row

## Future Improvements

- Human-in-the-loop confirmation before logging
- Better template-based WhatsApp alerting
- Database-backed session analytics
- Retry queue for transient external API failures
- Better media preview in the chat UI

## License

This project was built for an assessment and does not currently include a formal license.
```

I can also turn this into a shorter, cleaner `README.md` tailored for submission if you want a more polished final version.
