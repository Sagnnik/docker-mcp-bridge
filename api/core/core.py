import json
from utils.logger import logger
from typing import Dict, Any, List, Optional, AsyncGenerator
from utils.prompts import MCP_BRIDGE_MESSAGES
from models import AgentResult
from langfuse import observe

TOOL_CHANGE_TRIGGERS = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

class AgentCore:
    def __init__(self, client, provider, mode:str):
        self.client = client
        self.provider = provider
        self.mode = mode
        self.mcp_find_cache: Dict[str, Dict[str, Any]] = {}

    async def prepare_messages(self, messages: List[Dict[str, Any]], mode:str)->List[Dict[str, Any]]:
        prepared = [
            {
                "role": m["role"],
                "content": m["content"]
            }
            for m in messages
        ]
        sys_msg = None
        sys_msg_index = -1
        for i, m in enumerate(prepared):
            if m.get("role") == "system":
                sys_msg = m
                sys_msg_index = i
                break

        if sys_msg:
            new_sys_msg = sys_msg["content"].rstrip() + "\n\n--- Your Additional Instructions for MCP Bridge Client ---\n\n"+ MCP_BRIDGE_MESSAGES.get(mode)
            prepared[sys_msg_index]['content'] = new_sys_msg

        else:
            prepared.insert(0, {
                "role": "system",
                "content": MCP_BRIDGE_MESSAGES.get(mode)
            })
        
        return prepared
    
    @observe(name="handle_tool_call")
    async def handle_tool_call(self, tool_name:str, tool_args: Dict[str, Any], tool_call_id:str)-> Dict[str, Any]:
        """
        Returns:
        Dict with 'status', 'result_text' and optional interrupt info
        """

        try:
            if tool_name == "mcp-find":
                return await self._handle_mcp_find(tool_args)
            
            elif tool_name == "mcp-add":
                return await self._handle_mcp_add(tool_args, tool_call_id)
            
            elif tool_name in ['code-mode', 'mcp-exec']:
                logger.info(f"\n[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                result = await self.client.call_tool(tool_name, tool_args)
                return {"status": "success", "result_text": json.dumps(result)}
            else:
                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                result = await self.client.call_tool(tool_name, tool_args)
                if isinstance(result, dict) and 'content' in result:
                    result_text = self.client._parse_response(result['content'])
                else:
                    result_text = json.dumps(result)

                return {"status": "success", "result_text": result_text}
            
        except Exception as e:
            logger.error(f"Tool call error: {str(e)}")
            return {"status": "error", "result_text": f"Error: {str(e)}"}
        
    async def _handle_mcp_find(self, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"\n[tool name]: mcp-find\n [tool args]: {tool_args}\n")
        result = await self.client.call_tool("mcp-find", tool_args)
        result_text = json.dumps(result)

        if isinstance(result, dict) and 'content' in result:
            text = self.client._parse_response(result['content'])
            try:
                payload = json.loads(text)
                servers = payload.get("servers", [])
                for server_info in servers:
                    if isinstance(server_info, dict) and 'name' in server_info:
                        self.mcp_find_cache[server_info['name']] = server_info

            except json.JSONDecodeError:
                pass

        return {"status": "success", "result_text": result_text}
    
    async def _handle_mcp_add(self, tool_args: Dict[str, Any], tool_call_id: str) -> Dict[str, Any]:
        logger.info(f"\n[tool name]: mcp-add\n[tool args]: {tool_args}\n")
        server_name = tool_args.get('name', '').strip()
        cached_find = self.mcp_find_cache.get(server_name)
        mcp_find_result = [cached_find] if cached_find else None

        add_result = await self.client.add_server_llm(
            server_name=server_name,
            activate=tool_args.get('activate', True),
            mcp_find_result=mcp_find_result
        )

        if add_result.status == "secrets_required":
            return {
                "status": "secrets_required",
                "result_text": json.dumps({
                    "status": "secrets_required",
                    "required_secrets": add_result.required_secrets or [],
                }),
                "interrupt_data": {
                    "server": add_result.server,
                    "required_secrets": add_result.required_secrets,
                    "instructions": add_result.instructions
                }
            }
        
        elif add_result.status == "config_required":
            return {
                "status": "config_required",
                "result_text": json.dumps({
                    "status": "config_required",
                    "required_configs": add_result.required_configs or [],
                }),
                "interrupt_data": {
                    "server": add_result.server,
                    "required_configs": add_result.required_configs,
                    "instructions": add_result.instructions
                }
            }
        
        elif add_result.status == "added":
            return {
                "status": "success",
                "result_text": json.dumps({
                    "status": "success",
                    "message": add_result.message or "Server added successfully"
                })
            }
        
        else:  # "failed"
            return {
                "status": "failed",
                "result_text": json.dumps({
                    "status": "failed",
                    "message": add_result.message or "Failed to add server"
                })
            }
        
    @observe(name="agent_loop")   
    async def run_agent_loop(
        self, 
        messages: List[Dict[str, Any]], 
        model:str, 
        max_iterations: int, 
        current_iteration: int=0
    ) -> AgentResult:
        """
        Run the main agent loop
        
        Args:
            messages: Conversation messages
            model: Model name
            max_iterations: Maximum iterations
            current_iteration: Starting iteration (for resume)
        
        Returns:
            AgentResult with finish reason and optional interrupt data
        """

        tools = await self.client.list_tools()

        for iteration in range(current_iteration, max_iterations):
            logger.info(f"Iteration {iteration+1}/{max_iterations}")

            response, assistant_msg, finish_reason = await self.provider.generate(
                messages=messages,
                model=model,
                tools=tools,
                mode=self.mode
            )
            
            messages.append(assistant_msg)

            if finish_reason == 'stop':
                return AgentResult(
                    finish_reason=finish_reason,
                    content=assistant_msg.get('content', ''),
                    messages=messages
                )
            
            if finish_reason == "tool_calls" and assistant_msg.get('tool_calls'):
                tools_changed = False

                for tc in assistant_msg['tool_calls']:
                    tool_name = tc['function']['name']
                    tool_args = json.loads(tc['function']['arguments'])
                    
                    if tool_name in TOOL_CHANGE_TRIGGERS:
                        tools_changed = True
                    
                    logger.info(f"Calling tool: {tool_name}")

                    tool_result = await self.handle_tool_call(tool_name, tool_args, tc['id'])

                    # Check for interrupts
                    if tool_result['status'] in ["secrets_required", "config_required"]:
                        messages.append({
                            "tool_call_id": tc['id'],
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result["result_text"]
                        })

                        interrupt_data = tool_result["interrupt_data"]
                        return AgentResult(
                            finish_reason="interrupt",
                            content="",
                            messages=messages,
                            interrupt_type=tool_result["status"],
                            server=interrupt_data["server"],
                            required_configs=interrupt_data.get("required_configs"),
                            required_secrets=interrupt_data.get("required_secrets"),
                            instructions=interrupt_data.get("instructions")
                        )
                    
                    messages.append({
                        "tool_call_id": tc['id'],
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_result["result_text"]
                    })
                
                if tools_changed:
                    tools = await self.client.list_tools()
                    logger.info(f"Tools refreshed, now have {len(tools)} tools")
                
                continue
            
            logger.warning(f"Unexpected finish reason: {finish_reason}")
            break
        
        return AgentResult(
            finish_reason="max_iteration",
            content="Max iterations reached",
            messages=messages
        )
    
    @observe(name="agent_loop_streaming")
    async def run_agent_loop_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        max_iterations: int,
        current_iteration: int = 0
    ) -> AsyncGenerator:
        """
        Run the main agent loop with streaming
        
        Yields events:
            - {'type': 'iteration', 'number': int}
            - {'type': 'content', 'data': str}
            - {'type': 'tool_call', 'tool': str, 'args': dict}
            - {'type': 'tool_result', 'tool': str, 'result': str}
            - {'type': 'tool_error', 'tool': str, 'error': str}
            - {'type': 'config_required', ...}
            - {'type': 'secrets_required', ...}
            - {'type': 'done', 'finish_reason': str}
        """
        tools = await self.client.list_tools()

        for iteration in range(current_iteration, max_iterations):
            yield {'type': 'iteration', 'number': iteration + 1}

            assistant_msg = {"role": "assistant", "content": None}
            finish_reason = None

            async for chunk in self.provider.generate_stream(
                messages=messages,
                model=model,
                tools=tools,
                mode=self.mode
            ):
                if chunk['type'] == "content_delta":
                    yield {'type': 'content', 'data': chunk['content']}

                elif chunk['type'] == "complete":
                    assistant_msg = chunk["message"]
                    finish_reason = chunk["finish_reason"]

            messages.append(assistant_msg)

            if finish_reason == 'stop':
                yield {'type': 'done', 'finish_reason': finish_reason}
                return
            
            if finish_reason == 'tool_calls' and assistant_msg.get('tool_calls'):
                tools_changed = False
                
                for tc in assistant_msg['tool_calls']:
                    tool_name = tc['function']['name']
                    tool_args = json.loads(tc['function']['arguments'])
                    
                    if tool_name in TOOL_CHANGE_TRIGGERS:
                        tools_changed = True
                    
                    yield {'type': 'tool_call', 'tool': tool_name, 'args': tool_args}
                    
                    # Handle the tool call
                    tool_result = await self.handle_tool_call(tool_name, tool_args, tc['id'])

                    if tool_result["status"] in ["secrets_required", "config_required"]:
                        messages.append({
                            "tool_call_id": tc['id'],
                            "role": "tool",
                            "name": tool_name,
                            "content": tool_result["result_text"]
                        })
                        
                        interrupt_data = tool_result["interrupt_data"]
                        if tool_result["status"] == "config_required":
                            yield {
                                'type': tool_result["status"],
                                'server': interrupt_data["server"],
                                'instructions': interrupt_data.get("instructions"),
                                'required_configs': interrupt_data.get("required_configs")
                            }
                        else:
                            yield {
                                'type': tool_result["status"],
                                'server': interrupt_data["server"],
                                'instructions': interrupt_data.get("instructions"),
                                'required_secrets': interrupt_data.get("required_secrets")
                            }
                        return
                    
                    # Tool error
                    if tool_result["status"] == "error":
                        yield {
                            'type': 'tool_error',
                            'tool': tool_name,
                            'error': tool_result["result_text"]
                        }
                    else:
                        yield {
                            'type': 'tool_result',
                            'tool': tool_name,
                            'result': tool_result["result_text"][:500]
                        }
                    
                    messages.append({
                        "tool_call_id": tc['id'],
                        "role": "tool",
                        "name": tool_name,
                        "content": tool_result["result_text"]
                    })
                
                if tools_changed:
                    tools = await self.client.list_tools()
                    logger.info(f"Tools refreshed, now have {len(tools)} tools")
                
                continue
            
            logger.warning(f"Unexpected finish reason: {finish_reason}")
            break
        
        yield {'type': 'done', 'finish_reason': 'max_iteration'}