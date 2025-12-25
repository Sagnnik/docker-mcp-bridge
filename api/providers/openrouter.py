from utils.prompts import LLM_TOOL_SCHEMAS
from config import settings
from providers.base import LLMProvider, should_expose
from typing import Dict, List, Optional, Any, AsyncGenerator
from openai import AsyncOpenAI

class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str=None):
        self.api_key = api_key or settings.openrouter_api_key
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
    
    async def generate_stream(self, 
        messages: List[Dict], 
        model: str, 
        tools: Optional[List[Dict]], 
        mode: str = "dynamic",
        **kwargs
    ) -> AsyncGenerator:
        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120.0
        )

        request_kwargs = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs
        }

        if tools:
            request_kwargs['tools'] = self.format_tool_for_provider(tools, mode)
            request_kwargs['tool_choice'] = "auto"

        stream = await client.chat.completions.create(**request_kwargs)

        accumulated_content = ""
        accumulated_tool_calls = []
        finish_reason = None

        async for chunk in stream:
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                accumulated_content +=delta
                yield {
                    "type": "content_delta",
                    "content": delta.content
                }

            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    while len(accumulated_tool_calls) <= tc_delta.index:
                        accumulated_tool_calls.append({
                            "id": None,
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        })

                    tool_call = accumulated_tool_calls[tc_delta.index]

                    if tc_delta.id:
                        tool_call['id'] = tc_delta.id

                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_call["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_call["function"]["arguments"] += tc_delta.function.arguments

        assistant_message = {
            "role": "assistant",
            "content": accumulated_content or None
        }

        if accumulated_tool_calls:
            assistant_message['tool_calls'] = accumulated_tool_calls

        # Normalize finish_reason before yielding
        finish_reason_map = {
            "stop": "stop",
            "length": "length",
            "tool_calls": "tool_calls",
            "content_filter": "content_filter",
            "function_call": "tool_calls",
        }
        normalized_finish_reason = finish_reason_map.get(finish_reason, finish_reason) if finish_reason else None

        yield {
            "type": "complete",
            "message": assistant_message,
            "finish_reason": normalized_finish_reason
        }