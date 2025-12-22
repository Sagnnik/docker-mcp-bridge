from langfuse import Langfuse
from config import settings
from typing import Optional
from logger import logger

_langfuse: Optional[Langfuse] = None


def init_langfuse(settings):
    global _langfuse

    if not settings.langfuse_enabled:
        return None

    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
        )

    return _langfuse

def get_langfuse() -> Optional[Langfuse]:
    return _langfuse


def flush_langfuse():
    """Flush tracing on shutdown"""
    langfuse_client = get_langfuse()
    if settings.langfuse_enabled and langfuse_client:
        try:
            langfuse_client.flush()
            logger.info("Langfuse traces flushed")
        except Exception as e:
            logger.error(f"Error flushing Langfuse: {e}")

            