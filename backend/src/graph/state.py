"""LangGraph agent state definition for multi-turn persistence."""
from typing import TypedDict, Optional, Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Graph state persisted across turns and checkpoints.
    
    Messages accumulate and are merged via add_messages.
    Last card/sheet data are preserved so later voice notes link back to the same contact.
    """
    messages: Annotated[list, add_messages]  # Merged message history
    session_id: str  # Thread ID for checkpointing
    last_card_data: Optional[dict]  # Most recent extracted contact (Name, Phone, Email, Company)
    last_sheet_row_id: Optional[int]  # Google Sheets row number used for updates
    pending_confirmation: Optional[dict]  # For HITL bonus: awaiting user confirmation
    image_path: Optional[str]  # Path to uploaded visiting card image
    audio_path: Optional[str]  # Path to uploaded voice note audio file
