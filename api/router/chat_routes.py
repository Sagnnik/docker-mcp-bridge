from fastapi import APIRouter, HTTPException, Header
from fastapi.responses import StreamingResponse
from utils.logger import logger
import json
import uuid
from typing import Optional
from core.core import AgentCore
from models import (
    ChatRequest, 
    ChatResponse, 
    ChatResumeRequest,
    SecretsRequiredResponse, 
    ConfigInterruptResponse, 
    ChatResponseUnion
)
from core.gateway_client import MCPGatewayAPIClient
from providers import LLMProviderFactory
from core.state_manager import (
    generate_interrupt_id, 
    store_interrupt_state,
    get_interrupt_state, 
    cleanup_interrupt_state,
    get_user_stats
)

router = APIRouter()

def get_user_id_from_header(x_user_id: Optional[str] = Header(default=None)) -> str:
    """
    Extract and validate user ID from header
    Or auto-provisions a new anonymous user.
    """
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()

    return f"anon-{uuid.uuid4().hex}"

@router.post("/chat", response_model=ChatResponseUnion, tags=['chat'])
async def chat(request: ChatRequest, x_user_id: Optional[str] = Header(default=None)):
    """
    Non-streaming chat endpoint with MCP tools
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/chat \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{
        "messages": [{"role": "user", "content": "What's the weather in SF?"}],
        "model": "gpt-5-mini",
        "provider": "openai",
        "mode": "dynamic",
        "initial_servers": ["weather"]
      }'
    ```
    """
    user_id = get_user_id_from_header(x_user_id)
    try:
        async with MCPGatewayAPIClient(user_id) as client:
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

            user_servers = await get_user_stats(user_id)

            # handle interrupts
            if result.interrupt_type == "secrets_required":
                return SecretsRequiredResponse(
                    interrupt_type="secrets_required",
                    server=result.server,
                    required_secrets=result.required_secrets,
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
                    message=(
                        f"Cannot add server '{result.server}' - "
                        f"missing required secrets: {', '.join([s.get('name', s) if isinstance(s, dict) else s for s in result.required_secrets or []])}. "
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
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
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
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
                    interrupt_id=interrupt_id,
                    instructions=result.instructions
                )
            
            # Normal response
            return ChatResponse(
                content=result.content,
                active_servers=user_servers["active_servers"],
                available_tools=user_servers["available_tools"],
                finish_reason=result.finish_reason
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[User: {user_id}] Chat error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/chat/resume", response_model=ChatResponseUnion, tags=['chat'])
async def chat_resume(request: ChatResumeRequest, x_user_id: Optional[str] = Header(default=None)):
    """
    Resume conversation after config interrupt
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/chat/resume \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{
        "interrupt_id": "abc-123",
        "provided_configs": {
          "github_token": "ghp_..."
        }
      }'
    ```
    """  
    user_id = get_user_id_from_header(x_user_id)
    try:
        interrupt_state = await get_interrupt_state(request.interrupt_id)
        if not interrupt_state:
            raise HTTPException(
                status_code=404, 
                detail=f"Interrupt {request.interrupt_id} not found or expired"
            )
        
        if request.provided_configs:
            required = {c["key"] for c in interrupt_state["required_configs"]}
            provided = set(request.provided_configs.keys())
            if required != provided:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Config mismatch. Required: {required}, Provided: {provided}"
                )
            
        async with MCPGatewayAPIClient(user_id) as client:
            for server in interrupt_state['active_servers']:
                try:
                    await client.add_server(server)
                except Exception as e:
                    logger.warning(f"[User: {user_id}] Failed to restore server {server}: {e}")

            messages = interrupt_state['messages'].copy()
            if request.provided_configs:
                server_name = interrupt_state["server_name"]
                logger.info(f"[User: {user_id}] Retrying mcp-add for {server_name}")

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

            user_servers = await get_user_stats(user_id)

            await cleanup_interrupt_state(request.interrupt_id)

            if result.interrupt_type == "secrets_required":
                return SecretsRequiredResponse(
                    interrupt_type="secrets_required",
                    server=result.server,
                    required_secrets=result.required_secrets,
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
                    message=(
                        f"Cannot add server '{result.server}' - "
                        f"missing required secrets: {', '.join([s.get('name', s) if isinstance(s, dict) else s for s in result.required_secrets or []])}. "
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
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
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
                    active_servers=user_servers["active_servers"],
                    available_tools=user_servers["available_tools"],
                    interrupt_id=new_interrupt_id,
                    instructions=result.instructions
                )
            
            return ChatResponse(
                content=result.content,
                active_servers=user_servers["active_servers"],
                available_tools=user_servers["available_tools"],
                finish_reason=result.finish_reason
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[User: {user_id}] Resume error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/sse/chat", tags=['chat'])
async def chat_stream(request: ChatRequest, x_user_id: Optional[str] = Header(default=None)):
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
    user_id = get_user_id_from_header(x_user_id)

    async def event_generator():
        interrupt_id = None
        try:
            async with MCPGatewayAPIClient(user_id) as client:
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
                        user_servers = await get_user_stats(user_id)
                        await store_interrupt_state(
                            interrupt_id=interrupt_id,
                            messages=messages,
                            active_servers=user_servers["active_servers"],
                            available_tools=user_servers["available_tools"],
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
                        event['active_servers'] = user_servers["active_servers"]
                        event['available_tools'] = user_servers["available_tools"]
                    
                    elif event['type'] == 'secrets_required':
                        event['message'] = (
                            f"Cannot add server '{event['server']}' - "
                            f"missing required secrets: {', '.join([s.get('name', s) if isinstance(s, dict) else s for s in event.get('required_secrets', [])])}. "
                            f"Please configure these secrets in your environment settings "
                            f"and start a new conversation."
                        )
                    
                    yield f"data: {json.dumps(event)}\n\n"
        
        except Exception as e:
            logger.error(f"[User: {user_id}] Stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/sse/chat/resume", tags=['chat'])
async def chat_stream_resume(request: ChatResumeRequest, x_user_id: Optional[str] = Header(default=None)):
    """
    Resume streaming chat after config interrupt
    
    Continues streaming from where the previous SSE connection left off.
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/sse/chat/resume \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{
        "interrupt_id": "abc-123",
        "provided_configs": {
          "github_token": "ghp_..."
        }
      }'
    """
    user_id = get_user_id_from_header(x_user_id)

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
            
            async with MCPGatewayAPIClient(user_id) as client:
                for server in interrupt_state['active_servers']:
                    try:
                        await client.add_server(server)
                    except Exception as e:
                        logger.warning(f"[User: {user_id}] Failed to restore server {server}: {e}")
                
                messages = interrupt_state['messages'].copy()
                if request.provided_configs:
                    server_name = interrupt_state["server_name"]
                    logger.info(f"[User: {user_id}] Retrying mcp-add for {server_name}")

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
                        user_servers = await get_user_stats(user_id)
                        
                        await store_interrupt_state(
                            interrupt_id=new_interrupt_id,
                            messages=messages,
                            active_servers=user_servers["active_servers"],
                            available_tools=user_servers["available_tools"],
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
                        event['active_servers'] = user_servers["active_servers"]
                        event['available_tools'] = user_servers["available_tools"]
                    
                    elif event['type'] == 'secrets_required':
                        await cleanup_interrupt_state(request.interrupt_id)
                        event['message'] = (
                            f"Cannot add server '{event['server']}' - "
                            f"missing required secrets: {', '.join([s.get('name', s) if isinstance(s, dict) else s for s in event.get('required_secrets', [])])}. "
                            f"Please configure these secrets in your environment settings "
                            f"and start a new conversation."
                        )
                    
                    elif event['type'] == 'done':
                        await cleanup_interrupt_state(request.interrupt_id)
                    
                    yield f"data: {json.dumps(event)}\n\n"
        
        except Exception as e:
            logger.error(f"[User: {user_id}] Resume stream error: {str(e)}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")