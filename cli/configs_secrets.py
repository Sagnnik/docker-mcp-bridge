import subprocess
import getpass
from typing import List, Dict
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()

def parse_secret_key(secret_full_key: str):
    """
    Parse a secret key like 'github.personal_access_token' 
    Returns (server_prefix, secret_name)
    """
    parts = secret_full_key.split('.', 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return secret_full_key, secret_full_key

def set_docker_secret_interactive(server_name: str, secret_key: str):
    """
    Prompt user to enter a secret value and set it via docker CLI
    """
    console.print(f"\n{'─'*60}")
    console.print(f"🔑 Secret: [cyan]{secret_key}[/cyan]")
    console.print(f"{'─'*60}")

    secret_value = getpass.getpass(f"Enter value for '{secret_key}' (input hidden): ")
    if not secret_value.strip():
        console.print(f"[yellow]⚠️  Skipping empty secret '{secret_key}'[/yellow]")
        return False
    
    try:
        result = subprocess.run(
            ['docker', 'mcp', 'secret', 'set', f'{server_name}/{secret_key}'],
            input=secret_value.encode(),
            capture_output=True,
            timeout=30,
            text=False
        )

        if result.returncode == 0:
            console.print(f"[green]✓ Secret '{secret_key}' set successfully[/green]")
            return True
        else:
            error_msg = result.stderr.decode() if result.stderr else "Unknown error"
            console.print(f"[red]✗ Failed to set secret '{secret_key}': {error_msg}[/red]")
            return False
        
    except subprocess.TimeoutExpired:
        console.print(f"[red]✗ Timeout while setting secret '{secret_key}'[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Unexpected error: {str(e)}[/red]")
        return False

def prompt_manual_secret_setup(server_name: str, secret_keys: List[str]):
    """
    Show instructions for manual secret setup via CLI
    """
    console.print(f"\n{'='*70}")
    console.print("[bold]🔐 SECRET CONFIGURATION REQUIRED[/bold]")
    console.print(f"{'='*70}")
    console.print(f"\nServer: [cyan]{server_name}[/cyan]")
    console.print("\n[bold]Run these commands in your terminal:[/bold]\n")
    
    for secret_key in secret_keys:
        console.print(f"  [dim]docker mcp secret set {server_name}/{secret_key}[/dim]")
    
    console.print(f"\n{'='*70}")

def handle_secrets_interactive(server: Dict):
    """
    Handle secret configuration interactively
    Returns True if secrets were configured successfully
    """
    if 'required_secrets' not in server or not server['required_secrets']:
        return True  # No secrets needed
    
    server_name = server['name']
    required_secrets = server['required_secrets']

    console.print(f"\n{'='*70}")
    console.print(f"[bold]🔐 Server '{server_name}' requires secret configuration[/bold]")
    console.print(f"{'='*70}")
    console.print(f"\n[yellow]Required secrets:[/yellow] {', '.join(required_secrets)}")

    console.print("\n[bold]How would you like to configure secrets?[/bold]")
    console.print("  [cyan]1.[/cyan] Interactive mode (enter values now)")
    console.print("  [cyan]2.[/cyan] Manual mode (I'll run docker commands myself)")
    console.print("  [cyan]3.[/cyan] Skip (configure later)")

    choice = Prompt.ask("\nEnter choice", choices=["1", "2", "3"], default="1")

    if choice == '1':
        # Interactive mode
        console.print("\n[bold cyan]--- Interactive Secret Configuration ---[/bold cyan]")
        success_count = 0
        
        for secret_key in required_secrets:
            success = set_docker_secret_interactive(server_name, secret_key)
            if success:
                success_count += 1
            else:
                console.print(f"\n[yellow]⚠️  Required secret '{secret_key}' was not set![/yellow]")
                if Confirm.ask("Retry?", default=True):
                    success = set_docker_secret_interactive(server_name, secret_key)
                    if success:
                        success_count += 1
        
        if success_count == len(required_secrets):
            console.print(f"\n[green]✓ All {success_count} required secrets configured successfully[/green]")
            return True
        else:
            console.print(f"\n[yellow]⚠️  Only {success_count}/{len(required_secrets)} secrets were configured[/yellow]")
            return Confirm.ask("Continue anyway?", default=False)
        
    elif choice == '2':
        # Manual mode
        prompt_manual_secret_setup(server_name, required_secrets)
        Prompt.ask("\n[dim]Press Enter after you've configured the secrets[/dim]", default="")
        console.print("[green]✓ Continuing...[/green]\n")
        return True
    
    else:
        # Skip
        console.print("[yellow]⚠️  Skipping secret configuration. Server may not work correctly.[/yellow]")
        return Confirm.ask("Continue anyway?", default=False)
    
def hil_configs(server: Dict):
    """
    Human-in-the-loop for config schema
    Returns (server_name, config_keys, config_values)
    """
    config_schema = server['config_schema'][0]
    console.print(f"\n[bold cyan]--- Configuration Required ---[/bold cyan]")
    console.print(config_schema.get('description', 'No description'))

    config_server_name = config_schema['name']
    config_keys = list(config_schema['properties'].keys())
    required_keys = config_schema.get('required', [])

    console.print(f"\n[yellow]Required properties:[/yellow] {required_keys}")
    console.print(f"[dim]Optional properties:[/dim] {[k for k in config_keys if k not in required_keys]}")

    config_values = []
    for key in config_keys:
        prop_info = config_schema['properties'][key]
        prop_desc = prop_info.get('description', '')
        prop_type = prop_info.get('type', 'string')
        is_required = key in required_keys

        # Build prompt text
        prompt_text = key
        if prop_desc:
            prompt_text = f"{key} ({prop_desc})"
        
        # Use Rich Prompt which handles display better
        if is_required:
            value = Prompt.ask(f"[yellow]✱[/yellow] {prompt_text} [red][REQUIRED][/red]")
            # Validate required fields
            while not value.strip():
                console.print(f"[red]⚠️  '{key}' is required![/red]")
                value = Prompt.ask(f"[yellow]✱[/yellow] {prompt_text} [red][REQUIRED][/red]")
        else:
            value = Prompt.ask(f"  {prompt_text}", default="")
        
        config_values.append(value)

    return config_server_name, config_keys, config_values