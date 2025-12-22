from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from logger import logger
import json
from core import AgentCore
from models import (
    ChatRequest, 
    ChatResponse, 
    ChatResumeRequest,
    MCPRemoveRequest,
    MCPServerConfig,
    MCPFindRequest,
    SecretsRequiredResponse, 
    ConfigInterruptResponse, 
    ChatResponseUnion
)
from gateway_client import MCPGatewayAPIClient
from provider import LLMProviderFactory
from services.state_manager import (
    generate_interrupt_id, 
    store_interrupt_state,
    get_interrupt_state, 
    cleanup_interrupt_state
)

router = APIRouter()

@router.post("/chat", response_model=ChatResponseUnion, tags=['chat'])
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
                logger.info(f"Adding inital server: {server}")
                await client.add_server(server)

            provider = LLMProviderFactory.get_provider(request.provider)
            agent = AgentCore(client=client, provider=provider, mode=request.mode)

            messages = await agent.prepare_messages(
                [{"role": m.role, "content": m.content} for m in request.messages],
                request.mode
            )

            # run agent loop
            result = await agent.run_agent_loop(
                messages=messages,
                model=request.model,
                max_iterations=request.max_iterations
            )

            # handle interrupts
            if result.interrupt_type == "secrets_required":
                return SecretsRequiredResponse(
                    interrupt_type="secrets_required",
                    server=result.server,
                    required_secrets=result.required_secrets,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    message=(
                        f"Cannot add server '{result.server}' - "
                        f"missing required secrets: {', '.join(result.required_secrets or [])}. "
                        f"Please configure these secrets in your environment/settings "
                        f"and start a new conversation."
                    ),
                    instructions=result.instructions
                )
            
            elif result.interrupt_type == "config_required":
                interrupt_id = generate_interrupt_id()
                await store_interrupt_state(
                    interrupt_id=interrupt_id,
                    messages=result.messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    pending_tool_call=None, #added in messages
                    server_name=result.server,
                    required_configs=result.required_configs or [],
                    mode=request.mode,
                    model=request.model,
                    provider=request.provider,
                    max_iterations=request.max_iterations,
                    current_iteration=len([m for m in result.messages if m.get("role") == "assistant"]),
                    mcp_find_cache=agent.mcp_find_cache
                )

                return ConfigInterruptResponse(
                    interrupt_type="config_required",
                    server=result.server,
                    required_configs=result.required_configs or [],
                    conversation_state=result.messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    interrupt_id=interrupt_id,
                    instructions=result.instructions
                )
            
            # Normal response
            return ChatResponse(
                content=result.content,
                active_servers=client.active_servers,
                available_tools=list(client.available_tools.keys()),
                finish_reason=result.finish_reason
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/chat/resume", response_model=ChatResponseUnion, tags=['chat'])
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
        interrupt_state = await get_interrupt_state(request.interrupt_id)
        if not interrupt_state:
            raise HTTPException(
                status_code=404, 
                detail=f"Interrupt {request.interrupt_id} not found or expired"
            )
        
        if request.provided_configs:
            required_keys = {cfg['key'] for cfg in interrupt_state['required_configs']}
            provided_keys = set(request.provided_configs.keys())

            if request.provided_configs:
                required = {c["key"] for c in interrupt_state["required_configs"]}
                provided = set(request.provided_configs.keys())
                if required != provided:
                    raise HTTPException(status_code=400, detail="Config Mismatch")
            
        async with MCPGatewayAPIClient() as client:
            for server in interrupt_state['active_servers']:
                try:
                    await client.add_server(server)
                except Exception as e:
                    logger.warning(f"Failed to restore server {server}: {e}")

            messages = interrupt_state['messages'].copy()
            if request.provided_configs:
                server_name = interrupt_state["server_name"]
                logger.info(f"Retrying mcp-add for {server_name}")

                add_result = await client.add_server(
                    server_name=server_name,
                    activate=True,
                    config=request.provided_configs
                )

                if isinstance(add_result, dict) and "content" in add_result:
                    result_text = client._parse_response(add_result["content"])
                else:
                    result_text = str(add_result)

                pending_tc = interrupt_state.get("pending_tool_call")

                if pending_tc:
                    tool_call = pending_tc
                else:
                    # Need to synthesize tool calls for runtime interrupts
                    tool_call = {
                        "id": "resume-mcp-add",
                        "type": "function",
                        "function": {
                            "name": "mcp-add",
                            "arguments": json.dumps({
                                "name": server_name,
                                "activate": True,
                                **request.provided_configs
                            })
                        }
                    }

                    messages.append({
                        "role": "assistant",
                        "tool_calls": [tool_call],
                        "content": None
                    })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": "mcp-add",
                    "content": result_text
                })
            
            provider = LLMProviderFactory.get_provider(
                request.provider if request.provider else interrupt_state['provider']
            )
            agent = AgentCore(client, provider, interrupt_state['mode'])
            agent.mcp_find_cache = interrupt_state.get('mcp_find_cache', {})
            
            result = await agent.run_agent_loop(
                messages=messages,
                model=request.model or interrupt_state["model"],
                max_iterations=interrupt_state["max_iterations"],
                current_iteration=interrupt_state["current_iteration"]
            )

            await cleanup_interrupt_state(request.interrupt_id)

            if result.interrupt_type == "secrets_required":
                return SecretsRequiredResponse(
                    interrupt_type="secrets_required",
                    server=result.server,
                    required_secrets=result.required_secrets,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    message=(
                        f"Cannot add server '{result.server}' - "
                        f"missing required secrets: {', '.join(result.required_secrets or [])}. "
                        f"Please configure these secrets in your environment/settings "
                        f"and start a new conversation."
                    ),
                    instructions=result.instructions
                )
            
            elif result.interrupt_type == "config_required":
                new_interrupt_id = generate_interrupt_id()
                await store_interrupt_state(
                    interrupt_id=new_interrupt_id,
                    messages=result.messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    pending_tool_call=None,
                    server_name=result.server,
                    required_configs=result.required_configs or [],
                    mode=interrupt_state['mode'],
                    model=request.model if request.model else interrupt_state['model'],
                    provider=request.provider if request.provider else interrupt_state['provider'],
                    max_iterations=interrupt_state['max_iterations'],
                    current_iteration=len([m for m in result.messages if m.get("role") == "assistant"]),
                    mcp_find_cache=agent.mcp_find_cache
                )
                
                return ConfigInterruptResponse(
                    interrupt_type="config_required",
                    server=result.server,
                    required_configs=result.required_configs or [],
                    conversation_state=result.messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    interrupt_id=new_interrupt_id,
                    instructions=result.instructions
                )
            
            return ChatResponse(
                content=result.content,
                active_servers=client.active_servers,
                available_tools=list(client.available_tools.keys()),
                finish_reason=result.finish_reason
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/sse/chat", tags=['chat'])
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
        interrupt_id = None
        try:
            async with MCPGatewayAPIClient() as client:
                for server in request.inital_servers:
                    logger.info(f"Adding initial server: {server}")
                    await client.add_server(server)
                
                yield f"data: {json.dumps({'type': 'status', 'message': 'Connected to MCP'})}\n\n"
                
                provider = LLMProviderFactory.get_provider(request.provider)
                agent = AgentCore(client, provider, request.mode)

                messages = await agent.prepare_messages(
                    [{"role": m.role, "content": m.content} for m in request.messages],
                    request.mode
                )

                async for event in agent.run_agent_loop_stream(
                    messages=messages,
                    model=request.model,
                    max_iterations=request.max_iterations
                ):
                   # Handle interrupts
                    if event['type'] == 'config_required':
                        interrupt_id = generate_interrupt_id()
                        await store_interrupt_state(
                            interrupt_id=interrupt_id,
                            messages=messages,
                            active_servers=client.active_servers,
                            available_tools=list(client.available_tools.keys()),
                            pending_tool_call=None,
                            server_name=event['server'],
                            required_configs=event.get('required_configs', []),
                            mode=request.mode,
                            model=request.model,
                            provider=request.provider,
                            max_iterations=request.max_iterations,
                            current_iteration=len([m for m in messages if m.get("role") == "assistant"]),
                            mcp_find_cache=agent.mcp_find_cache
                        )
                        event['interrupt_id'] = interrupt_id
                        event['active_servers'] = client.active_servers
                        event['available_tools'] = list(client.available_tools.keys())
                    
                    elif event['type'] == 'secrets_required':
                        event['message'] = (
                            f"Cannot add server '{event['server']}' - "
                            f"missing required secrets: {', '.join(event.get('required_secrets', []))}. "
                            f"Please configure these secrets in your environment settings "
                            f"and start a new conversation."
                        )
                    
                    yield f"data: {json.dumps(event)}\n\n"
        
        except Exception as e:
            logger.error(f"Stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/sse/chat/resume", tags=['chat'])
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
            # Retrieve interrupt state
            interrupt_state = await get_interrupt_state(request.interrupt_id)
            if not interrupt_state:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Interrupt {request.interrupt_id} not found or expired'})}\n\n"
                return
            
            if request.provided_configs:
                required = {c["key"] for c in interrupt_state["required_configs"]}
                provided = set(request.provided_configs.keys())
                if required != provided:
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Config mismatch'})}\n\n"
                    return
                
            yield f"data: {json.dumps({'type': 'status', 'message': 'Resuming conversation...'})}\n\n"
            
            async with MCPGatewayAPIClient() as client:
                for server in interrupt_state['active_servers']:
                    try:
                        await client.add_server(server)
                    except Exception as e:
                        logger.warning(f"Failed to restore server {server}: {e}")
                
                messages = interrupt_state['messages'].copy()
                if request.provided_configs:
                    server_name = interrupt_state["server_name"]
                    logger.info(f"Retrying mcp-add for {server_name}")

                    add_result = await client.add_server(
                        server_name=server_name,
                        activate=True,
                        config=request.provided_configs
                    )

                    if isinstance(add_result, dict) and "content" in add_result:
                        result_text = client._parse_response(add_result["content"])
                    else:
                        result_text = str(add_result)

                    pending_tc = interrupt_state.get("pending_tool_call")

                    if pending_tc:
                        tool_call = pending_tc
                    else:
                        # Need to synthesize tool calls for runtime interrupts
                        tool_call = {
                            "id": "resume-mcp-add",
                            "type": "function",
                            "function": {
                                "name": "mcp-add",
                                "arguments": json.dumps({
                                    "name": server_name,
                                    "activate": True,
                                    **request.provided_configs
                                })
                            }
                        }

                        messages.append({
                            "role": "assistant",
                            "tool_calls": [tool_call],
                            "content": None
                        })

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "name": "mcp-add",
                        "content": result_text
                    })

                provider = LLMProviderFactory.get_provider(
                    request.provider if request.provider else interrupt_state['provider']
                )
                agent = AgentCore(client, provider, interrupt_state['mode'])
                agent.mcp_find_cache = interrupt_state.get('mcp_find_cache', {})
                
                async for event in agent.run_agent_loop_stream(
                    messages=messages,
                    model=request.model or interrupt_state["model"],
                    max_iterations=interrupt_state["max_iterations"],
                    current_iteration=interrupt_state["current_iteration"],
                ):
                    # Handle new interrupts
                    if event['type'] == 'config_required':
                        await cleanup_interrupt_state(request.interrupt_id)
                        new_interrupt_id = generate_interrupt_id()
                        await store_interrupt_state(
                            interrupt_id=new_interrupt_id,
                            messages=messages,
                            active_servers=client.active_servers,
                            available_tools=list(client.available_tools.keys()),
                            pending_tool_call=None,
                            server_name=event['server'],
                            required_configs=event.get('required_configs', []),
                            mode=interrupt_state['mode'],
                            model=request.model if request.model else interrupt_state['model'],
                            provider=request.provider if request.provider else interrupt_state['provider'],
                            max_iterations=interrupt_state['max_iterations'],
                            current_iteration=len([m for m in messages if m.get("role") == "assistant"]),
                            mcp_find_cache=agent.mcp_find_cache
                        )
                        event['interrupt_id'] = new_interrupt_id
                        event['active_servers'] = client.active_servers
                        event['available_tools'] = list(client.available_tools.keys())
                    
                    elif event['type'] == 'secrets_required':
                        await cleanup_interrupt_state(request.interrupt_id)
                        event['message'] = (
                            f"Cannot add server '{event['server']}' - "
                            f"missing required secrets: {', '.join(event.get('required_secrets', []))}. "
                            f"Please configure these secrets in your environment settings "
                            f"and start a new conversation."
                        )
                    
                    elif event['type'] == 'done':
                        await cleanup_interrupt_state(request.interrupt_id)
                    
                    yield f"data: {json.dumps(event)}\n\n"
        
        except Exception as e:
            logger.error(f"Resume stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/mcp/find", tags=["mcp"])
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

@router.post("/mcp/add", tags=['mcp'])
async def add_mcp_server(config: MCPServerConfig):
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
    
@router.post("/mcp/remove", tags=["mcp"])
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
    
@router.get("/mcp/servers", tags=["mcp"])
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