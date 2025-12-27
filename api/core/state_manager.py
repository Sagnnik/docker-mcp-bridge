from typing import Dict, Any, Optional, Set
from datetime import datetime, timezone
import uuid
import json
from config import settings
from services.redis_client import get_redis_client

INTERRUPT_KEY_PREFIX = "interrupt_state:"
DEFAULT_TTL = 3600 # 1 hr
_interrupt_states: Dict[str, Dict[str, Any]] = {}

USER_SERVER_TOOLS_KEY_PREFIX = "user_server_tools:"
USER_DATA_TTL = 21600 # 6 hr

# In-memory fallback: user_id -> {server_name: Set[tool_names]}
_user_server_tools: Dict[str, Dict[str, Set[str]]] = {}

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

# Server & Tools Tracking

async def add_user_server(user_id: str, server_name: str, tool_names: Set[str]) -> None:
    """
    Register a server and its tools for a user
    Stores server_name -> tools mapping in HSET
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        
        await r.hset(key, server_name, json.dumps(list(tool_names)))
        await r.expire(key, USER_DATA_TTL)
        return
    
    if user_id not in _user_server_tools:
        _user_server_tools[user_id] = {}
    _user_server_tools[user_id][server_name] = tool_names.copy()

async def remove_user_server(user_id: str, server_name: str) -> None:
    """
    Remove a server and all its tools from user's list
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        await r.hdel(key, server_name)
        return
    
    if user_id in _user_server_tools:
        _user_server_tools[user_id].pop(server_name, None)

async def get_user_servers(user_id: str) -> Set[str]:
    """
    Get all active server names for a user
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        servers = await r.hkeys(key)
        return set(servers) if servers else set()
    
    return set(_user_server_tools.get(user_id, {}).keys())

async def get_user_tools(user_id: str) -> Set[str]:
    """
    Get all tools available to a user (flattened from all servers)
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        
        # Get all server->tools mappings
        server_tools_map = await r.hgetall(key)
        
        all_tools = set()
        for server_name, tools_json in server_tools_map.items():
            tools = json.loads(tools_json)
            all_tools.update(tools)
        
        return all_tools
    
    all_tools = set()
    for server_tools in _user_server_tools.get(user_id, {}).values():
        all_tools.update(server_tools)
    return all_tools

async def get_server_tools(user_id: str, server_name: str) -> Set[str]:
    """
    Get tools for a specific server
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        
        tools_json = await r.hget(key, server_name)
        if not tools_json:
            return set()
        
        return set(json.loads(tools_json))
    
    return _user_server_tools.get(user_id, {}).get(server_name, set()).copy()

async def get_user_server_tools_map(user_id: str) -> Dict[str, Set[str]]:
    """
    Get complete mapping of server_name -> tools for a user
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        
        server_tools_map = await r.hgetall(key)
        
        result = {}
        for server_name, tools_json in server_tools_map.items():
            result[server_name] = set(json.loads(tools_json))
        
        return result
    
    result = {}
    for server_name, tools in _user_server_tools.get(user_id, {}).items():
        result[server_name] = tools.copy()
    return result

async def clear_user_servers(user_id: str) -> None:
    """
    Clear all servers and tools for a user
    """
    if settings.redis_enabled:
        r = await get_redis_client()
        key = f"{USER_SERVER_TOOLS_KEY_PREFIX}{user_id}"
        await r.delete(key)
        return
    
    _user_server_tools.pop(user_id, None)

# Utility Functions

async def get_user_stats(user_id: str) -> Dict:
    """
    Get stats for a user's MCP usage
    """
    servers = await get_user_servers(user_id)
    tools = await get_user_tools(user_id)
    server_tools_map = await get_user_server_tools_map(user_id)

    return {
        "user_id": user_id,
        "active_servers": list(servers),
        "server_count": len(servers),
        "available_tools": list(tools),
        "tool_count": len(tools),
        "server_tools_info": {
            server: list(tools) for server, tools in server_tools_map.items()
        }
    }

      