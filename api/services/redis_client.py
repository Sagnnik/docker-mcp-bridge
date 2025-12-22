import redis.asyncio as redis
from typing import Optional
from config import settings

_redis_client: Optional[redis.Redis] = None

async def get_redis_client() -> Optional[redis.Redis]:
    global _redis_client

    if not settings.redis_enabled:
        return None

    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")

    return _redis_client


async def init_redis() -> None:
    global _redis_client

    if not settings.redis_enabled:
        return

    if _redis_client is not None:
        return

    _redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=10,
    )

    await _redis_client.ping()
    print("Redis connected successfully")


async def close_redis() -> None:
    global _redis_client

    if not settings.redis_enabled:
        return

    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        print("Redis connection closed")
