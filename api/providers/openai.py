from utils.prompts import LLM_TOOL_SCHEMAS
from config import settings
from providers.base import LLMProvider, should_expose
from typing import Dict, List, Optional, Any, AsyncGenerator
from openai import AsyncOpenAI

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.openai_api_key
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
        mode: str = "dynamic",
        **kwargs
    ):
        client = AsyncOpenAI(
            api_key=self.api_key,
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
        return data, assistant_message, finish_reason
    
    async def generate_stream(self, 
        messages: List[Dict], 
        model: str, 
        tools: Optional[List[Dict]], 
        mode: str = "dynamic",
        **kwargs
    ) -> AsyncGenerator:
        """
        Streaming generation (for /sse/chat endpoint)
        Yields chunks as they arrive from OpenAI
        """
        client = AsyncOpenAI(
            api_key=self.api_key,
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

        # For tool calls accumulate the response
        accumulated_content = ""
        accumulated_tool_calls = []
        finish_reason = None

        async for chunk in stream:
            delta = chunk.choices[0].delta
            finish_reason = chunk.choices[0].finish_reason

            if delta.content:
                accumulated_content += delta.content
                yield {
                    "type": "content_delta",
                    "content": delta.content
                }

            # Accumulate tool call chunks
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    # add empty tool call
                    while len(accumulated_tool_calls) <= tc_delta.index:
                        accumulated_tool_calls.append({
                            "id": None,
                            "type": "function",
                            "function": {"name": "", "arguments": ""}
                        })

                    tool_call = accumulated_tool_calls[tc_delta.index]

                    # if tool call - format the empty tool call
                    if tc_delta.id:
                        tool_call['id'] = tc_delta.id

                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_call["function"]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_call["function"]["arguments"] += tc_delta.function.arguments
        
        # Yield the complete assistant message
        assistant_message = {
            "role": "assistant",
            "content": accumulated_content or None
        }

        if accumulated_tool_calls:
            assistant_message['tool_calls'] = accumulated_tool_calls

        yield {
            "type": "complete",
            "message": assistant_message,
            "finish_reason": finish_reason
        }