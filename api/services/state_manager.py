from typing import Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import json
from config import settings
from services.redis_client import get_redis_client

INTERRUPT_KEY_PREFIX = "interrupt_state:"
DEFAULT_TTL = 3600
_interrupt_states: Dict[str, Dict[str, Any]] = {}

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
    mcp_find_cache: dict,
) -> None:
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
        "created_at": datetime.now(timezone.utc),
        "ttl": DEFAULT_TTL,
    }

    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
        payload = state.copy()
        payload['created_at'] = payload['created_at'].isoformat()

        await r.setex(
            key,
            DEFAULT_TTL,
            json.dumps(payload, default=str)
        )
        return
    
    _interrupt_states[interrupt_id] = state

async def get_interrupt_state(interrupt_id: str) -> Optional[Dict[str, Any]]:
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"

        data = await r.get(key)
        if not data:
            return None

        state = json.loads(data)
        state["created_at"] = datetime.fromisoformat(state["created_at"])
        return state
    
    state = _interrupt_states.get(interrupt_id)
    if not state:
        return None
    
    elapsed = (datetime.now(timezone.utc) - state["created_at"]).total_seconds()
    if elapsed > state["ttl"]:
        _interrupt_states.pop(interrupt_id, None)
        return None
    
    return state

async def cleanup_interrupt_state(interrupt_id: str) -> None:
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{INTERRUPT_KEY_PREFIX}{interrupt_id}"
        await r.delete(key)
        return
    
    _interrupt_states.pop(interrupt_id, None)

def generate_interrupt_id() -> str:
    return str(uuid.uuid4())
      