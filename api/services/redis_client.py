import redis.asyncio as redis
from typing import Optional
import os

_redis_client: Optional[redis.Redis] = None

async def get_redis_client() -> redis.Redis:
    """Get the Redis client instance"""
    global _redis_client
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _redis_client

async def init_redis() -> None:
    """Initialize Redis connection"""
    global _redis_client
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    
    _redis_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=10
    )

    await _redis_client.ping()
    print("Redis connected successfully")

async def close_redis() -> None:
    """Close Redis connection"""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
        print("Redis connection closed")