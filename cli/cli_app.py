import asyncio
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import box
import json
import httpx
from typing import Optional, List
from mcp_host import MCPGatewayClient

console = Console()

def print_banner():
    """Display welcome banner"""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║        🤖 MCP Gateway CLI - Tool Management Made Easy     ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
    """
    console.print(banner, style="bold cyan")

def print_success(message: str):
    """Print success message"""
    console.print(f"✅ {message}", style="bold green")

def print_error(message: str):
    """Print error message"""
    console.print(f"❌ {message}", style="bold red")

def print_warning(message: str):
    """Print warning message"""
    console.print(f"⚠️  {message}", style="bold yellow")

def print_info(message: str):
    """Print info message"""
    console.print(f"ℹ️  {message}", style="bold blue")

def print_section_header(title: str):
    """Print section header"""
    console.print(f"\n{'─' * 70}", style="cyan")
    console.print(f"  {title}", style="bold cyan")
    console.print(f"{'─' * 70}", style="cyan")

def print_servers_table(servers: List[dict]):
    """Display servers in a beautiful table"""
    if not servers:
        print_warning("No servers found")
        return
    
    table = Table(
        title="🔍 Available MCP Servers",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        title_style="bold cyan"
    )
    table.add_column("#", style="cyan", width=4)
    table.add_column("Name", style="bold green", width=25)
    table.add_column("Description", style="white", width=50)
    table.add_column("Config", justify="center", width=8)
    table.add_column("Secrets", justify="center", width=8)

    for i, server in enumerate(servers, 1):
        name = server.get('name', 'N/A')
        description = server.get('description', 'No description')[:47] + "..."
        has_config = '✓' if 'config_schema' in server else '○'
        has_secrets = '✓' if 'required_secrets' in server else '○'
        
        table.add_row(
            str(i),
            name,
            description,
            has_config,
            has_secrets
        )
    
    console.print(table)

def print_tools_table(tools: List[dict]):
    """Display tools in a beautiful table"""
    if not tools:
        print_warning("No tools available")
        return
    
    table = Table(
        title="🔧 Available Tools",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        title_style="bold cyan"
    )
    
    table.add_column("Tool Name", style="bold green", width=30)
    table.add_column("Description", style="white", width=60)
    
    for tool in tools:
        name = tool.get('name', 'N/A')
        description = tool.get('description', 'No description')[:57] + "..."
        table.add_row(name, description)
    
    console.print(table)

def print_json_pretty(data: dict, title: str = "Response"):
    """Display JSON in a pretty panel"""
    json_str = json.dumps(data, indent=2)
    syntax = Syntax(json_str, "json", theme="monokai", line_numbers=False)
    panel = Panel(syntax, title=f"📄 {title}", border_style="cyan", box=box.ROUNDED)
    console.print(panel)

def print_chat_response(content: str):
    """Display chat response in a nice format"""
    panel = Panel(
        Markdown(content),
        title="🤖 Assistant Response",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2)
    )
    console.print(panel)

async def add_server_interactive(client: MCPGatewayClient, http_client, server: dict):
    """Add server with interactive config/secrets handling"""
    from configs_secrets import hil_configs, handle_secrets_interactive

    server_name = server['name']
    
    print_section_header(f"⚙️  Configuring: {server_name}")

    # Handle configs
    if 'config_schema' in server:
        print_info("This server requires configuration")
        config_server, config_keys, config_values = hil_configs(server)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Setting configurations...", total=None)
            await client.add_mcp_configs(
                client=http_client,
                server=config_server,
                keys=config_keys,
                values=config_values
            )
        print_success("Configuration completed")

    # Handle secrets
    if 'required_secrets' in server:
        secrets_ok = handle_secrets_interactive(server)
        if not secrets_ok:
            print_warning("Continuing without complete secret configuration")

    # Add server
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Adding server '{server_name}'...", total=None)
        result = await client.add_mcp_servers(
            client=http_client,
            server_name=server_name,
            activate=True
        )
    
    if result:
        print_success(f"Server '{server_name}' added successfully! 🎉")
        
        # Show available tools
        tools = list(client.available_tools.values())
        new_tools = [t for t in tools if server_name in t.get('name', '').lower()]
        
        if new_tools:
            console.print(f"\n[bold]New tools available:[/bold]")
            for tool in new_tools[:5]:
                console.print(f"  • {tool['name']}", style="green")
            if len(new_tools) > 5:
                console.print(f"  ... and {len(new_tools) - 5} more")
    else:
        print_error(f"Failed to add server '{server_name}'")

def show_interactive_help():
    """Show help for interactive mode"""
    help_text = """
[bold cyan]Available Commands:[/bold cyan]

  [bold]tools[/bold]         - List all available tools
  [bold]servers[/bold]       - Show active servers
  [bold]search <query>[/bold] - Search for MCP servers
  [bold]add <name>[/bold]    - Add an MCP server
  [bold]help[/bold]          - Show this help
  [bold]exit[/bold]          - Exit interactive mode

[bold cyan]Examples:[/bold cyan]
  search github
  add weather
  tools
    """
    console.print(Panel(help_text, title="💡 Help", border_style="cyan", box=box.ROUNDED))

@click.group()
@click.version_option(version="0.1.0")
def cli():
    """
    MCP Gateway CLI - Manage MCP servers and chat with AI tools
    
    Examples:
      mcp-cli chat "What's the weather in SF?"
      mcp-cli search github
      mcp-cli list-tools
    """
    pass

@cli.command()
@click.argument('query')
@click.option('--activate', is_flag=True, help="Auto-activate found server")
def search(query: str, activate:bool):
    """
    Search for MCP servers
    
    Example: mcp-cli search github
    """
    print_banner()
    print_section_header(f"🔍 Searching for: {query}")

    async def run():
        async with httpx.AsyncClient(timeout=120) as client:
            mcp = MCPGatewayClient()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                task = progress.add_task("Initializing MCP Gateway...", total=None)
                await mcp.list_tools(client)
                tools = await mcp.list_tools(client)

            if format == 'json':
                print_json_pretty({"tools": tools}, "Available Tools")

            else:
                print_success(f"Loaded {len(tools)} tools")
                print_tools_table(tools)

                if mcp.active_servers:
                    print_info(f"Active servers: {', '.join(mcp.active_servers)}")

    asyncio.run(run())

@cli.command()
@click.argument('messages')
@click.option('--model', default='gpt-4o', help='LLM model to use')
@click.option('--provider', default='openai', help='LLM provider')
@click.option('--mode', type=click.Choice(['dynamic', 'code', 'default']), default='dynamic', help='Tool mode')
@click.option('--servers', multiple=True, help='Initial servers to load')
@click.option('--max-iter', default=5, help='Max agentic iterations')
@click.option('--verbose', is_flag=True, help='Show detailed tool calls')
def chat(message: str, model: str, provider: str, mode: str, servers: tuple, max_iter: int, verbose: bool):
    """
    Chat with AI using MCP tools
    
    Examples:
      mcp-cli chat "What's the weather in SF?"
      mcp-cli chat "Search GitHub for MCP servers" --mode dynamic
      mcp-cli chat "List my repos" --servers github
    """

    print_banner()
    print_section_header("💬 Starting Chat Session")

    console.print(f"[bold]User:[/bold] {message}\n")

    async def run():
        async with httpx.AsyncClient(timeout=120) as client:
            mcp = MCPGatewayClient()

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing...", total=None)

                try:
                    result = await mcp.chat_with_llm(
                        provider_name=provider,
                        user_message=message,
                        model=model,
                        initial_servers=list(servers),
                        mode=mode,
                        max_iterations=max_iter
                    )

                    progress.stop()

                    if result.get('content'):
                        print_chat_response(result['content'])

                    if verbose:
                        console.print("\n")
                        print_section_header("📊 Session Metadata")

                        metadata = {
                            "active_servers": result.get('active_servers', []),
                            "available_tools": result.get('available_tools', []),
                        }
                        print_json_pretty(metadata, "Session Info")

                except Exception as e:
                    progress.stop()
                    print_error(f"Chat error: {str(e)}")
                    if verbose:
                        console.print_exception()

    asyncio.run(run())

@cli.command()
@click.argument('server_name')
def add(server_name:str):
    """
    Add an MCP server by name
    
    Example: mcp-cli add github
    """
    print_banner()
    print_section_header(f"📦 Adding Server: {server_name}")
    async def run():
        async with httpx.AsyncClient(timeout=300) as http_client:
            client = MCPGatewayClient()
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing...", total=None)
                await client.initialize(http_client)
                await client.list_tools(http_client)

                progress.update(task, description=f"Searching for '{server_name}'...")
                servers = await client.find_mcp_servers(http_client, server_name)

            if not servers:
                print_error(f"Server '{server_name}' not found")
                return
            
            # Find exact match or let user choose
            exact_match = next((s for s in servers if s['name'] == server_name), None)

            if exact_match:
                server = exact_match
            elif len(servers) == 1:
                server = servers[0]
            else:
                print_warning(f"Multiple servers found matching '{server_name}'")
                print_servers_table(servers)
                choice = Prompt.ask(
                    "Select server number",
                    choices=[str(i) for i in range(1, len(servers) + 1)]
                )
                server = servers[int(choice) - 1]
            
            await add_server_interactive(client, http_client, server)

    asyncio.run(run())

@cli.command()
@click.argument('server_name')
def remove(server_name: str):
    """
    Remove an MCP server
    
    Example: mcp-cli remove github
    """
    print_banner()
    print_section_header(f"🗑️  Removing Server: {server_name}")
    
    if not Confirm.ask(f"Are you sure you want to remove '{server_name}'?"):
        print_info("Cancelled")
        return
    
    async def run():
        async with httpx.AsyncClient(timeout=300) as http_client:
            client = MCPGatewayClient()
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Removing server...", total=None)
                await client.initialize(http_client)
                result = await client.remove_mcp_servers(http_client, server_name)
            
            if result:
                print_success(f"Server '{server_name}' removed successfully")
            else:
                print_error(f"Failed to remove server '{server_name}'")
    
    asyncio.run(run())

@cli.command()
def interactive():
    """
    Start interactive mode for exploring MCP tools
    """
    print_banner()
    console.print("\n[bold cyan]🎮 Interactive Mode[/bold cyan]")
    console.print("Type 'help' for commands, 'exit' to quit\n")

    async def run():
        async with httpx.AsyncClient(timeout=300) as http_client:
            client = MCPGatewayClient()

            # Initialize
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Initializing...", total=None)
                await client.initialize(http_client)
                await client.list_tools(http_client)

            print_success("Ready! Type your commands below.")
            
            while True:
                try:
                    command = Prompt.ask("\n[bold green]mcp[/bold green]")

                    if command.lower() in ['exit', 'quit', 'q']:
                        print_info("Goodbye! 👋")
                        break

                    elif command.lower() == 'help':
                        show_interactive_help()
                    
                    elif command.lower() == 'tools':
                        tools = list(client.available_tools.values())
                        print_tools_table(tools)
                    
                    elif command.lower() == 'servers':
                        if client.active_servers:
                            print_success(f"Active: {', '.join(client.active_servers)}")
                        else:
                            print_info("No active servers")

                    elif command.lower().startswith('search '):
                        query = command[7:].strip()
                        servers = await client.find_mcp_servers(http_client, query)
                        print_servers_table(servers)
                    
                    elif command.lower().startswith('add '):
                        server_name = command[4:].strip()
                        servers = await client.find_mcp_servers(http_client, server_name)
                        if servers:
                            server = servers[0]
                            await add_server_interactive(client, http_client, server)

                    else:
                        print_warning(f"Unknown command: {command}")
                        print_info("Type 'help' to see available commands")
                
                except KeyboardInterrupt:
                    console.print()
                    if Confirm.ask("Exit interactive mode?"):
                        break
                except Exception as e:
                    print_error(f"Error: {str(e)}")
    
    asyncio.run(run())

if __name__ == '__main__':
    cli()