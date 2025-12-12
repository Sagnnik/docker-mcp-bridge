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
                await mcp.list_tools