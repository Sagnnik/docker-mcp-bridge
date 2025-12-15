from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from provider import LLMProviderFactory
from models import (
    ChatResponse, 
    ChatRequest, 
    MCPServerConfig, 
    MCPRemoveRequest, 
    MCPFindRequest, 
    SecretsRequiredResponse, 
    ConfigInterruptResponse, 
    ChatResponseUnion, 
    ChatResumeRequest
)
from state_manager import (
    store_interrupt_state, 
    generate_interrupt_id, 
    get_interrupt_state, 
    cleanup_interrupt_state
)
from gateway_client import MCPGatewayAPIClient
from prompts import MCP_BRIDGE_MESSAGES
from logger import logger
from typing import Dict, Any
import json

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MCP Gateway API...")
    LLMProviderFactory.initialize_provider()
    yield
    logger.info("Shutting down MCP Gateway API...")

app = FastAPI(
    title="MCP Gateway Client",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "mcp-gateway-client"}

@app.post("/chat", response_model=ChatResponseUnion, tags=['chat'])
async def chat(request: ChatRequest):
    """
    Non-streaming chat endpoint with MCP tools
    
    Example:
    ```json
    {
        "messages": [{"role": "user", "content": "What's the weather in SF?"}],
        "model": "gpt-5-mini",
        "provider": "openai",
        "mode": "dynamic",
        "initial_servers": ["weather"]
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            for server in request.inital_servers:
                logger.info(f"Adding initial server: {server}")
                await client.add_server(server)
            provider = LLMProviderFactory.get_provider(request.provider)

            tools = await client.list_tools()

            # Getting the messages and appending the system messages
            messages = [
                {
                    "role": m.role,
                    "content": m.content
                }
                for m in request.messages
            ]
            sys_msg = None
            sys_msg_index = -1
            for i, m in enumerate(messages):
                if m.get("role") == "system":
                    sys_msg = m
                    sys_msg_index = i
                    break

            if sys_msg:
                new_sys_msg = sys_msg["content"].rstrip() + "\n\n--- Your Additional Instructions for MCP Bridge Client ---\n\n"+ MCP_BRIDGE_MESSAGES.get(request.mode)
                messages[sys_msg_index]['content'] = new_sys_msg

            else:
                messages.insert(0, {
                    "role": "system",
                    "content": MCP_BRIDGE_MESSAGES.get(request.mode)
                })
            
            mcp_find_cache: Dict[str, Dict[str, Any]] = {}

            #Agentic Loop
            for iteration in range(request.max_iterations):
                logger.info(f"Iteration {iteration + 1}/{request.max_iterations}")
                response, assistant_msg, finish_reason = await provider.generate(
                    messages=messages,
                    model=request.model,
                    tools=tools,
                    mode=request.mode
                )

                messages.append(assistant_msg)

                if finish_reason == 'stop':
                    return ChatResponse(
                        content=assistant_msg.get('content', ''),
                        active_servers=client.active_servers,
                        available_tools=list(client.available_tools.keys()),
                        finish_reason=finish_reason
                    )
                
                # Handle tool calls
                if finish_reason == "tool_calls" and assistant_msg.get('tool_calls'):
                    tools_changed = False
                    tool_change_triggers = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

                    for tc in assistant_msg['tool_calls']:
                        tool_name = tc['function']['name']
                        tool_args = json.loads(tc['function']['arguments'])

                        if tool_name in tool_change_triggers:
                            tools_changed = True
                        
                        logger.info(f"Calling tool: {tool_name}")

                        try:
                            if tool_name == "mcp-find":
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)
                                
                                # Parse MCP text response
                                if isinstance(result, dict) and "content" in result:
                                    text = client._parse_response(result["content"])
                                    try:
                                        payload = json.loads(text)
                                    except json.JSONDecodeError:
                                        payload = {}
                                else:
                                    payload = {}

                                servers = payload.get("servers", [])

                                for server_info in servers:
                                    if isinstance(server_info, dict) and "name" in server_info:
                                        mcp_find_cache[server_info["name"]] = server_info

                            elif tool_name == "mcp-add":
                                logger.info(f"[tool name]: {tool_name}\n[tool args]: {tool_args}\n")

                                # Get cached find result for this server
                                server_name = tool_args.get('name', '').strip()
                                cached_find = mcp_find_cache.get(server_name)
                                mcp_find_result = [cached_find] if cached_find else None
                                
                                # add_server_llm call
                                add_result = await client.add_server_llm(
                                    server_name=server_name,
                                    activate=tool_args.get('activate', True),
                                    mcp_find_result=mcp_find_result
                                )

                                # check status
                                if add_result.status == "secrets_required":
                                    # HARD STOP - return SecretsRequiredResponse
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc["id"],
                                        "name": "mcp-add",
                                        "content": json.dumps({
                                            "status": "secrets_required",
                                            "required_secrets": add_result.required_secrets or [],
                                        })
                                    })
                                    return SecretsRequiredResponse(
                                        interrupt_type="secrets_required",
                                        server=add_result.server,
                                        required_secrets=add_result.required_secrets,
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools),
                                        message=(
                                            f"Cannot add server '{add_result.server}' - "
                                            f"missing required secrets: {', '.join(add_result.required_secrets or [])}. "
                                            f"Please configure these secrets in your environment/settings "
                                            f"and start a new conversation."
                                        ),
                                        instructions=add_result.instructions
                                    )
                                elif add_result.status == "config_required":
                                    # INTERRUPT - stores states and return interrupt state
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc["id"],
                                        "name": "mcp-add",
                                        "content": json.dumps({
                                            "status": "config_required",
                                            "required_configs": add_result.required_configs or [],
                                        })
                                    })

                                    interrupt_id = generate_interrupt_id()
                                    await store_interrupt_state(
                                        interrupt_id=interrupt_id,
                                        messages=messages,
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools.keys()),
                                        pending_tool_call=tc,
                                        server_name=add_result.server,
                                        required_configs=add_result.required_configs or [],
                                        mode=request.mode,
                                        model=request.model,
                                        provider=request.provider,
                                        max_iterations=request.max_iterations,
                                        current_iteration=iteration,
                                        mcp_find_cache=mcp_find_cache
                                    )

                                    return ConfigInterruptResponse(
                                        interrupt_type="config_required",
                                        server=add_result.server,
                                        required_configs=add_result.required_configs or [],
                                        conversation_state=messages,
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools.keys()),
                                        interrupt_id=interrupt_id,
                                        instructions=add_result.instructions
                                    )
                                
                                elif add_result.status == "added":
                                    # Success
                                    result_text = json.dumps({
                                        "status": "success",
                                        "message": add_result.message or "Server added successfully"
                                    })
                                
                                else:  # "failed"
                                    result_text = json.dumps({
                                        "status": "failed",
                                        "message": add_result.message or "Failed to add server"
                                    })

                            elif tool_name in ['code-mode', 'mcp-exec']:
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)

                            else:
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)

                                if isinstance(result, dict) and 'content' in result:
                                    result_text = client._parse_response(result['content'])

                                else:
                                    result_text = json.dumps(result)

                        except Exception as e:
                            result_text = f"Error: {str(e)}"
                            logger.error(f"Toll call error: {str(e)}")

                        messages.append({
                            "tool_call_id": tc['id'],
                            "role": "tool",
                            "name": tool_name,
                            "content": result_text
                        })

                    if tools_changed:
                        tools = await client.list_tools()
                        logger.info(f"Tools refreshed, now have {len(tools)} tools")

                    continue

                logger.warning(f"Unexpected finish reason: {finish_reason}")
                break

            return ChatResponse(
                content="Max Iteration reached",
                active_servers=client.active_servers,
                available_tools=list(client.available_tools.keys()),
                finish_reason="max_iteration"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/chat/resume", response_model=ChatResponseUnion, tags=['chat'])
async def chat_resume(request: ChatResumeRequest):
    """
    Resume conversation after config interrupt
    
    Example:
    ```json
        {
            "interrupt_id": "abc-123",
            "provided_configs":{
                "github_token": "ghp_...",
            }
        }
    ```
    """  
    try:
        # 1. Retrieve interrupt state
        interrupt_state = await get_interrupt_state(request.interrupt_id)
        logger.info("Restored interrupt state...")
        if not interrupt_state:
            raise HTTPException(
                status_code=404,
                detail=f"Interrupt {request.interrupt_id} not found or expired"
            )
        
        # 2. Check if required configs are provided
        # Then validate that all required configs
        if request.provided_configs:
            required_keys = {cfg['key'] for cfg in interrupt_state['required_configs']}
            provided_keys = set(request.provided_configs.keys())

            if required_keys != provided_keys:
                missing = required_keys - provided_keys
                extra = provided_keys - required_keys
                error_msg = []
                if missing:
                    error_msg.append(f"Missing configs: {', '.join(missing)}")
                if extra:
                    error_msg.append(f"Unexpected configs: {', '.join(extra)}")
                raise HTTPException(
                    status_code=400,
                    detail="; ".join(error_msg)
                )
        # 3. Rebuild client state
        async with MCPGatewayAPIClient() as client:

            for server in interrupt_state['active_servers']:
                try:
                    await client.add_server(server)
                except Exception as e:
                    logger.warning(f"Failed to restore server {server}: {e}")

            server_name = interrupt_state['server_name']
            pending_tc = interrupt_state['pending_tool_call']

            if request.provided_configs:
                logger.info(f"Retrying mcp-add for {server_name} with configs: {list(request.provided_configs.keys())}")

                add_result = await client.add_server(server_name=server_name, activate=True, config=request.provided_configs)
                if isinstance(add_result, dict) and "content" in add_result:
                    result_text = client._parse_response(add_result["content"])
                else:
                    result_text = str(add_result)

                messages = interrupt_state['messages'].copy()
                # Needed to add the previous tool calls and then append the result_text
                # Replay assistant tool call
                messages.append({
                    "role": "assistant",
                    "tool_calls": [pending_tc],
                    "content": None
                })

                # Tool response
                messages.append({
                    "role": "tool",
                    "tool_call_id": pending_tc["id"],
                    "name": "mcp-add",
                    "content": result_text
                })
            else:
                messages = interrupt_state['messages'].copy()

            tools = await client.list_tools()
            logger.info(f"Tools refreshed after resume, now have {len(tools)} tools")
            
            provider = LLMProviderFactory.get_provider(request.provider if request.provider else interrupt_state['provider'])
            mcp_find_cache = interrupt_state.get('mcp_find_cache', {})
            remaining_iterations = interrupt_state['max_iterations'] - interrupt_state['current_iteration'] - 1
            tool_change_triggers = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

            for iteration in range(remaining_iterations):
                logger.info(f"Resume iteration {iteration + 1}/{remaining_iterations}")
                
                response, assistant_msg, finish_reason = await provider.generate(
                    messages=messages,
                    model=request.model if request.model else interrupt_state['model'],
                    tools=tools,
                    mode=interrupt_state['mode']
                )
                
                messages.append(assistant_msg)

                if finish_reason == 'stop':
                    await cleanup_interrupt_state(request.interrupt_id)
                    return ChatResponse(
                        content=assistant_msg.get('content', ''),
                        active_servers=client.active_servers,
                        available_tools=list(client.available_tools.keys()),
                        finish_reason=finish_reason
                    )
                
                if finish_reason == "tool_calls" and assistant_msg.get('tool_calls'):
                    tools_changed = False

                    for tc in assistant_msg['tool_calls']:
                        tool_name = tc['function']['name']
                        tool_args = json.loads(tc['function']['arguments'])
                        
                        if tool_name in tool_change_triggers:
                            tools_changed = True
                        
                        logger.info(f"Calling tool: {tool_name}")

                        try:
                            if tool_name == "mcp-find":
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)
                                
                                # Parse MCP text response
                                if isinstance(result, dict) and "content" in result:
                                    text = client._parse_response(result["content"])
                                    try:
                                        payload = json.loads(text)
                                    except json.JSONDecodeError:
                                        payload = {}
                                else:
                                    payload = {}

                                servers = payload.get("servers", [])

                                for server_info in servers:
                                    if isinstance(server_info, dict) and "name" in server_info:
                                        mcp_find_cache[server_info["name"]] = server_info

                            elif tool_name == "mcp-add":
                                logger.info(f"[tool name]: {tool_name}\n[tool args]: {tool_args}\n")

                                # Get cached find result for this server
                                server_name_new = tool_args.get('name', '').strip()
                                cached_find = mcp_find_cache.get(server_name_new)
                                mcp_find_result = [cached_find] if cached_find else None
                                
                                # Call add_server_llm
                                add_result = await client.add_server_llm(
                                    server_name=server_name_new,
                                    activate=tool_args.get('activate', True),
                                    mcp_find_result=mcp_find_result
                                )
                                
                                # Check for another interrupt
                                if add_result.status == "secrets_required":
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc["id"],
                                        "name": "mcp-add",
                                        "content": json.dumps({
                                            "status": "secrets_required",
                                            "required_secrets": add_result.required_secrets or [],
                                        })
                                    })
                                    await cleanup_interrupt_state(request.interrupt_id)
                                    return SecretsRequiredResponse(
                                        interrupt_type="secrets_required",
                                        server=add_result.server,
                                        required_secrets=add_result.required_secrets or [],
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools.keys()),
                                        message=(
                                            f"Cannot add server '{add_result.server}' - "
                                            f"missing required secrets: {', '.join(add_result.required_secrets or [])}. "
                                            f"Please configure these secrets in your environment/settings "
                                            f"and start a new conversation."
                                        ),
                                        instructions=add_result.instructions
                                    )
                                
                                elif add_result.status == "config_required":
                                    # Another config interrupt - create new interrupt state
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc["id"],
                                        "name": "mcp-add",
                                        "content": json.dumps({
                                            "status": "config_required",
                                            "required_configs": add_result.required_configs or [],
                                        })
                                    })
                                    await cleanup_interrupt_state(request.interrupt_id)
                                    new_interrupt_id = generate_interrupt_id()
                                    
                                    await store_interrupt_state(
                                        interrupt_id=new_interrupt_id,
                                        messages=messages,
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools.keys()),
                                        pending_tool_call=tc,
                                        server_name=add_result.server,
                                        required_configs=add_result.required_configs or [],
                                        mode=interrupt_state['mode'],
                                        model=request.model if request.mode else interrupt_state['model'],
                                        provider=request.provider if request.provider else interrupt_state['provider'],
                                        max_iterations=interrupt_state['max_iterations'],
                                        current_iteration=interrupt_state['current_iteration'] + iteration + 1,
                                        mcp_find_cache=mcp_find_cache
                                    )
                                    
                                    return ConfigInterruptResponse(
                                        interrupt_type="config_required",
                                        server=add_result.server,
                                        required_configs=add_result.required_configs or [],
                                        conversation_state=messages,
                                        active_servers=client.active_servers,
                                        available_tools=list(client.available_tools.keys()),
                                        interrupt_id=new_interrupt_id,
                                        instructions=add_result.instructions
                                    )
                                
                                elif add_result.status == "added":
                                    # Success
                                    result_text = json.dumps({
                                        "status": "success",
                                        "message": add_result.message or "Server added successfully"
                                    })
                                
                                else:  # "failed"
                                    result_text = json.dumps({
                                        "status": "failed",
                                        "message": add_result.message or "Failed to add server"
                                    })

                            elif tool_name in ['code-mode', 'mcp-exec']:
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)
                                result_text = json.dumps(result)

                            else:
                                logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                result = await client.call_tool(tool_name, tool_args)

                                if isinstance(result, dict) and 'content' in result:
                                    result_text = client._parse_response(result['content'])
                                else:
                                    result_text = json.dumps(result)

                        except Exception as e:
                            result_text = f"Error: {str(e)}"
                            logger.error(f"Tool call error: {str(e)}")

                        messages.append({
                            "tool_call_id": tc['id'],
                            "role": "tool",
                            "name": tool_name,
                            "content": result_text
                        })

                    if tools_changed:
                        tools = await client.list_tools()
                        logger.info(f"Tools refreshed, now have {len(tools)} tools")

                    continue

                logger.warning(f"Unexpected finish reason: {finish_reason}")
                break

            # Max iterations reached in resume
            await cleanup_interrupt_state(request.interrupt_id)
            return ChatResponse(
                content="Max iterations reached during resume",
                active_servers=client.active_servers,
                available_tools=list(client.available_tools.keys()),
                finish_reason="max_iteration"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/sse/chat", tags=['chat'])
async def chat_stream(request: ChatRequest):
    """
    Streaming chat endpoint using Server-Sent Events (SSE)
    
    Streams events as they happen:
    - `status`: Connection status
    - `iteration`: Current iteration number
    - `content`: Assistant message content
    - `tool_call`: Tool being called
    - `tool_result`: Tool execution result
    - `config_required`: Configuration interrupt (requires /sse/chat/resume)
    - `secrets_required`: Secrets missing (terminal error)
    - `done`: Conversation complete
    - `error`: Error occurred
    """
    async def event_generator():
        try:
            async with MCPGatewayAPIClient() as client:
                for server in request.inital_servers:
                    logger.info(f"Adding initial server: {server}")
                    await client.add_server(server)

                yield f"data: {json.dumps({'type': 'status', 'message': 'Connected to MCP'})}\n\n"

                provider = LLMProviderFactory.get_provider(request.provider)
                tools = await client.list_tools()

                # Getting and appending system messages
                messages = [
                    {
                        "role": m.role,
                        "content": m.content
                    }
                    for m in request.messages
                ]
                sys_msg = None
                sys_msg_index = -1
                for i, m in enumerate(messages):
                    if m.get('role') == "system":
                        sys_msg = m
                        sys_msg_index = i
                        break

                if sys_msg:
                    new_sys_msg = sys_msg['content'].rstrip() + "\n\n--- Your Additional Instructions for MCP Bridge Client ---\n\n"+ MCP_BRIDGE_MESSAGES.get(request.mode)
                    messages[sys_msg_index]['content'] = new_sys_msg

                else:
                    messages.insert(0, {
                        "role": "system",
                        "content": MCP_BRIDGE_MESSAGES.get(request.mode)
                    })

                mcp_find_cache: Dict[str, Dict[str, Any]] = {}
                tool_change_triggers = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

                for iteration in range(request.max_iterations):
                    yield f"data: {json.dumps({'type': 'iteration', 'number': iteration+1})}\n\n"

                    # Using streaming generation
                    assistant_msg = {"role": "assistant", "content": None}
                    finish_reason = None

                    async for chunk in provider.generate_stream(
                        messages=messages,
                        model = request.model,
                        tools=tools,
                        mode = request.mode
                    ):
                        if chunk['type'] == "content_delta":
                            # Stream the response
                            yield f"data: {json.dumps({"type": 'content', 'data': chunk['content']})}\n\n"

                        elif chunk['type'] == "complete":
                            # Final complete message
                            assistant_msg = chunk["message"]
                            finish_reason = chunk["finish_reason"]

                    messages.append(assistant_msg)

                    if finish_reason == 'stop':
                        yield f"data: {json.dumps({'type': 'done', 'finish_reason': finish_reason})}\n\n"
                        break

                    # Handle tool calls
                    if finish_reason == 'tool_calls' and assistant_msg.get('tool_calls'):
                        tools_changed = False

                        for tc in assistant_msg['tool_calls']:
                            tool_name = tc['function']['name']
                            tool_args = json.loads(tc['function']['arguments'])

                            if tool_name in tool_change_triggers:
                                tools_changed = True

                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'args': tool_args})}\n\n"
                            
                            try:
                                if tool_name == 'mcp-find':
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)
                                    result_text = json.dumps(result)

                                    # Parse MCP text response
                                    if isinstance(result, dict) and "content" in result:
                                        text = client._parse_response(result["content"])
                                        try:
                                            payload = json.loads(text)
                                        except json.JSONDecodeError:
                                            payload = {}
                                    else:
                                        payload = {}

                                    servers = payload.get("servers", [])
                                    for server_info in servers:
                                        if isinstance(server_info, dict) and "name" in server_info:
                                            mcp_find_cache[server_info["name"]] = server_info

                                elif tool_name == "mcp-add":
                                    logger.info(f"[tool name]: {tool_name}\n[tool args]: {tool_args}\n")

                                    # Get cached find result for this server
                                    server_name = tool_args.get('name', '').strip()
                                    cached_find = mcp_find_cache.get(server_name)
                                    mcp_find_result = [cached_find] if cached_find else None
                                    
                                    # add_server_llm call
                                    add_result = await client.add_server_llm(
                                        server_name=server_name,
                                        activate=tool_args.get('activate', True),
                                        mcp_find_result=mcp_find_result
                                    )

                                    # check status
                                    if add_result.status == "secrets_required":
                                        # HARD STOP - Stream Error
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tc["id"],
                                            "name": "mcp-add",
                                            "content": json.dumps({
                                                "status": "secrets_required",
                                                "required_secrets": add_result.required_secrets or [],
                                            })
                                        })
                                        yield f"data: {json.dumps({'type': 'secrets_required', 'server': add_result.server, 'required_secrets': add_result.required_secrets or [], 'message': f"Cannot add server '{add_result.server}' - missing required secrets: {', '.join(add_result.required_secrets or [])}. Please configure these secrets in your environment settings and start a new conversation.", 'instructions': add_result.instructions})}\n\n"
                                        return
                                    
                                    elif add_result.status == "config_required":
                                        # INTERRUPT - store the state and return interrupt event
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tc["id"],
                                            "name": "mcp-add",
                                            "content": json.dumps({
                                                "status": "config_required",
                                                "required_configs": add_result.required_configs or [],
                                            })
                                        })
                                        interrupt_id = generate_interrupt_id()
                                        await store_interrupt_state(
                                            interrupt_id=interrupt_id,
                                            messages=messages,
                                            active_servers=client.active_servers,
                                            available_tools=list(client.available_tools.keys()),
                                            pending_tool_call=tc,
                                            server_name=add_result.server,
                                            required_configs=add_result.required_configs or [],
                                            mode=request.mode,
                                            model=request.model,
                                            provider=request.provider,
                                            max_iterations=request.max_iterations,
                                            current_iteration=iteration,
                                            mcp_find_cache=mcp_find_cache
                                        )
                                        yield f"data: {json.dumps({'type': 'config_required', 'interrupt_id': interrupt_id, 'server': add_result.server, 'required_configs': add_result.required_configs or [], 'active_servers': client.active_servers, 'available_tools': list(client.available_tools.keys()), 'instructions': add_result.instructions})}\n\n"
                                        return
                                    
                                    elif add_result.status == "added":
                                        # Success
                                        result_text = json.dumps({
                                            "status": "success",
                                            "message": add_result.message or "Server added successfully"
                                        })
                                    
                                    else:  # "failed"
                                        result_text = json.dumps({
                                            "status": "failed",
                                            "message": add_result.message or "Failed to add server"
                                        })

                                elif tool_name in ['code-mode', 'mcp-exec']:
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)
                                    result_text = json.dumps(result)

                                else:
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)

                                    if isinstance(result, dict) and 'content' in result:
                                        result_text = client._parse_response(result['content'])
                                    else:
                                        result_text = json.dumps(result)

                                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'result': result_text[:500]})}\n\n"
                            
                            except Exception as e:
                                result_text = f"Error: {str(e)}"
                                logger.error(f"Tool call error: {str(e)}")
                                yield f"data: {json.dumps({'type': 'tool_error', 'tool': tool_name, 'error': result_text})}\n\n"
                            
                            messages.append({
                                "tool_call_id": tc['id'],
                                "role": "tool",
                                "name": tool_name,
                                "content": result_text
                            })

                        if tools_changed:
                            tools = await client.list_tools()
                            logger.info(f"Tools refreshed, now have {len(tools)} tools")

                        continue

                    logger.warning(f"Unexpected finish reason: {finish_reason}")
                    break

                yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'max_iteration'})}\n\n"
            
        except Exception as e:
            logger.error(f"Stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/sse/chat/resume", tags=['chat'])
async def chat_stream_resume(request: ChatResumeRequest):
    """
    Resume streaming chat after config interrupt
    
    Continues streaming from where the previous SSE connection left off.
    
    Example:
    ```json
    {
        "interrupt_id": "abc-123",
        "provided_configs": {
            "github_token": "ghp_..."
        }
    }
    ```
    """
    async def event_generator():
        try:
            # 1. Retrieve the interrupt state
            interrupt_state = await get_interrupt_state(request.interrupt_id)
            logger.info("Restored interrupt state...")

            if not interrupt_state:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Interrupt {request.interrupt_id} not found or expired'})}\n\n"
                return
            
            # 2. Validate the provided configs
            if request.provided_configs:
                required_keys = {cfg['key'] for cfg in interrupt_state['required_configs']}
                provided_keys = set(request.provided_configs.keys())

                if required_keys != provided_keys:
                    missing = required_keys - provided_keys
                    extra = provided_keys - required_keys
                    error_msg = []
                    if missing:
                        error_msg.append(f"Missing configs: {', '.join(missing)}")

                    if extra:
                        error_msg.append(f"Unexpected configs: {', '.join(extra)}")
                    yield f"data: {json.dumps({'type': 'error', 'message': '; '.join(error_msg)})}\n\n"
                    return
            
            yield f"data: {json.dumps({'type': 'status', 'message': 'Resuming conversation...'})}\n\n"
            
            # 3. Rebuild client state
            async with MCPGatewayAPIClient() as client:
                for server in interrupt_state['active_servers']:
                    try:
                        await client.add_server(server)
                    except Exception as e:
                        logger.warning(f"failed to restore server {server}: {str(e)}")

                server_name = interrupt_state['server_name']
                pending_tc = interrupt_state['pending_tool_call']

                if request.provided_configs:
                    logger.info(f"Retrying mcp-add for {server_name} with configs: {list(request.provided_configs.keys())}")

                    add_result = await client.add_server(server_name=server_name, activate=True, config=request.provided_configs)

                    if isinstance(add_result, dict) and 'content' in add_result:
                        result_text = client._parse_response(add_result["content"])
                    else:
                        result_text = str(add_result)
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool': 'mcp-add', 'result': result_text[:500]})}\n\n"

                    messages = interrupt_state['messages'].copy()
                    # Needed to add the previous tool calls and then append the result_text
                    # Replay assistant tool call
                    messages.append({
                        "role": "assistant",
                        "tool_calls": [pending_tc],
                        "content": None
                    })

                    # Tool response
                    messages.append({
                        "role": "tool",
                        "tool_call_id": pending_tc["id"],
                        "name": "mcp-add",
                        "content": result_text
                    })
                else:
                    messages = interrupt_state['messages'].copy()

                tools = await client.list_tools()
                logger.info(f"Tools refreshed after resume, now have {len(tools)} tools")

                provider = LLMProviderFactory.get_provider(request.provider if request.provider else interrupt_state['provider'])
                mcp_find_cache = interrupt_state.get('mcp_find_cache', {})
                remaining_iterations = interrupt_state['max_iterations'] - interrupt_state['current_iteration'] - 1
                tool_change_triggers = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

                for iteration in range(remaining_iterations):
                    yield f"data: {json.dumps({'type': 'iteration', 'number': interrupt_state['current_iteration'] + iteration + 2})}\n\n"
                    
                    # Use streaming generation
                    assistant_msg = {"role": "assistant", "content": None}
                    finish_reason = None
                    
                    async for chunk in provider.generate_stream(
                        messages=messages,
                        model=request.model if request.model else interrupt_state['model'],
                        tools=tools,
                        mode=interrupt_state['mode']
                    ):
                        if chunk["type"] == "content_delta":
                            # Stream the response
                            yield f"data: {json.dumps({'type': 'content', 'data': chunk['content']})}\n\n"
                        
                        elif chunk["type"] == "complete":
                            # Final complete message
                            assistant_msg = chunk["message"]
                            finish_reason = chunk["finish_reason"]
                    
                    messages.append(assistant_msg)

                    if finish_reason == "stop":
                        await cleanup_interrupt_state(request.interrupt_id)
                        yield f"data: {json.dumps({'type': 'done', 'finish_reason': finish_reason})}\n\n"
                        return
                    
                    if finish_reason == "tool_calls" and assistant_msg.get("tool_calls"):
                        tools_changed = False
                        
                        for tc in assistant_msg['tool_calls']:
                            tool_name = tc['function']['name']
                            tool_args = json.loads(tc['function']['arguments'])

                            if tool_name in tool_change_triggers:
                                tools_changed = True

                            yield f"data: {json.dumps({'type': 'tool_call', 'tool': tool_name, 'args': tool_args})}\n\n"

                            try:
                                if tool_name == "mcp-find":
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)
                                    result_text = json.dumps(result)
                                    
                                    # Parse MCP text response
                                    if isinstance(result, dict) and "content" in result:
                                        text = client._parse_response(result["content"])
                                        try:
                                            payload = json.loads(text)
                                        except json.JSONDecodeError:
                                            payload = {}
                                    else:
                                        payload = {}

                                    servers = payload.get("servers", [])
                                    for server_info in servers:
                                        if isinstance(server_info, dict) and "name" in server_info:
                                            mcp_find_cache[server_info["name"]] = server_info

                                elif tool_name == "mcp-add":
                                    logger.info(f"[tool name]: {tool_name}\n[tool args]: {tool_args}\n")

                                    # Get cached find result for this server
                                    server_name_new = tool_args.get('name', '').strip()
                                    cached_find = mcp_find_cache.get(server_name_new)
                                    mcp_find_result = [cached_find] if cached_find else None

                                    # Call add_server_llm
                                    add_result = await client.add_server_llm(
                                        server_name=server_name_new,
                                        activate=tool_args.get('activate', True),
                                        mcp_find_result=mcp_find_result
                                    )

                                    # Check for nested interruptions
                                    if add_result.status == "secrets_required":
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tc["id"],
                                            "name": "mcp-add",
                                            "content": json.dumps({
                                                "status": "secrets_required",
                                                "required_secrets": add_result.required_secrets or [],
                                            })
                                        })
                                        await cleanup_interrupt_state(request.interrupt_id)
                                        yield f"data: {json.dumps({'type': 'secrets_required', 'server': add_result.server, 'required_secrets': add_result.required_secrets or [], 'message': f"Cannot add server '{add_result.server}' - missing required secrets: {', '.join(add_result.required_secrets or [])}. Please configure these secrets in your environment settings and start a new conversation.", 'instructions': add_result.instructions})}\n\n"
                                        return
                                    
                                    elif add_result.status == "config_required":
                                        # Another config interrupt - create new interrupt state
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tc["id"],
                                            "name": "mcp-add",
                                            "content": json.dumps({
                                                "status": "config_required",
                                                "required_configs": add_result.required_configs or [],
                                            })
                                        })
                                        await cleanup_interrupt_state(request.interrupt_id)
                                        new_interrupt_id = generate_interrupt_id()

                                        await store_interrupt_state(
                                            interrupt_id=new_interrupt_id,
                                            messages=messages,
                                            active_servers=client.active_servers,
                                            available_tools=list(client.available_tools.keys()),
                                            pending_tool_call=tc,
                                            server_name=add_result.server,
                                            required_configs=add_result.required_configs or [],
                                            mode=interrupt_state['mode'],
                                            model=request.model if request.model else interrupt_state['model'],
                                            provider=request.provider if request.provider else interrupt_state['provider'],
                                            max_iterations=interrupt_state['max_iterations'],
                                            current_iteration=interrupt_state['current_iteration'] + iteration + 1,
                                            mcp_find_cache=mcp_find_cache
                                        )

                                        yield f"data: {json.dumps({'type': 'config_required', 'interrupt_id': new_interrupt_id, 'server': add_result.server, 'required_configs': add_result.required_configs or [], 'active_servers': client.active_servers, 'available_tools': list(client.available_tools.keys()), 'instructions': add_result.instructions})}\n\n"
                                        return
                                    
                                    elif add_result.status == "added":
                                        # Success
                                        result_text = json.dumps({
                                            "status": "success",
                                            "message": add_result.message or "Server added successfully"
                                        })
                                    
                                    else:  # "failed"
                                        result_text = json.dumps({
                                            "status": "failed",
                                            "message": add_result.message or "Failed to add server"
                                        })

                                elif tool_name in ['code-mode', 'mcp-exec']:
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)
                                    result_text = json.dumps(result)

                                else:
                                    logger.info(f"[tool name]: {tool_name}\n [tool args]: {tool_args}\n")
                                    result = await client.call_tool(tool_name, tool_args)
                                    
                                    if isinstance(result, dict) and 'content' in result:
                                        result_text = client._parse_response(result['content'])
                                    else:
                                        result_text = json.dumps(result)

                                yield f"data: {json.dumps({'type': 'tool_result', 'tool': tool_name, 'result': result_text[:500]})}\n\n"

                            except Exception as e:
                                result_text = f"Error: {str(e)}"
                                logger.error(f"Tool call error: {str(e)}")
                                yield f"data: {json.dumps({'type': 'tool_error', 'tool': tool_name, 'error': result_text})}\n\n"

                            messages.append({
                                "tool_call_id": tc['id'],
                                "role": "tool",
                                "name": tool_name,
                                "content": result_text
                            })

                        if tools_changed:
                            tools = await client.list_tools()
                            logger.info(f"Tools refreshed, now have {len(tools)} tools")

                        continue

                    logger.warning(f"Unexpected finish reason: {finish_reason}")
                    break

                # Max iterations reached in resume
                await cleanup_interrupt_state(request.interrupt_id)
                yield f"data: {json.dumps({'type': 'done', 'finish_reason': 'max_iteration'})}\n\n"
        
        except Exception as e:
            logger.error(f"Resume stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
                        


@app.post("/mcp/find", tags=["mcp"])
async def find_mcp_server(request: MCPFindRequest):
    """
    Discover available MCP servers using `mcp-find`.

    Example:
    ```json
    {
        "query": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            result = await client.call_tool(
                "mcp-find",
                {"query": request.query}
            )

            return {
                "status": "success",
                "query": request.query,
                "servers": result
            }

    except Exception as e:
        logger.error(f"Find MCP server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mcp/add", tags=['mcp'])
async def add_mcp_server(config: MCPServerConfig = Body(..., media_type="application/json")):
    """
    Add an MCP server
    
    **Security Note**: Secrets cannot be set via API. Configure them externally:
    - Docker CLI: `docker mcp secret set server/key`
    - Environment variables
    - Secret manager (AWS Secrets Manager, Vault, etc.)
    
    Example:
    ```json
    {
        "name": "github",
        "activate": true,
        "config": {
            "api_version": "v3"
        }
    }
    ```
    """

    if config.secrets:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Secrets cannot be set via API for security reasons",
                "instructions": [
                    f"Run: docker mcp secret set {config.name}=<secret>",
                    "Or configure via environment variables / secrets manager"
                ]
            }
        )
    
    try:
        async with MCPGatewayAPIClient() as client:
            if config.config:
                for key, value in config.config.items():
                    await client.call_tool("mcp-config-set", {
                        "server": config.name,
                        "key": key,
                        "value": value
                    })

                logger.info(f"Set {len(config.config)} configs for {config.name}")

            result = await client.add_server(
                server_name = config.name,
                activate=config.activate
            )

            return {
                "status": "success",
                "server": config.name,
                "active_servers": client.active_servers,
                "message": "Server added. Ensure secrets are configured externally.",
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Add server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/mcp/remove", tags=["mcp"])
async def remove_mcp_server(request: MCPRemoveRequest):
    """
    Remove an MCP server
    
    Example:
    ```json
    {
        "name": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            result = await client.remove_server(request.name)

            return {
                "status": "success",
                "server": request.name,
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Remove server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/mcp/servers", tags=["mcp"])
async def list_servers():
    """
    List currently active MCP servers and available tools
    """
    try:
        async with MCPGatewayAPIClient() as client:
            return {
                "active_servers": client.active_servers,
                "available_tools": list(client.available_tools.keys()),
                "tool_count": len(client.available_tools)
            }
    
    except Exception as e:
        logger.error(f"List servers error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))