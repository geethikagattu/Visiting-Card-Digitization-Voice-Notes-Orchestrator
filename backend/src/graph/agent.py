"""LangGraph agent definition and compilation."""
from typing import Literal
from langchain.chat_models import init_chat_model
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver

from .state import AgentState
from ..settings import settings
from .tools import (
    extract_card_details,
    check_duplicate,
    log_contact,
    notify_whatsapp,
    transcribe_voice_note,
    update_contact_audio,
)


# Collect all tools for binding to the model
ALL_TOOLS = [
    extract_card_details,
    check_duplicate,
    log_contact,
    notify_whatsapp,
    transcribe_voice_note,
    update_contact_audio,
]


def call_model(state: AgentState) -> dict:
    """LLM node: Gemini calls tools based on messages and state.
    
    System prompt instructs the model to:
    - If image_path is set: extract card details, check duplicate, log or report
    - If audio_path is set and last_sheet_row_id exists: transcribe and update row
    
    Returns:
        dict with updated messages (AI's tool calls or final response)
    """
    model_name = settings.MODEL_NAME
    
    # Initialize the model and bind tools
    model_kwargs = {}
    if model_name.startswith("google_genai:"):
        if not settings.GEMINI_API_KEY:
            raise ValueError("Set GEMINI_API_KEY in backend/.env")
        model_kwargs["google_api_key"] = settings.GEMINI_API_KEY
    model = init_chat_model(model_name, **model_kwargs)
    model_with_tools = model.bind_tools(ALL_TOOLS)
    
    # System prompt instructs the agent's behavior
    system_prompt = """You are a visiting card digitization agent. Your responsibilities:

1. **Image Upload (visiting card)**: If the user provides an image, call extract_card_details to parse it. Then call check_duplicate to see if the contact already exists. If no duplicate, call log_contact to save it. Notify the manager via notify_whatsapp. Store the extracted data in state for later voice note linkage.

2. **Audio Upload (voice note)**: If the user provides audio and there's a last_sheet_row_id in state (meaning a card was just processed), call transcribe_voice_note to convert audio to text, then update_contact_audio to write the transcript and audio URL back to the sheet row.

3. **Text Messages**: Respond conversationally to the user. Ask for clarification if needed.

Always explain what you're doing. Be concise and professional."""
    
    # Build message list from state
    messages = state.get("messages", [])
    
    # Call model with system prompt and tools
    response = model_with_tools.invoke(
        [
            {"type": "system", "content": system_prompt},
            *messages,
        ]
    )
    
    # Return updated state with the model's response
    return {"messages": [response]}


def route_tool_calls(state: AgentState) -> Literal["tools", "__end__"]:
    """Route based on whether the last message contains tool calls."""
    return tools_condition(state, messages_key="messages")


def build_graph(checkpointer=None):
    """Build and compile the LangGraph agent.
    
    Args:
        checkpointer: Optional checkpoint saver (MongoDBSaver, InMemorySaver, etc.).
                     If None, uses InMemorySaver (development only).
    
    Returns:
        Compiled StateGraph ready to invoke with messages.
    """
    # Use in-memory saver if no checkpointer provided (development)
    if checkpointer is None:
        checkpointer = InMemorySaver()
    
    # Build state graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(ALL_TOOLS))
    
    # Set entry and exit
    graph.set_entry_point("agent")
    # Route tool calls or end
    graph.add_conditional_edges("agent", route_tool_calls)
    graph.add_edge("tools", "agent")
    
    # Compile with checkpointer for persistent state across calls
    compiled = graph.compile(checkpointer=checkpointer)
    
    return compiled


def get_compiled_graph(checkpointer=None):
    """Factory to get or create the compiled graph."""
    return build_graph(checkpointer=checkpointer)
