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
from typing import Optional, List
from mcp_host import MCPGatewayClient
import httpx
from prompt_toolkit import prompt
from prompt_toolkit.shortcuts import radiolist_dialog, button_dialog
from prompt_toolkit.styles import Style

console = Console()

# ============= Styles =============

dialog_style = Style.from_dict({
    'dialog': 'bg:#1e1e1e',
    'dialog.body': 'bg:#1e1e1e #00ff00',
    'dialog.body text-area': 'bg:#1e1e1e #00ff00',
    'button': 'bg:#2e2e2e #00ff00',
    'button.focused': 'bg:#00ff00 #000000 bold',
    'radio-list': 'bg:#1e1e1e #00ff00',
    'radio-checked': 'bg:#1e1e1e #00ff00 bold',
    'radio': 'bg:#1e1e1e #888888',
})

# ============= Print Helpers =============

def print_welcome():
    """Display welcome message"""
    console.print("\n[bold cyan]╔══════════════════════════════════════════════╗[/bold cyan]")
    console.print("[bold cyan]║[/bold cyan]  [bold white]🤖 MCP Gateway - Interactive Chat[/bold white]       [bold cyan]    ║[/bold cyan]")
    console.print("[bold cyan]╚══════════════════════════════════════════════╝[/bold cyan]")
    console.print("\n[dim]Type your message or use commands:[/dim]")
    console.print("  [cyan]/help[/cyan]   - Show available commands")
    # console.print("  [cyan]/add[/cyan]    - Add MCP servers")
    # console.print("  [cyan]/find[/cyan]   - Search for servers")
    # console.print("  [cyan]/list[/cyan]   - List tools & servers")
    # console.print("  [cyan]/remove[/cyan] - Remove a server")
    console.print("  [cyan]/exit[/cyan]   - Quit\n")

def print_success(message: str):
    console.print(f"✅ {message}", style="bold green")

def print_error(message: str):
    console.print(f"❌ {message}", style="bold red")

def print_info(message: str):
    console.print(f"💡 {message}", style="bold blue")

def print_chat_response(content: str):
    """Display chat response"""
    panel = Panel(
        Markdown(content),
        title="🤖 Assistant",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2)
    )
    console.print(panel)

def print_help():
    """Show help panel"""
    help_text = """
[bold cyan]Available Commands:[/bold cyan]

[bold]/chat <message>[/bold]   - Chat with AI using available tools
[bold]/add[/bold]              - Search and add MCP servers
[bold]/find <query>[/bold]     - Search for specific servers
[bold]/list[/bold]             - Show active servers and tools
[bold]/remove[/bold]           - Remove a server
[bold]/help[/bold]             - Show this help
[bold]/exit[/bold]             - Exit the CLI

[bold cyan]Examples:[/bold cyan]

  /find github
  /add
  What's the weather in San Francisco?
  Search for MCP repositories
    """
    console.print(Panel(help_text, title="💡 Help", border_style="cyan", box=box.ROUNDED))

# ============= Interactive Selection =============

def select_from_list(items: List[dict], title: str, name_key: str = 'name') -> Optional[dict]:
    """Interactive selection using arrow keys"""
    if not items:
        return None
    
    # Create radio list options
    values = [(i, f"{item.get(name_key, 'Unknown')} - {item.get('description', '')[:50]}") 
              for i, item in enumerate(items)]
    
    result = radiolist_dialog(
        title=title,
        text="Use arrow keys to navigate, Enter to select:",
        values=values,
        style=dialog_style,
    ).run()
    
    if result is not None:
        return items[result]
    return None

async def confirm_action(title: str, text: str) -> bool:
    result = await button_dialog(
        title=title,
        text=text,
        buttons=[('Yes', True), ('No', False)],
        style=dialog_style,
    ).run_async()
    return bool(result)

# ============= Command Handlers =============

async def handle_add(client: MCPGatewayClient, http_client):
    """Add server workflow"""
    from configs_secrets import hil_configs, handle_secrets_interactive
    
    console.print("\n[bold cyan]🔍 Searching for servers...[/bold cyan]")
    query = Prompt.ask("Search query (or press Enter for all)", default="")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Searching...", total=None)
        servers = await client.find_mcp_servers(http_client, query or "mcp")
    
    if not servers:
        print_error("No servers found")
        return
    
    print_success(f"Found {len(servers)} servers")
    
    # Interactive selection
    server = select_from_list(servers, "Select Server to Add")
    
    if not server:
        print_info("Cancelled")
        return
    
    server_name = server['name']
    console.print(f"\n[bold]Selected:[/bold] {server_name}")
    console.print(f"[dim]{server.get('description', 'No description')}[/dim]\n")
    
    # Check requirements
    needs_config = 'config_schema' in server
    needs_secrets = 'required_secrets' in server
    
    if needs_config or needs_secrets:
        console.print("[yellow]⚙️  Setup required:[/yellow]")
        if needs_config:
            console.print("  • Configuration needed")
        if needs_secrets:
            console.print("  • Credentials needed")
        console.print()
    
    if not confirm_action("Confirm", f"Add '{server_name}'?"):
        print_info("Cancelled")
        return
    
    # Configure
    if needs_config:
        config_server, config_keys, config_values = hil_configs(server)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Configuring...", total=None)
            await client.add_mcp_configs(http_client, config_server, config_keys, config_values)
    
    if needs_secrets:
        handle_secrets_interactive(server)
    
    # Add server
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Adding server...", total=None)
        result = await client.add_mcp_servers(http_client, server_name, activate=True)
    
    if result:
        print_success(f"🎉 '{server_name}' added successfully!")
        await client.list_tools(http_client)
    else:
        print_error(f"Failed to add '{server_name}'")

async def handle_find(client: MCPGatewayClient, http_client, query: str):
    """Search servers"""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task(f"Searching for '{query}'...", total=None)
        servers = await client.find_mcp_servers(http_client, query)
    
    if not servers:
        print_error(f"No servers found matching '{query}'")
        return
    
    print_success(f"Found {len(servers)} server(s)\n")
    
    # Display table
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("Name", style="bold green", width=25)
    table.add_column("Description", style="white", width=60)
    
    for server in servers:
        name = server.get('name', 'N/A')
        desc = server.get('description', 'No description')
        if len(desc) > 57:
            desc = desc[:57] + "..."
        table.add_row(name, desc)
    
    console.print(table)
    
    # Ask to add
    if confirm_action("Add Server?", "Would you like to add one of these servers?"):
        server = select_from_list(servers, "Select Server")
        if server:
            await handle_add_selected(client, http_client, server)

async def handle_add_selected(client: MCPGatewayClient, http_client, server: dict):
    """Add a pre-selected server"""
    from configs_secrets import hil_configs, handle_secrets_interactive
    
    server_name = server['name']
    
    # Check requirements
    needs_config = 'config_schema' in server
    needs_secrets = 'required_secrets' in server
    
    # Configure
    if needs_config:
        config_server, config_keys, config_values = hil_configs(server)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Configuring...", total=None)
            await client.add_mcp_configs(http_client, config_server, config_keys, config_values)
    
    if needs_secrets:
        handle_secrets_interactive(server)
    
    # Add server
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Adding server...", total=None)
        result = await client.add_mcp_servers(http_client, server_name, activate=True)
    
    if result:
        print_success(f"🎉 '{server_name}' added!")
        await client.list_tools(http_client)
    else:
        print_error(f"Failed to add '{server_name}'")

async def handle_list(client: MCPGatewayClient, http_client):
    """List servers and tools"""
    console.print("\n[bold cyan]📊 Current Status[/bold cyan]\n")
    
    # Active servers
    if client.active_servers:
        console.print("[bold green]Active Servers:[/bold green]")
        for server in client.active_servers:
            console.print(f"  • {server}")
    else:
        console.print("[dim]No active servers[/dim]")
    
    console.print()
    
    # Tools
    tools = list(client.available_tools.values())
    if tools:
        console.print(f"[bold green]Available Tools:[/bold green] [cyan]{len(tools)} tools[/cyan]\n")
        
        table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        table.add_column("Tool", style="green", width=30)
        table.add_column("Description", width=60)
        
        for tool in tools[:10]:  # Show first 10
            name = tool.get('name', 'N/A')
            desc = tool.get('description', 'No description')
            if len(desc) > 57:
                desc = desc[:57] + "..."
            table.add_row(name, desc)
        
        console.print(table)
        
        if len(tools) > 10:
            console.print(f"\n[dim]... and {len(tools) - 10} more tools[/dim]")
    else:
        console.print("[dim]No tools available yet[/dim]")
    
    console.print()

async def handle_remove(client: MCPGatewayClient, http_client):
    """Remove server"""
    if not client.active_servers:
        print_error("No active servers to remove")
        return
    
    # Create list for selection
    server_list = [{'name': s, 'description': ''} for s in client.active_servers]
    server = select_from_list(server_list, "Select Server to Remove")
    
    if not server:
        print_info("Cancelled")
        return
    
    server_name = server['name']
    
    if not confirm_action("Confirm Removal", f"Remove '{server_name}'?\nAll its tools will be removed."):
        print_info("Cancelled")
        return
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Removing...", total=None)
        result = await client.remove_mcp_servers(http_client, server_name)
    
    if result:
        print_success(f"Removed '{server_name}'")
    else:
        print_error(f"Failed to remove '{server_name}'")

async def handle_chat(client: MCPGatewayClient, http_client, message: str):
    """Handle chat message"""
    console.print(f"\n[bold]You:[/bold] {message}\n")
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Thinking...", total=None)
        
        try:
            result = await client.chat_with_llm(
                provider_name="openai",
                user_message=message,
                model="gpt-4o",
                initial_servers=list(client.active_servers) if client.active_servers else [],
                mode="dynamic",
                max_iterations=5,
                verbose=False  # Disable verbose output
            )
            
            progress.stop()
            
            if result.get('content'):
                print_chat_response(result['content'])
            
            # Show active servers if changed
            if result.get('active_servers'):
                console.print(f"\n[dim]Active: {', '.join(result['active_servers'])}[/dim]")
        
        except Exception as e:
            progress.stop()
            print_error(f"Error: {str(e)}")

# ============= Main Chat Loop =============

async def chat_loop():
    """Main interactive chat loop"""
    print_welcome()
    
    async with httpx.AsyncClient(timeout=300) as http_client:
        client = MCPGatewayClient()
        
        # Initialize
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Initializing...", total=None)
            await client.initialize(http_client)
            await client.list_tools(http_client)
        
        print_success("Ready!\n")
        
        # Main loop
        while True:
            try:
                # Get input
                user_input = Prompt.ask("[bold green]›[/bold green]").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.startswith('/'):
                    parts = user_input.split(maxsplit=1)
                    cmd = parts[0].lower()
                    args = parts[1] if len(parts) > 1 else ""
                    
                    if cmd == '/exit' or cmd == '/quit':
                        if confirm_action("Exit", "Are you sure?"):
                            print_info("Goodbye! 👋")
                            break
                    
                    elif cmd == '/help':
                        print_help()
                    
                    elif cmd == '/add':
                        await handle_add(client, http_client)
                    
                    elif cmd == '/find':
                        if not args:
                            args = Prompt.ask("Search query")
                        await handle_find(client, http_client, args)
                    
                    elif cmd == '/list':
                        await handle_list(client, http_client)
                    
                    elif cmd == '/remove':
                        await handle_remove(client, http_client)
                    
                    else:
                        print_error(f"Unknown command: {cmd}")
                        print_info("Type /help to see available commands")
                
                else:
                    # Regular chat
                    await handle_chat(client, http_client, user_input)
            
            except KeyboardInterrupt:
                console.print()
                if confirm_action("Exit", "Exit the chat?"):
                    break
            except EOFError:
                break
            except Exception as e:
                print_error(f"Error: {str(e)}")

# ============= CLI Entry Point =============

@click.command()
@click.version_option(version="2.0.0")
def cli():
    """
    🤖 MCP Gateway - Interactive Chat Interface
    
    Chat with AI and manage MCP servers with /commands
    """
    asyncio.run(chat_loop())

if __name__ == '__main__':
    cli()