from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, AsyncGenerator

def should_expose(name:str, mode:str):
    exposed_tools = {"mcp-find", "mcp-add", "code-mode", "mcp-exec"} 
    code_mode_tools = {"code-mode", "mcp-exec"}
    not_expose_default = {"mcp-add", "mcp-config-set", "mcp-remove"}
    not_expose = {"mcp-config-set", "mcp-remove"}

    def is_custom(name:str):
        return name.startswith("code-mode-")
    
    if mode == 'default':
        if name in not_expose_default:
            return False
        if name in exposed_tools:
            return False
        if is_custom(name):
            return False
        return True
    
    elif mode == 'dynamic':
        if name in not_expose:
            return False
        if name in code_mode_tools:
            return False
        if is_custom(name):
            return False
        return True
    elif mode == 'code':
        if name in not_expose:
            return False
        if name in exposed_tools:
            return True
        if is_custom(name):
            return True
        return False
    else:
        raise ValueError(f"Unknown Mode: {mode}")

class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, messages: List[Dict], model:str, tools: Optional[List[Dict]], **kwargs):
        pass

    @abstractmethod
    async def generate_stream(self, messages: List[Dict], model:str, tools: Optional[List[Dict]], mode: str, **kwargs) -> AsyncGenerator:
        pass

    @abstractmethod
    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='dynamic'):
        pass