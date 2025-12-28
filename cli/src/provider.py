from abc import ABC, abstractmethod
from openai import AsyncOpenAI
from typing import Dict, List, Optional, Any, AsyncGenerator
import os
from cli.src.prompts import LLM_TOOL_SCHEMAS
from dotenv import load_dotenv
load_dotenv()
    
def should_expose(name:str, mode:str):
    exposed_tools = {"mcp-find", "code-mode", "mcp-exec"} 
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
    async def generate(self, messages: List[Dict], model:str, tools: Optional[List[Dict]]):
        pass

    @abstractmethod
    async def generate_stream(self, messages: List[Dict], model:str, tools: Optional[List[Dict]], mode: str) -> AsyncGenerator:
        pass

    @abstractmethod
    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='default'):
        pass
    
class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set. Please set it in your environment.")

    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='dynamic'):
        """
        Convert MCP tool definitions to OpenAI function tools
        Now handles dynamic MCP tools (mcp-find, mcp-add, mcp-remove) and code-mode
        Modes: 
        - default: Added servers in docker compose
        - dynamic: tool search tool
        - code: LLM creates custom tool
        """ 
        tools: List[Dict[str, Any]] = []
        for t in mcp_tools:
            name = t.get('name')
            if not name or not should_expose(name, mode):
                continue

            description = t.get("description", "")
            # Use cleaner schemas for dynamic mcps
            if name in LLM_TOOL_SCHEMAS:
                input_schema = LLM_TOOL_SCHEMAS[name]
            else:
                # For other tools, use original schema with fixes
                input_schema = t.get("inputSchema", {})
                if input_schema.get('type') is None:
                    input_schema['type'] = 'object'
                if 'properties' not in input_schema:
                    input_schema['properties'] = {}
                input_schema.setdefault("additionalProperties", False)

            tools.append(
                {
                    "type": "function",
                    "function": { 
                        "name": name,
                        "description": description,
                        "parameters": input_schema,
                    }
                }
            )

        return tools
    
    async def generate(
        self, 
        messages: List[Dict], 
        model: str, 
        tools: Optional[List[Dict]], 
        mode: str = "dynamic"
    ):
        client = AsyncOpenAI(
            api_key=self.api_key,
            timeout=120.0
        )
        kwargs = {
            "model": model,
            "messages": messages
        }

        if tools:
            kwargs['tools'] = self.format_tool_for_provider(tools, mode)
            kwargs['tool_choice'] = "auto"
        
        response = await client.chat.completions.create(**kwargs)

        choice = response.choices[0]
        assistant_message = choice.message.model_dump()
        finish_reason = choice.finish_reason
        data = response.model_dump()
        return data, assistant_message, finish_reason

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str=None):
        self.api_key = api_key or os.getenv('OPENROUTER_API_KEY')
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set. Please set it in your environment")
        
        self.base_url = "https://openrouter.ai/api/v1"

    def format_tool_for_provider(self, mcp_tools: List[Dict[str, Any]], mode: str='dynamic'):
        """OpenRouter uses OpenAI compatible tool format"""
        tools: List[Dict[str, Any]] = []
        for t in mcp_tools:
            name = t.get('name')
            if not name or not should_expose(name, mode):
                continue

            description = t.get("description", "")
            if name in LLM_TOOL_SCHEMAS:
                input_schema = LLM_TOOL_SCHEMAS[name]
            else:
                input_schema = t.get("inputSchema", {})
                if input_schema.get('type') is None:
                    input_schema['type'] = 'object'
                if 'properties' not in input_schema:
                    input_schema['properties'] = {}
                input_schema.setdefault("additionalProperties", False)

            tools.append(
                {
                    "type": "function",
                    "function": { 
                        "name": name,
                        "description": description,
                        "parameters": input_schema,
                    }
                }
            )

        return tools
    
    def normalize_response(self, response_data:Dict, assistant_message:Dict, finish_reason:str) -> tuple:
        """Need to normalize the Openrouter responses to OpenAI format"""
        finish_reason_map = {
            "stop": "stop",
            "length": "length",
            "tool_calls": "tool_calls",
            "content_filter": "content_filter",
            "function_call": "tool_calls",
        }
        normalized_finish_reason = finish_reason_map.get(finish_reason, finish_reason)

        if assistant_message.get('tool_calls'):
            normalized_tool_calls = []
            for tc in assistant_message['tool_calls']:
                normalized_tc = {
                    "id": tc.get('id'),
                    "type": "function",
                    "function":{
                        "name": tc.get('function', {}).get('name'),
                        "arguments": tc.get('function', {}).get('arguments')
                    }
                }
                normalized_tool_calls.append(normalized_tc)

            assistant_message['tool_calls'] = normalized_tool_calls

        return response_data, assistant_message, normalized_finish_reason
    
    async def generate(
        self, 
        messages: List[Dict], 
        model: str, 
        tools: Optional[List[Dict]], 
        mode: str = "dynamic",
        **kwargs
    ):
        """
        Openrouter accepts extra_body param
        kwargs = {
            "temperature": 0.7,
            "max_tokens": 2000,
            "top_p": 0.9,
            "extra_body": {
                "provider": {
                    "order": ["Moonshot"],
                    "allow_fallbacks": False
                }
            }
        }
        Can add:
        - Model fallbacks: List(model_names)
        - Adjust Reasoning: max_tokens, effort[high, medium, low]
        """
        
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120.0
        )

        request_kwargs = {
            "model": model,
            "messages": messages,
            **kwargs
        }

        if tools:
            request_kwargs['tools'] = self.format_tool_for_provider(tools, mode)
            request_kwargs['tool_choice'] = "auto"

        response = await client.chat.completions.create(**request_kwargs)

        choice = response.choices[0]
        assistant_message = choice.message.model_dump()
        finish_reason = choice.finish_reason
        data = response.model_dump()

        return self.normalize_response(data, assistant_message, finish_reason)
                        
    
class LLMProviderFactory:
    _providers: Dict[str, LLMProvider] = {}

    @classmethod
    def initialize_provider(cls):
        cls._providers = {
            "openai": OpenAIProvider(),
            "openrouter": OpenRouterProvider(),
        }

    @classmethod
    def get_provider(cls, provider_name: str) -> LLMProvider:
        if not cls._providers:
            cls.initialize_provider()
        
        if provider_name not in cls._providers:
            raise ValueError(f"Unknown provider: {provider_name}")
        return cls._providers[provider_name]