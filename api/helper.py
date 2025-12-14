from prompts import MCP_BRIDGE_MESSAGES
from models import SecretsRequiredResponse, ConfigInterruptResponse
from state_manager import generate_interrupt_id, store_interrupt_state
from logger import logger
import json

def inject_mcp_system_message(messages, mode: str):
    sys_msg_index = next((i for i, m in enumerate(messages) if m["role"] == "system"), None)

    if sys_msg_index is not None:
        messages[sys_msg_index]["content"] = (
            messages[sys_msg_index]["content"].rstrip()
            + "\n\n--- Your Additional Instructions for MCP Bridge Client ---\n\n"
            + MCP_BRIDGE_MESSAGES.get(mode)
        )
    else:
        messages.insert(0, {
            "role": "system",
            "content": MCP_BRIDGE_MESSAGES.get(mode)
        })

async def handle_tool_call(
    client,
    tc,
    messages,
    mcp_find_cache,
    request_ctx,
    iteration
):
    tool_name = tc["function"]["name"]
    tool_args = json.loads(tc["function"]["arguments"])
    tool_change_triggers = {"mcp-add", "mcp-find", "mcp-exec", "code-mode"}

    tools_changed = tool_name in tool_change_triggers
    result_text = ""

    try:
        if tool_name == "mcp-find":
            result = await client.call_tool(tool_name, tool_args)
            result_text = json.dumps(result)
            if isinstance(result, list):
                for s in result:
                    if isinstance(s, dict) and "name" in s:
                        mcp_find_cache[s["name"]] = s

        elif tool_name == "mcp-add":
            server_name = tool_args.get("name", "").strip()
            cached_find = mcp_find_cache.get(server_name)
            add_result = await client.add_server_llm(
                server_name=server_name,
                activate=tool_args.get("activate", True),
                mcp_find_result=[cached_find] if cached_find else None
            )

            if add_result.status == "secrets_required":
                raise SecretsRequiredResponse(
                    interrupt_type="secrets_required",
                    server=add_result.server,
                    required_secrets=add_result.required_secrets,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    message=f"Missing secrets for {add_result.server}",
                    instructions=add_result.instructions
                )
            
            if add_result.status == "config_required":
                interrupt_id = generate_interrupt_id()
                await store_interrupt_state(
                    interrupt_id=interrupt_id,
                    messages=messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    pending_tool_call=tc,
                    server_name=add_result.server,
                    required_configs=add_result.required_configs or [],
                    **request_ctx,
                    current_iteration=iteration,
                    mcp_find_cache=mcp_find_cache
                )

                raise ConfigInterruptResponse(
                    interrupt_type="config_required",
                    server=add_result.server,
                    required_configs=add_result.required_configs or [],
                    conversation_state=messages,
                    active_servers=client.active_servers,
                    available_tools=list(client.available_tools.keys()),
                    interrupt_id=interrupt_id,
                    instructions=add_result.instructions
                )
            
            result_text = json.dumps({
                "status": add_result.status,
                "message": add_result.message
            })

        else:
            result = await client.call_tool(tool_name, tool_args)
            if isinstance(result, dict) and "content" in result:
                result_text = client._parse_response(result["content"])
            else:
                result_text = json.dumps(result)

    except (SecretsRequiredResponse, ConfigInterruptResponse):
        raise
    except Exception as e:
        logger.error(f"Tool error: {e}")
        result_text = f"Error: {str(e)}"

    messages.append({
        "tool_call_id": tc["id"],
        "role": "tool",
        "name": tool_name,
        "content": result_text
    })

    return tools_changed

async def run_agent_loop(
    provider,
    client,
    messages,
    tools,
    request_ctx,
    start_iter=0,
    max_iter=5,
    mcp_find_cache=None
):
    mcp_find_cache = mcp_find_cache or {}

    for iteration in range(start_iter, max_iter):
        response, assistant_msg, finish_reason = await provider.generate(
            messages=messages,
            model=request_ctx["model"],
            tools=tools,
            mode=request_ctx["mode"]
        )

        messages.append(assistant_msg)

        if finish_reason == "stop":
            return assistant_msg, finish_reason
        
        if finish_reason == "tool_calls":
            tools_changed = False
            for tc in assistant_msg.get("tool_calls", []):
                tools_changed |= await handle_tool_call(
                    client,
                    tc,
                    messages,
                    mcp_find_cache,
                    request_ctx,
                    iteration
                )
            if tools_changed:
                tools = await client.list_tools()
            continue
        break
    return {"content": "Max iterations reached"}, "max_iteration"