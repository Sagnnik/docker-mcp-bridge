from typing import Dict, Any, Optional, Set
from datetime import datetime, timezone
import uuid
import json
from config import settings
from services.redis_client import get_redis_client

INTERRUPT_KEY_PREFIX = "interrupt_state:"
DEFAULT_TTL = 3600 # 1 hr
_interrupt_states: Dict[str, Dict[str, Any]] = {}

USER_SERVER_KEY_PREFIX = "user_servers:"
USER_TOOLS_KEY_PREFIX = "user_tools:"
USER_DATA_TTL = 21600 # 6 hr
# In-memory fallback
_user_servers: Dict[str, Set[str]] = {}
_user_tools: Dict[str, Set[str]] = {}

# Interrupt Tracking

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

# Server Tracking

async def add_user_server(user_id: str, server_name:str) -> None:
    """Register user activated server"""

    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_KEY_PREFIX}{user_id}"

        await r.sadd(key, server_name)
        await r.expire(key, USER_DATA_TTL)
        return
    
    if user_id not in _user_servers:
        _user_servers[user_id] = set()
    _user_servers[user_id].add(server_name)

async def remove_user_server(user_id:str, server_name:str) -> None:
    """Remove server from user active server list"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_KEY_PREFIX}{user_id}"
        await r.srem(key, server_name)
        return 
    
    if user_id in _user_servers:
        _user_servers[user_id].discard(server_name)

async def get_user_servers(user_id: str) -> Set[str]:
    """Get all the active user servers"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_KEY_PREFIX}{user_id}"
        servers = await r.smembers(key)

        return servers
    
    return _user_servers.get(user_id, set())

async def clear_user_servers(user_id:str) -> None:
    """Clear all active servers for user"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_KEY_PREFIX}{user_id}"
        await r.delete(key)
        return
    
    _user_servers.pop(user_id, None)

# Tracking per user tool list

async def set_user_tools(user_id: str, tool_names: Set[str]) -> None:
    """
    Set the complete list of tools available for the user
    Replaces any existing tools for this user
    """

    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_TOOLS_KEY_PREFIX}{user_id}"
        await r.delete(key)

        if tool_names:
            await r.sadd(key, *tool_names)
            await r.expire(key, USER_DATA_TTL)
        return
    
    _user_tools[user_id] = tool_names.copy()

async def add_user_tools(user_id:str, tool_names: Set[str]) -> None:
    """Add tools to user's available tool list"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_TOOLS_KEY_PREFIX}{user_id}"
        
        if tool_names:
            await r.sadd(key, *tool_names)
            await r.expire(key, USER_DATA_TTL)
        return
    
    if user_id not in _user_tools:
        _user_tools[user_id] = set()
    _user_tools[user_id].update(tool_names)

async def remove_user_tools(user_id:str, tool_names: Set[str])-> None:
    """Remove tools to user's available tool list"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_TOOLS_KEY_PREFIX}{user_id}"

        if tool_names:
            await r.srem(key, *tool_names)
        return
    
    if user_id in _user_tools:
        _user_tools[user_id].difference_update(tool_names)

async def get_user_tools(user_id:str) -> Set[str]:
    """Get all tools available for this user"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_TOOLS_KEY_PREFIX}{user_id}"
        tools = await r.smembers(key)
        return tools
    
    return _user_tools.get(user_id, set()).copy()

async def clear_user_tools(user_id:str) -> None:
    """Clear all tools for a user"""
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_TOOLS_KEY_PREFIX}{user_id}"
        await r.delete(key)
        return
    
    _user_tools.pop(user_id, None)

# Utility Functions

async def get_user_stats(user_id:str) -> Dict:
    """Get stats for a user's MCP usage"""

    servers = await get_user_servers(user_id)
    tools = await get_user_servers(user_id)

    return {
        "user_id": user_id,
        "active_servers": list(servers),
        "server_count": len(servers),
        "available_tools": list(tools),
        "tool_count": len(tools),
    }

      