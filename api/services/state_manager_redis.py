from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import json
from services.redis_client import get_redis_client

INTERRUPT_KEY_PREFIX = "interrupt_state:"
DEFAULT_TTL = 3600

async def store_interrupt_state(
    interrupt_id: str,
    messages: list,
    active_servers: list,
    available_tools: list,
    pending_tool_call: dict,
    server_name: str,
    required_configs: list,
    mode: str,
    model: str,
    provider: str,
    max_iterations: int,
    current_iteration: int,
    mcp_find_cache: dict
) -> None:
    redis_client = await get_redis_client()
    
    state = {
        "messages": messages,
        "active_servers": active_servers,
        "available_tools": available_tools,
        "pending_tool_call": pending_tool_call,
        "server_name": server_name,
        "required_configs": required_configs,
        "mode": mode,
        "model": model,
        "provider": provider,
        "max_iterations": max_iterations,
        "current_iteration": current_iteration,
        "mcp_find_cache": mcp_find_cache,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ttl": DEFAULT_TTL
    }
    
    key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
    
    await redis_client.setex(
        key,
        DEFAULT_TTL,
        json.dumps(state, default=str)
    )

async def get_interrupt_state(interrupt_id: str) -> Optional[Dict[str, Any]]:
    redis_client = await get_redis_client()
    
    key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
    data = await redis_client.get(key)
    
    if not data:
        return None
    state = json.loads(data)
    state['created_at'] = datetime.fromisoformat(state['created_at'])
    
    return state

async def cleanup_interrupt_state(interrupt_id: str) -> None:
    redis_client = await get_redis_client()
    
    key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
    await redis_client.delete(key)

def generate_interrupt_id() -> str:
    return str(uuid.uuid4())