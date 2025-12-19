import questionary
import json
from mcp_host import MCPGatewayClient
from provider import LLMProviderFactory
from prompts import MCP_BRIDGE_MESSAGES
from helpers import handle_mcp_find
from configs_secrets import hil_configs, handle_secrets_interactive
from utils import parse_sse_json, extract_text_from_content
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich.panel import Panel
from rich import box

TOOL_CHANGE_TRIGGERS = {"mcp-add", "code-mode"}

async def confirm_action(title: str, text: str = "") -> bool:
    """Confirm action using questionary"""
    message = f"{title}: {text}" if text else title
    return await questionary.confirm(message, default=False).ask_async()

def render_verbose_panel(
    console,
    title: str,
    lines: list[str],
):
    """
    Render verbose/debug output as a de-emphasized panel.
    """
    if not lines:
        return

    content = "\n".join(lines)

    console.print(
        Panel(
            f"[dim]{content}[/dim]",
            title=f"[grey70]{title}[/grey70]",
            border_style="grey39",
            box=box.ROUNDED,
            padding=(1, 2),
            style="grey58",
        )
    )
        
async def cli_chat_llm(
    console,
    client: MCPGatewayClient,
    provider_name: str,
    user_message: str,
    model: str,
    mode: str = "dynamic",
    max_iterations: int=10,
    verbose: bool = False
):
    
    provider = LLMProviderFactory.get_provider(provider_name)
    tools = await client.list_tools()
    messages = [
        {
            "role": "system",
            "content": MCP_BRIDGE_MESSAGES.get(mode)
        },
        {
            "role": "user",
            "content": user_message
        }
    ]

    for iteration in range(max_iterations):
        verbose_lines = []
        with Progress(SpinnerColumn(), TextColumn("[dim]Thinking...[/dim]"), console=console, transient=True) as progress:
            progress.add_task("", total=None)
            response, assistant_msg, finish_reason = await provider.generate(
                    messages=messages,
                    model=model,
                    tools=tools,
                    mode=mode
                )
        
        messages.append(assistant_msg)

        if finish_reason == "stop":
            return {
                "content": assistant_msg.get('content', ''),
                "active_servers": client.active_servers,
                "available_tools": list(client.available_tools.keys()),
                "full_response": response
            }
        
        if finish_reason == "tool_calls" and assistant_msg.get('tool_calls'):
            tool_calls = assistant_msg['tool_calls']
            
            # Show iteration info
            console.print(f"\n[dim]🔄 Step {iteration+1}/{max_iterations} • {len(tool_calls)} action{'s' if len(tool_calls) > 1 else ''}[/dim]")
            
            if verbose:
                verbose_lines.append(
                    f"Iteration {iteration+1}/{max_iterations} — {len(tool_calls)} tool call(s)"
                )
                
            tools_changed = False

            for tc in tool_calls:
                tool_name = tc['function']['name']
                tool_args = json.loads(tc['function']['arguments'])
                tool_call_id = tc['id']

                # Visual indicators for different tool types
                if tool_name == "mcp-find":
                    query = tool_args.get('query', '')
                    console.print(f"  [cyan]🔍 Searching servers:[/cyan] {query}")
                elif tool_name == "mcp-exec":
                    console.print(f"  [yellow]⚙️  Running code[/yellow]")
                elif tool_name == "code-mode":
                    console.print(f"  [magenta]🔧 Creating tool:[/magenta] {tool_args.get('name', 'unnamed')}")
                else:
                    console.print(f"  [green]🔨 Using tool:[/green] {tool_name}")

                if verbose:
                    verbose_lines.append(
                        f"→ Tool call: {tool_name}\n  Args: {json.dumps(tool_args, indent=2)}"
                    )

                if tool_name in TOOL_CHANGE_TRIGGERS:
                    tools_changed = True

                try:
                    if tool_name == "mcp-find":
                        servers = await client.find_mcp_servers(tool_args.get('query'))

                        final_server, additional_info = await handle_mcp_find(console, servers, verbose=verbose)
                        
                        if not final_server:
                            console.print(f"    [dim]↳ {additional_info}[/dim]")
                            if verbose:
                                verbose_lines.append(additional_info)
                            continue

                        final_server_name = final_server['name']
                        console.print(f"    [dim]↳ Selected:[/dim] [bold]{final_server_name}[/bold]")

                        # Handle config schema
                        if 'config_schema' in final_server:
                            console.print(f"    [dim]↳ Configuring...[/dim]")
                            config_server, config_keys, config_values = hil_configs(final_server)
                            await client.add_mcp_configs( 
                                server=config_server, 
                                keys=config_keys, 
                                values=config_values
                            )
                            if verbose:
                                verbose_lines.append("✓ Configuration completed")

                        # Handle required secrets
                        if 'required_secrets' in final_server:
                            console.print(f"    [dim]↳ Setting up credentials...[/dim]")
                            secrets_configured = handle_secrets_interactive(final_server)
                            
                            if not secrets_configured:
                                console.print("\n[yellow]⚠️  Warning: Proceeding without proper secret configuration[/yellow]")
                                if not await confirm_action("Continue adding server?"):
                                    console.print("[red]Aborted.[/red]")
                                    exit(0)

                        # Add server
                        console.print(f"    [dim]↳ Adding server...[/dim]")
                        if verbose:
                            verbose_lines.append(f"\nAdding server '{final_server_name}'...")
                            
                        add_mcp_result = await client.add_mcp_servers( 
                            server_name=final_server_name, 
                            activate=True
                        )
                        stringified_add_mcp_result = json.dumps(add_mcp_result)
                        if verbose:
                            verbose_lines.append(
                                "Add Server Result:\n"
                                + json.dumps(add_mcp_result, indent=2)
                            )

                        if stringified_add_mcp_result.lower().startswith("successfully"):
                            add_status = "success"
                            console.print(f"    [green]✓ Server added successfully[/green]")
                        elif stringified_add_mcp_result.lower().startswith("error"):
                            add_status = "failed"
                            console.print(f"    [red]✗ Failed to add server[/red]")
                        else:
                            add_status = "undefined"
                            console.print(f"    [yellow]⚠ Unknown status[/yellow]")
                        
                        if verbose:
                            verbose_lines.append(f"\n✓ Server '{final_server_name}' successfully added and activated!")

                        result_text = additional_info + json.dumps(
                            {
                                "server": final_server, 
                                "status": add_status,
                                "message": stringified_add_mcp_result
                            }
                        )

                    # Handle code-mode - create a custom tool code-mode-{name}
                    elif tool_name == "code-mode":
                        result = await client.create_dynamic_code_tool(
                            code='',
                            name=tool_args.get('name'),
                            servers=tool_args.get('servers'),
                            timeout=tool_args.get('timeout', 30)
                        )
                        console.print(f"    [green]✓ Tool created[/green]")
                        result_text = json.dumps(result)

                    # Handle mcp-exec - Runs the generated script
                    elif tool_name == "mcp-exec":
                        exec_tool_name = tool_args.get('name')
                        exec_arguments = tool_args.get('arguments', {})
                        script = exec_arguments.get('script', '')

                        if verbose:
                            verbose_lines.append(
                                "Generated Code:\n"
                                + (script if script else "No script provided")
                            )

                        exec_result = await client.execute_dynamic_code_tool(
                            tool_name=exec_tool_name,
                            script=script
                        )
                        console.print(f"    [green]✓ Code executed[/green]")
                        
                        if isinstance(exec_result, dict) and 'content' in exec_result:
                            result_text = extract_text_from_content(exec_result['content'])
                        else:
                            result_text = json.dumps(exec_result)

                    else:
                        # Regular MCP tool call
                        tool_result = await client.call_tool( 
                            name=tool_name, 
                            arguments=tool_args
                        )
                        console.print(f"    [green]✓ Done[/green]")
                        
                        if isinstance(tool_result, dict) and 'content' in tool_result:
                            result_text = extract_text_from_content(tool_result['content'])
                        else:
                            result_text = json.dumps(tool_result)

                    if verbose:
                        verbose_lines.append(
                            "Tool Result Preview:\n"
                            + result_text[:300]
                            + ("…" if len(result_text) > 300 else "")
                        )

                    messages.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": result_text
                    })

                except Exception as e:
                    error_msg = f"Error calling tool {tool_name}: {str(e)}"
                    console.print(f"    [red]✗ Error: {str(e)[:50]}...[/red]")
                    if verbose:
                        verbose_lines.append(f"ERROR: {error_msg}")
                    messages.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": error_msg
                    })
        
            if tools_changed:
                console.print(f"  [dim]🔄 Refreshing tools...[/dim]")
                if verbose:
                    verbose_lines.append("Tools changed → refreshing available tools")
                tools = await client.list_tools(client)
                if verbose:
                    verbose_lines.append(f"Now have {len(tools)} tools available")

            if verbose:
                render_verbose_panel(
                    console,
                    title=f"Verbose · Iteration {iteration+1}",
                    lines=verbose_lines,
                )
            continue

        # Unexpected finish reason
        if verbose:
            verbose_lines.append(f"Unexpected finish_reason: {finish_reason}")  
        break

    return {
            "content": "Maximum iterations reached without completion",
            "messages": messages,
            "active_servers": client.active_servers,
            "available_tools": list(client.available_tools.keys()),
            "full_response": response
        }