"""Checkpoint storage helpers for LangGraph session state."""
from contextlib import ExitStack

from langgraph.checkpoint.memory import InMemorySaver

from src.settings import settings


checkpoint_context = ExitStack()


def build_checkpointer():
    """Return the configured LangGraph checkpointer.

    Local development uses an in-memory checkpointer. Cloud deployments can set
    USE_POSTGRES_CHECKPOINTER=true and POSTGRES_URI to persist sessions in a
    managed Postgres database such as Cloud SQL, Neon, Supabase, or Render.
    """
    if settings.USE_POSTGRES_CHECKPOINTER:
        if not settings.POSTGRES_URI:
            raise ValueError("Set POSTGRES_URI when USE_POSTGRES_CHECKPOINTER=true")

        from langgraph.checkpoint.postgres import PostgresSaver

        checkpointer = checkpoint_context.enter_context(
            PostgresSaver.from_conn_string(settings.POSTGRES_URI)
        )
        checkpointer.setup()
        return checkpointer

    if settings.USE_MONGODB_CHECKPOINTER:
        raise ValueError(
            "MongoDB checkpointing is not wired in this prototype. "
            "Use USE_POSTGRES_CHECKPOINTER=true with POSTGRES_URI, or leave both disabled."
        )

    return InMemorySaver()


def close_checkpointer_context() -> None:
    """Close any long-lived checkpoint connections."""
    checkpoint_context.close()
