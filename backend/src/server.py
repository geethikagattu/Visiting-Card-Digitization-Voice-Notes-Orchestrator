"""FastAPI server for visiting card digitization agent."""
import os
import uuid
import tempfile
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.graph.agent import get_compiled_graph
from src.graph.tools import (
    check_duplicate,
    extract_card_details,
    log_contact,
    notify_whatsapp,
    transcribe_voice_note,
    update_contact_audio,
)
from src.settings import settings
from src.storage.database import build_checkpointer, close_checkpointer_context


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Close checkpoint storage connections on application shutdown."""
    try:
        yield
    finally:
        close_checkpointer_context()


app = FastAPI(
    title="Visiting Card Digitization Agent",
    version="1.0.0",
    lifespan=lifespan,
)

cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Initialize graph with the configured LangGraph checkpointer.
checkpointer = build_checkpointer()
graph = get_compiled_graph(checkpointer=checkpointer)


# Pydantic models for request/response
class SessionResponse(BaseModel):
    """Response with session ID."""
    session_id: str
    message: str


class MessageRequest(BaseModel):
    """Request to send a text message."""
    message: str


class MessageResponse(BaseModel):
    """Response with agent's reply."""
    session_id: str
    response: str
    last_card_data: Optional[dict] = None
    last_sheet_row_id: Optional[int] = None


class HistoryResponse(BaseModel):
    """Response with session history."""
    session_id: str
    messages: list
    last_card_data: Optional[dict] = None


def initial_state(session_id: str) -> dict:
    """Return the complete state shape for a new session."""
    return {
        "messages": [],
        "session_id": session_id,
        "last_card_data": None,
        "last_sheet_row_id": None,
        "pending_confirmation": None,
        "image_path": None,
        "audio_path": None,
    }


def current_state(config: dict, session_id: str) -> dict:
    """Read existing checkpoint values or initialize a new session state."""
    snapshot = graph.get_state(config)
    return snapshot.values if snapshot and snapshot.values else initial_state(session_id)


def tool_error_detail(result: dict) -> str:
    """Format tool errors without losing blank exception messages."""
    error = str(result.get("error") or "").strip()
    if error:
        response = str(result.get("response") or "").strip()
        if response:
            return f"{error}: {response}"
        return error
    return f"Tool failed without an error message: {result}"


# File upload helper
async def save_upload_file(upload_file: UploadFile) -> str:
    """Save uploaded file to temp directory and return path."""
    temp_dir = tempfile.gettempdir()
    suffix = Path(upload_file.filename or "upload").suffix
    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}{suffix}")
    
    contents = await upload_file.read()
    with open(file_path, "wb") as f:
        f.write(contents)
    
    return file_path


async def upload_to_cloudinary(local_path: str, session_id: str) -> str:
    """Upload an audio file to Cloudinary and return its public secure URL."""
    if not all(
        [
            settings.CLOUDINARY_CLOUD_NAME,
            settings.CLOUDINARY_API_KEY,
            settings.CLOUDINARY_API_SECRET,
        ]
    ):
        raise HTTPException(
            status_code=500,
            detail="Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET in backend/.env",
        )

    try:
        import cloudinary
        import cloudinary.uploader

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )
        uploaded = cloudinary.uploader.upload(
            local_path,
            folder=f"voice-notes/{session_id}",
            resource_type="video",
        )
        secure_url = uploaded.get("secure_url")
        if not secure_url:
            raise ValueError(f"Cloudinary upload did not return secure_url: {uploaded}")
        return secure_url
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cloudinary upload failed: {str(e)}")


# Endpoints
@app.post("/chat/session", response_model=SessionResponse)
async def create_session():
    """Create a new chat session with a unique session_id."""
    session_id = str(uuid.uuid4())
    return SessionResponse(
        session_id=session_id,
        message=f"Session created. Send messages, images, or audio to this session_id.",
    )


@app.post("/chat/{session_id}/message", response_model=MessageResponse)
async def send_message(session_id: str, request: MessageRequest):
    """Send a text message to the agent."""
    try:
        config = {"configurable": {"thread_id": session_id}}
        
        # Get current state or initialize
        state = current_state(config, session_id)
        
        # Invoke graph with new message
        result = graph.invoke(
            {
                **state,
                "messages": [{"role": "user", "content": request.message}],
            },
            config=config,
        )
        
        # Extract assistant response
        last_message = result.get("messages", [])[-1] if result.get("messages") else None
        response_text = (
            last_message.content
            if hasattr(last_message, "content")
            else str(last_message)
        )
        
        return MessageResponse(
            session_id=session_id,
            response=response_text,
            last_card_data=result.get("last_card_data"),
            last_sheet_row_id=result.get("last_sheet_row_id"),
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Message processing failed: {str(e)}")


@app.post("/chat/{session_id}/upload-image")
async def upload_image(session_id: str, image: UploadFile = File(...)):
    """Upload a visiting card image for processing."""
    try:
        config = {"configurable": {"thread_id": session_id}}
        
        # Save uploaded file
        image_path = await save_upload_file(image)
        
        card_data = extract_card_details.invoke({"image_path": image_path})
        if card_data.get("error"):
            raise HTTPException(
                status_code=502,
                detail=f"Gemini card extraction failed: {card_data['error']}",
            )

        duplicate = check_duplicate.invoke(
            {"email": card_data.get("email") or "", "phone": card_data.get("phone") or ""}
        )
        if "error" in duplicate:
            raise HTTPException(status_code=502, detail=tool_error_detail(duplicate))

        if duplicate.get("is_duplicate"):
            row_id = duplicate["row_index"]
            response_text = "This contact already exists. I linked the session to its sheet row."
        else:
            logged = log_contact.invoke({"data": card_data})
            if "error" in logged:
                raise HTTPException(status_code=502, detail=tool_error_detail(logged))
            row_id = logged.get("row_id")
            if not row_id:
                raise HTTPException(
                    status_code=502,
                    detail=f"Google Sheets logging did not return a row_id: {logged}",
                )
            response_text = "Card extracted and contact saved to Google Sheets."
            notification = notify_whatsapp.invoke(
                {
                    "contact_name": card_data.get("name") or "Unknown contact",
                    "company": card_data.get("company") or "Unknown company",
                }
            )
            if notification.get("error"):
                response_text += (
                    f" WhatsApp notification was skipped: {tool_error_detail(notification)}"
                )
            else:
                response_text += (
                    " WhatsApp notification sent"
                    f" to {notification.get('recipient') or 'the configured recipient'}"
                    f" (message id: {notification.get('message_id') or 'unavailable'})."
                )

        graph.update_state(
            config,
            {
                **current_state(config, session_id),
                "last_card_data": card_data,
                "last_sheet_row_id": row_id,
                "image_path": image_path,
                "messages": [{"role": "assistant", "content": response_text}],
            },
        )
        
        return {
            "session_id": session_id,
            "status": "image processed",
            "response": response_text,
            "last_card_data": card_data,
            "last_sheet_row_id": row_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image upload failed: {str(e)}")


@app.post("/chat/{session_id}/upload-audio")
async def upload_audio(session_id: str, audio: UploadFile = File(...)):
    """Upload a voice note for transcription and sheet update."""
    try:
        config = {"configurable": {"thread_id": session_id}}
        
        # Save uploaded file
        audio_path = await save_upload_file(audio)
        
        state = current_state(config, session_id)
        row_id = state.get("last_sheet_row_id")
        if not row_id:
            raise HTTPException(status_code=409, detail="Upload a visiting card before its voice note")

        transcript = transcribe_voice_note.invoke({"audio_path": audio_path})
        if transcript.startswith("Transcription error:"):
            raise HTTPException(status_code=502, detail=transcript)

        audio_url = await upload_to_cloudinary(audio_path, session_id)

        updated = update_contact_audio.invoke(
            {"row_index": row_id, "audio_url": audio_url, "transcript": transcript}
        )
        if updated.get("error"):
            raise HTTPException(status_code=502, detail=updated["error"])

        response_text = "Voice note transcribed and linked to the contact."
        graph.update_state(
            config,
            {
                **state,
                "audio_path": audio_path,
                "messages": [{"role": "assistant", "content": response_text}],
            },
        )
        
        return {
            "session_id": session_id,
            "status": "audio processed",
            "response": response_text,
            "transcript": transcript,
            "audio_url": audio_url,
            "last_sheet_row_id": row_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Audio upload failed: {str(e)}")


@app.get("/chat/{session_id}/history", response_model=HistoryResponse)
async def get_history(session_id: str):
    """Get full conversation history for a session."""
    try:
        config = {"configurable": {"thread_id": session_id}}
        state = graph.get_state(config)
        
        if not state:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        
        values = state.values
        
        return HistoryResponse(
            session_id=session_id,
            messages=values.get("messages", []),
            last_card_data=values.get("last_card_data"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"History retrieval failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
