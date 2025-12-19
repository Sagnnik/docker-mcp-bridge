import httpx
import json
import asyncio
from typing import Optional, List, Dict, Any
from utils import parse_sse_json, extract_text_from_content
from provider import LLMProviderFactory
from prompts import MCP_BRIDGE_MESSAGES
from configs_secrets import hil_configs, handle_secrets_interactive
from rich.console import Console
from rich.prompt import Prompt, Confirm, IntPrompt
from rich.table import Table
from rich import box
import questionary

TOOL_CHANGE_TRIGGERS = {"mcp-add", "code-mode"}

def handle_mcp_find(console, servers, verbose=False):
    """
    Handle mcp-find
    - if it returns only one server auto add it
    - if it returns multiple servers let the user choose it
    - let user input configs and secrets interactively using cli
    """
    additional_info = ""
    if verbose:
        console.print("\n[bold cyan]=== Servers Found ===[/bold cyan]\n")
    
    if not servers:
        if verbose:
            console.print("[yellow]No relevant MCP server found![/yellow]")
        additional_info = "No relevant MCP server found!"
        return None, additional_info
    
    final_server = None
    if len(servers) == 1:
        final_server = servers[0]
        if verbose:
            console.print(f"[green]Found 1 server:[/green] {final_server['name']}")
            console.print(f"[dim]Description:[/dim] {final_server.get('description', 'N/A')}")
    else:
        # Display servers in a nice table format
        for i, server in enumerate(servers, 1):
            has_config = '✓ config' if 'config_schema' in server else ''
            has_secrets = '✓ secrets' if 'required_secrets' in server else ''
            badges = ' | '.join(filter(None, [has_config, has_secrets]))

            console.print(f"[bold cyan]{i}.[/bold cyan] [bold]{server['name']}[/bold] {f'({badges})' if badges else ''}")
            desc = server.get('description', 'No description')
            if len(desc) > 100:
                desc = desc[:97] + "..."
            console.print(f"   [dim]{desc}[/dim]\n")

        # Create choices for questionary selector
        choices = []
        for server in servers:
            has_config = '✓ config' if 'config_schema' in server else ''
            has_secrets = '✓ secrets' if 'required_secrets' in server else ''
            badges = ' | '.join(filter(None, [has_config, has_secrets]))
            
            choice_text = f"{server['name']}"
            if badges:
                choice_text += f" ({badges})"
            
            choices.append(questionary.Choice(
                title=choice_text,
                value=server
            ))
        
        # Use questionary select for arrow-key navigation
        final_server = questionary.select(
            "Select a server:",
            choices=choices,
            use_arrow_keys=True
        ).ask()
        
        if final_server is None:
            console.print("[red]Server selection cancelled[/red]")
            raise ValueError("Server selection cancelled")

    final_server_name = final_server['name']
    if verbose:
        console.print(f"\n[green]✓ Selected server:[/green] [bold]{final_server_name}[/bold]")
        
    return final_server, additional_info

class MCPGatewayClient:
    MCP_PROTOCOL_VERSION = "2024-11-05"
    MCP_URL = "http://localhost:8811/mcp"

    def __init__(self):
        self.session_id: Optional[str] = None
        self._next_id = 1
        self.available_tools: Dict[str, Dict] = {}
        self.active_servers: List[str] = []
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=300)
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    async def initialize(self):
        """Initialize MCP session"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-api-gateway", "version": "1.0.0"}
            }
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        response.raise_for_status()
        
        self.session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        
        await self._client.post(
            self.MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        
        await self.list_tools()

    async def list_tools(self):
        """List available MCP tools"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
            "params": {}
        }
        self._next_id += 1

        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )

        data = self._parse_response(response.text)
        tools = data.get('result', {}).get('tools', [])
        
        self.available_tools = {tool["name"]: tool for tool in tools}
        return tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        """Call an MCP tool"""
        if name not in self.available_tools:
            raise ValueError(f"Tool {name} not found")
        
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments}
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
        )
        
        data = self._parse_response(response.text)
        if 'error' in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        
        return data["result"]
        
    async def find_mcp_servers(self, query: str):
        try:
            result = await self.call_tool(name="mcp-find", arguments={"query": query})
            result = json.loads(result['content'][0]['text'])
            return result['servers']
        except Exception as e:
            if self.verbose:
                print(f"Error finding MCP servers: {e}")
            return []
        
    async def add_mcp_configs(self, server: str, keys: List[str], values: List[Any]):
        try: 
            results = []
            for i, key in enumerate(keys):
                result = await self.call_tool(name="mcp-config-set", arguments={"server": server, "key": key, "value": values[i]})
                results.append(result)
            return results
        except Exception as e:
            if self.verbose:
                print(f"Error setting configs using mcp-config-set: {str(e)}")
            raise

    async def add_mcp_servers(self, server_name: str, activate: bool = True):
        
        try:
            result = await self.call_tool(name="mcp-add", arguments={"name": server_name, "activate": activate})
            if result.get('content'):
                if server_name not in self.active_servers:
                    self.active_servers.append(server_name)
                _ = await self.list_tools()
            return result
        
        except Exception as e:
            if self.verbose:
                print(f"Error adding MCP server {server_name}: {e}")
            return False
        
    async def remove_mcp_servers(self, server_name: str):
        try:
            result = await self.call_tool(name="mcp-remove", arguments={"name": server_name})
            
            if result.get('content'):
                if server_name in self.active_servers:
                    self.active_servers.remove(server_name)
                
                await self.list_tools()
                
            return result
        
        except Exception as e:
            if self.verbose:
                print(f"Error removing MCP server {server_name}: {e}")
            return False
        
    async def create_dynamic_code_tool(self, name: str, servers: List[str], timeout: int = 30):
        if not servers or len(servers) == 0:
            raise ValueError("At least one server must be provided for code-mode")
        
        arguments = {
            "code": '',
            "name": name,
            "servers": servers,  
            "timeout": timeout
        }
        
        try:
            result = await self.call_tool(
                name='code-mode', 
                arguments=arguments
            )
            tool_name = f"code-mode-{name}"
            
            return {
                "tool_name": tool_name,
                "raw_result": result
            }
        except Exception as e:
            raise RuntimeError(f"Error executing code-mode: {e}")
        
    async def execute_dynamic_code_tool(self, tool_name: str, script: str):
        """Execute the created tool"""
        try:
            result = await self.call_tool(
                name="mcp-exec",
                arguments={
                    "name": tool_name,
                    "arguments": {
                        "script": script
                    }
                }
            )
            return result
        except Exception as e:
            raise RuntimeError(f"Error executing dynamic code tool {tool_name}: {e}")
        
    def _parse_response(self, content) -> str:
        """
        Normalize MCP / SSE responses into plain text
        """
        if content is None:
            return ""

        # MCP structured content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    texts.append(item.get("text", ""))
            return "\n".join(texts).strip()

        # Already a string (maybe SSE)
        if isinstance(content, str):
            for line in content.strip().split("\n"):
                if line.startswith("data: "):
                    try:
                        return json.loads(line[6:])
                    except Exception:
                        return line[6:]
            return content.strip()

        # Fallback
        return str(content).strip()
    
async def confirm_action(title: str, text: str = "") -> bool:
    """Confirm action using questionary"""
    message = f"{title}: {text}" if text else title
    return await questionary.confirm(message, default=False).ask_async()
        
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
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.live import Live
    from rich.panel import Panel
    
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
        # Show thinking indicator
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
                print(f"\n==== Iteration {iteration+1}/{max_iterations} ==== Processing {len(tool_calls)} tool calls ====\n")
                
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
                    print(f"Calling tool: {tool_name} with args: {tool_args}")

                if tool_name in TOOL_CHANGE_TRIGGERS:
                    tools_changed = True

                try:
                    if tool_name == "mcp-find":
                        servers = await client.find_mcp_servers(tool_args.get('query'))

                        final_server, additional_info = handle_mcp_find(console, servers, verbose=verbose)
                        
                        if not final_server:
                            console.print(f"    [dim]↳ {additional_info}[/dim]")
                            if verbose:
                                print(additional_info)
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
                                print("✓ Configuration completed")

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
                            print(f"\nAdding server '{final_server_name}'...")
                            
                        add_mcp_result = await client.add_mcp_servers( 
                            server_name=final_server_name, 
                            activate=True
                        )
                        stringified_add_mcp_result = json.dumps(add_mcp_result)
                        if verbose:
                            print("\n=== Add Server Result ===")
                            print(json.dumps(add_mcp_result, indent=2))

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
                            print(f"\n✓ Server '{final_server_name}' successfully added and activated!")

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
                            print("\n=== Code to be Executed ===\n")
                            print(script if script else "No script provided")

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
                        print(f"\n=== Result Text after iteration {iteration+1} ===\n")
                        print(f"Tool result preview: {result_text[:200]}...")

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
                        print(error_msg)
                    messages.append({
                        "tool_call_id": tool_call_id,
                        "role": "tool",
                        "name": tool_name,
                        "content": error_msg
                    })
        
            if tools_changed:
                console.print(f"  [dim]🔄 Refreshing tools...[/dim]")
                if verbose:
                    print("Tools changed, refreshing tool list...")
                tools = await client.list_tools(client)
                if verbose:
                    print(f"Now have {len(tools)} tools available")

            continue

        # Unexpected finish reason
        if verbose:
            print(f"Unexpected finish_reason: {finish_reason}")  
        break

    return {
            "content": "Maximum iterations reached without completion",
            "messages": messages,
            "active_servers": client.active_servers,
            "available_tools": list(client.available_tools.keys()),
            "full_response": response
        }