import asyncio
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Prompt, Confirm
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich.rule import Rule
from rich import box
import json
from typing import Optional, List
from src.mcp_catalog import MCPCatalogManager
from src.state_manager import MCPStateManager
from src.mcp_host import MCPGatewayClient
from src.cli_chat import cli_chat_llm
import questionary
from datetime import datetime
import subprocess
import shlex

from dataclasses import dataclass, asdict

@dataclass
class ChatConfig:
    provider_name: str = "openai"
    model: str = "gpt-4o-mini"
    mode: str = "dynamic"
    max_iterations: int = 10
    verbose: bool = True

CHAT_CONFIG = ChatConfig()

console = Console()

message_history = []
history_index = -1

# ============= Print Helpers =============

def print_welcome():
    console.clear()
    console.print(
    Panel(
        "[bold cyan]🤖 MCP Gateway[/bold cyan]\n"
        "[dim]Interactive AI + MCP Server Console[/dim]",
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )
)

    console.print(Rule(style="grey39"))

    console.print("[bold]Current configuration[/bold]\n")

    console.print(f"  Provider        [green]{CHAT_CONFIG.provider_name}[/green]")
    console.print(f"  Model           [green]{CHAT_CONFIG.model}[/green]")
    console.print(f"  Mode            [yellow]{CHAT_CONFIG.mode}[/yellow]")
    console.print(f"  Max iterations  [cyan]{CHAT_CONFIG.max_iterations}[/cyan]\n")

    console.print("[bold]Commands[/bold]\n")

    console.print("  [green]/help[/green]     Show available commands")
    console.print("  [green]/config[/green]   Configure provider & model")
    console.print("  [green]/add[/green]      Search and add MCP servers")
    console.print("  [green]/list[/green]     Show active servers and tools")
    console.print("  [green]!<cmd>[/green]    Execute shell commands")
    console.print("  [green]/exit[/green]     Quit the CLI\n")

    console.print("[dim]Type /help to get started.[/dim]\n")
    console.print(Rule(style="grey39"))

def status_panel(title: str, message: str, style: str = "cyan"):
    console.print(
        Panel(
            message,
            title=title,
            border_style=style,
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )

def print_success(message: str):
    status_panel("SUCCESS", f"✅ {message}", "green")

def print_error(message: str):
    status_panel("ERROR", f"❌ {message}", "red")

def print_info(message: str):
    status_panel("INFO", f"💡 {message}", "blue")

def print_chat_response(content: str):
    panel = Panel(
        Markdown(content),
        title="🤖 Assistant",
        subtitle=datetime.now().strftime("%H:%M:%S"),
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2)
    )
    console.print(panel)

def print_help():
    """Show help panel"""
    help_text = """
[bold cyan]Available Commands:[/bold cyan]

[bold]/config[/bold]           - Configure LLM provider, model, and behavior
[bold]/chat <message>[/bold]   - Chat with AI using available tools
[bold]/add[/bold]              - Search and add MCP servers
[bold]/find <query>[/bold]     - Search for specific servers
[bold]/list[/bold]             - Show active servers and tools
[bold]/remove[/bold]           - Remove a server
[bold]!<command>[/bold]        - Execute shell commands (e.g., !ls, !pwd)
[bold]/help[/bold]             - Show this help
[bold]/exit[/bold]             - Exit the CLI

[bold cyan]Features:[/bold cyan]

  Use arrow keys to navigate command history
  Tab completion for commands
  Execute shell commands with ! prefix

[bold cyan]Examples:[/bold cyan]

  /find github
  /add
  What's the weather in San Francisco?
  Search for MCP repositories
    """
    console.print(Panel(help_text, title="💡 Help", border_style="cyan", box=box.ROUNDED))

# ============= Shell Command Execution =============

async def execute_shell_command(command: str):
    """Execute a shell command and display output"""
    try:
        # Remove the leading '!' and strip whitespace
        shell_cmd = command[1:].strip()
        
        if not shell_cmd:
            print_error("No command provided")
            return
        
        console.print(f"\n[bold cyan]⚡ Executing:[/bold cyan] [yellow]{shell_cmd}[/yellow]\n")
        
        # Execute the command
        process = await asyncio.create_subprocess_shell(
            shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            shell=True
        )
        
        stdout, stderr = await process.communicate()
        
        # Display output
        if stdout:
            output = stdout.decode('utf-8', errors='replace')
            console.print(Panel(
                output.rstrip(),
                title="📤 Output",
                border_style="green",
                box=box.ROUNDED
            ))
        
        if stderr:
            error = stderr.decode('utf-8', errors='replace')
            console.print(Panel(
                error.rstrip(),
                title="⚠️ Error Output",
                border_style="yellow",
                box=box.ROUNDED
            ))
        
        # Show return code if non-zero
        if process.returncode != 0:
            console.print(f"\n[yellow]⚠️  Exit code: {process.returncode}[/yellow]")
        
    except Exception as e:
        print_error(f"Failed to execute command: {str(e)}")

# ============= Interactive Selection =============

async def select_from_list(items: List[dict], title: str, name_key: str = 'name') -> Optional[dict]:
    """Interactive selection using arrow keys"""
    if not items:
        return None
    
    # Create choices for questionary
    choices = []
    for item in items:
        name = item.get(name_key, 'Unknown')
        desc = item.get('description', '')
        
        # Format the choice text
        if desc:
            # Truncate description if too long
            if len(desc) > 60:
                desc = desc[:57] + "..."
            choice_text = f"{name} - {desc}"
        else:
            choice_text = name
        
        choices.append(questionary.Choice(
            title=choice_text,
            value=item
        ))
    
    # Use questionary select ASYNC for arrow-key navigation
    result = await questionary.select(
        title,
        choices=choices,
        use_arrow_keys=True,
        instruction="(Use arrow keys to navigate, Enter to select)"
    ).ask_async()
    
    return result

async def confirm_action(title: str, text: str = "") -> bool:
    """Confirm action using questionary"""
    message = f"{title}: {text}" if text else title
    return await questionary.confirm(message, default=False).ask_async()

async def get_input_with_history(prompt_text: str) -> str:
    """Get user input with arrow key history navigation"""
    global history_index
    
    # Reset history index
    history_index = len(message_history)
    
    # Use questionary for input with better arrow key support
    try:
        user_input = await questionary.text(
            prompt_text,
            qmark="",
            style=questionary.Style([
                ('question', 'bold fg:green'),
                ('answer', 'fg:white'),
            ])
        ).ask_async()
        
        if user_input and user_input.strip():
            # Add to history if not duplicate of last entry
            if not message_history or message_history[-1] != user_input.strip():
                message_history.append(user_input.strip())
            return user_input.strip()
        
        return ""
    except (KeyboardInterrupt, EOFError):
        raise

# ============= Command Handlers =============

async def handle_config():
    console.print("\n[bold cyan]⚙️ Chat Configuration[/bold cyan]\n")

    provider = await questionary.select(
        "Select provider",
        choices=["openai", "anthropic", "google", "ollama"],
        default=CHAT_CONFIG.provider_name
    ).ask_async()

    model = await questionary.text(
        "Model name",
        default=CHAT_CONFIG.model
    ).ask_async()

    mode = await questionary.select(
        "Mode",
        choices=["default", "dynamic", "code-mode"],
        default=CHAT_CONFIG.mode
    ).ask_async()

    max_iterations = await questionary.text(
        "Max iterations",
        default=str(CHAT_CONFIG.max_iterations),
        validate=lambda x: x.isdigit() and int(x) > 0
    ).ask_async()

    verbose = await questionary.confirm(
        "Verbose logging?",
        default=CHAT_CONFIG.verbose
    ).ask_async()

    CHAT_CONFIG.provider_name = provider
    CHAT_CONFIG.model = model
    CHAT_CONFIG.mode = mode
    CHAT_CONFIG.max_iterations = int(max_iterations)
    CHAT_CONFIG.verbose = verbose

    print_success("Chat configuration updated")

    console.print(
        Panel(
            Syntax(
                json.dumps(asdict(CHAT_CONFIG), indent=2),
                "json",
                theme="monokai",
                line_numbers=False,
            ),
            title="Current Chat Config",
            border_style="cyan"
        )
    )

async def handle_add(client: MCPGatewayClient):
    """Add server workflow"""
    from src.configs_secrets import hil_configs, handle_secrets_interactive
    
    console.print("\n[bold cyan]🔍 Searching for servers...[/bold cyan]")
    query = Prompt.ask("Search query (or press Enter for all)", default="")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Searching...", total=None)
        servers = await client.find_servers(query or "mcp")
    
    if not servers:
        print_error("No servers found")
        return
    
    print_success(f"Found {len(servers)} servers")
    
    # Interactive selection
    server = await select_from_list(servers, "Select Server to Add")
    
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
    
    if not await confirm_action("Confirm", f"Add '{server_name}'?"):
        print_info("Cancelled")
        return
    
    # Configure
    if needs_config:
        config_server, config_keys, config_values = hil_configs(server)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Configuring...", total=None)
            await client.set_configs(config_server, dict(zip(config_keys, config_values)))
    
    if needs_secrets:
        handle_secrets_interactive(server)
    
    # Add server
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Adding server...", total=None)
        result = await client.add_server(server_name, activate=True)
    
    if result:
        print_success(f"🎉 '{server_name}' added successfully!")
        await client.list_tools()
    else:
        print_error(f"Failed to add '{server_name}'")

async def handle_find(client: MCPGatewayClient, query: str):
    """Search servers"""
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task(f"Searching for '{query}'...", total=None)
        servers = await client.find_servers(query)
    
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
    console.print()  # Add spacing
    
    # Directly select server with arrow keys
    server = await select_from_list(servers, "Select a server to add")
    if server:
        await handle_add_selected(client, server)
    else:
        print_error("Server selection cancelled")

async def handle_add_selected(client: MCPGatewayClient, server: dict):
    """Add a pre-selected server"""
    from src.configs_secrets import hil_configs, handle_secrets_interactive
    
    server_name = server['name']
    
    # Check requirements
    needs_config = 'config_schema' in server
    needs_secrets = 'required_secrets' in server
    
    # Configure
    if needs_config:
        config_server, config_keys, config_values = hil_configs(server)
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            task = progress.add_task("Configuring...", total=None)
            await client.set_configs(config_server, dict(zip(config_keys, config_values)))
    
    if needs_secrets:
        handle_secrets_interactive(server)
    
    # Add server
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Adding server...", total=None)
        result = await client.add_server(server_name, activate=True)
    
    if result:
        print_success(f"🎉 '{server_name}' added!")
        await client.list_tools()
    else:
        print_error(f"Failed to add '{server_name}'")

async def handle_list(client: MCPGatewayClient):
    """List servers and tools"""
    console.print("\n[bold cyan]📊 Current Status[/bold cyan]\n")
    
    # Get active servers from state
    active_servers = [
        name for name, data in client.state.servers.items() 
        if data['status'] == 'active'
    ]
    
    # Active servers
    if active_servers:
        console.print("[bold green]Active Servers:[/bold green]")
        for server in active_servers:
            console.print(f"  • {server}")
    else:
        console.print("[dim]No active servers[/dim]")
    
    console.print()
    
    # Tools from state
    tools = list(client.state.tools.values())
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

async def handle_remove(client: MCPGatewayClient):
    """Remove server"""
    # Get active servers from state
    active_servers = [
        name for name, data in client.state.servers.items() 
        if data['status'] == 'active'
    ]
    
    if not active_servers:
        print_error("No active servers to remove")
        return
    
    # Create list for selection
    server_list = [{'name': s, 'description': ''} for s in active_servers]
    server = await select_from_list(server_list, "Select Server to Remove")
    
    if not server:
        print_info("Cancelled")
        return
    
    server_name = server['name']
    
    if not await confirm_action("Confirm Removal", f"Remove '{server_name}'?\nAll its tools will be removed."):
        print_info("Cancelled")
        return
    
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
        task = progress.add_task("Removing...", total=None)
        result = await client.remove_server(server_name)
    
    if result:
        print_success(f"Removed '{server_name}'")
    else:
        print_error(f"Failed to remove '{server_name}'")

async def handle_chat(client: MCPGatewayClient, message: str):
    console.print(
        Panel(
            message,
            title="🧑 You",
            border_style="blue",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    try:
        result = await cli_chat_llm(
            console,
            client=client,
            provider_name=CHAT_CONFIG.provider_name,
            user_message=message,
            model=CHAT_CONFIG.model,
            mode=CHAT_CONFIG.mode,
            max_iterations=CHAT_CONFIG.max_iterations,
            verbose=CHAT_CONFIG.verbose
        )

        if result.get('content'):
            print_chat_response(result['content'])

        if result.get('active_servers'):
            console.print(f"\n[dim]Active: {', '.join(result['active_servers'])}[/dim]")

    except Exception as e:
        print_error(f"Error: {str(e)}")

# ============= Main Chat Loop =============

async def chat_loop():
    """Main interactive chat loop"""
    print_welcome()
    
    # Initialize catalog and state
    catalog = MCPCatalogManager("catalog")
    catalog.load_catalog()
    
    state = MCPStateManager(catalog)
    
    async with MCPGatewayClient(catalog, state, verbose=CHAT_CONFIG.verbose) as client:
        with Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold cyan]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("🔌 Connecting to MCP Gateway", total=None)
            await client.list_tools()
            progress.update(task, description="📦 Loading tools")
        
        # Main loop
        while True:
            try:
                # Get input with history support
                user_input = await get_input_with_history(
                    "You ›"
                )
                
                if not user_input:
                    continue
                
                # Handle shell commands
                if user_input.startswith('!'):
                    await execute_shell_command(user_input)
                    continue
                
                # Handle commands
                if user_input.startswith('/'):
                    parts = user_input.split(maxsplit=1)
                    cmd = parts[0].lower()
                    args = parts[1] if len(parts) > 1 else ""
                    
                    if cmd == '/exit' or cmd == '/quit':
                        if await confirm_action("Exit", "Are you sure?"):
                            print_info("Goodbye! 👋")
                            break
                    
                    elif cmd == '/help':
                        print_help()
                    
                    elif cmd == '/add':
                        await handle_add(client)
                    
                    elif cmd == '/find':
                        if not args:
                            args = Prompt.ask("Search query")
                        await handle_find(client, args)
                    
                    elif cmd == '/list':
                        await handle_list(client)
                    
                    elif cmd == '/remove':
                        await handle_remove(client)
                    
                    elif cmd == '/config':
                        await handle_config()
                    
                    else:
                        print_error(f"Unknown command: {cmd}")
                        print_info("Type /help to see available commands")
                
                else:
                    # Regular chat
                    await handle_chat(client, user_input)
            
            except KeyboardInterrupt:
                console.print()
                if await confirm_action("Exit", "Exit the chat?"):
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