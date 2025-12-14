from typing import Dict, Any, Optional
from datetime import datetime
import uuid

# Could use redis
interrupt_states: Dict[str, Dict[str, Any]] = {}

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
    """Store interrupt state for later resumption"""
    interrupt_states[interrupt_id] = {
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
        "created_at": datetime.utcnow(),
        "ttl": 3600  # 1 hour
    }

async def get_interrupt_state(interrupt_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve interrupt state if it exists and hasn't expired"""
    state = interrupt_states.get(interrupt_id)
    
    if not state:
        return None
    
    # Check TTL
    elapsed = (datetime.utcnow() - state['created_at']).total_seconds()
    if elapsed > state['ttl']:
        interrupt_states.pop(interrupt_id, None)
        return None
    
    return state

async def cleanup_interrupt_state(interrupt_id: str) -> None:
    """Remove interrupt state after successful resumption"""
    interrupt_states.pop(interrupt_id, None)

def generate_interrupt_id() -> str:
    """Generate unique interrupt ID"""
    return str(uuid.uuid4())