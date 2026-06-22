"""Configuration and environment settings."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # API & Server
    MODEL_NAME: str = "google_genai:gemini-2.5-flash"
    CORS_ORIGINS: str = ""  # Comma-separated frontend origins allowed to call the API
    
    # Google Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    
    # Google Sheets
    GOOGLE_SA_JSON: str = ""  # JSON service account credentials (stringified)
    GOOGLE_SA_JSON_FILE: str = ""  # Preferred: path to downloaded service account JSON
    SHEET_ID: str = ""  # Google Sheets ID to write contacts to

    # Cloudinary audio hosting
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    
    # WhatsApp Business API
    WHATSAPP_PHONE_NUMBER_ID: str = ""  # Phone number ID from Meta Business
    WHATSAPP_TOKEN: str = ""  # Permanent access token for WhatsApp Cloud API
    MANAGER_PHONE_NUMBER: str = ""  # Manager's phone number to notify (e.g., "+1234567890")
    WHATSAPP_MESSAGE_MODE: str = "text"  # Use text for custom alerts or template for approved templates
    WHATSAPP_TEMPLATE_NAME: str = "hello_world"  # Approved template for outbound notifications if using template mode
    WHATSAPP_TEMPLATE_LANGUAGE: str = "en_US"
    
    # MongoDB (for checkpointing)
    MONGODB_URI: str = "mongodb://localhost:27017"  # Connection URI
    MONGODB_DB_NAME: str = "langgraph_checkpoints"  # Database name
    POSTGRES_URI: str = ""  # Optional LangGraph checkpoint DB, e.g. Cloud SQL/Neon/Render Postgres
    
    # Feature flags
    USE_MONGODB_CHECKPOINTER: bool = False  # Set to True to use MongoDB; False uses in-memory
    USE_POSTGRES_CHECKPOINTER: bool = False  # Set to True to persist LangGraph checkpoints in Postgres
    ENABLE_HUMAN_IN_THE_LOOP: bool = False  # For Task 7: user confirmation before logging
    
    model_config = SettingsConfigDict(env_file=ENV_FILE, case_sensitive=True, extra="ignore")


settings = Settings()
