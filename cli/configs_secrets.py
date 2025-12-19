import subprocess
import getpass
from typing import List, Dict
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.rule import Rule

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
    console.print()
    console.print(f"[bold]🔑 Secret[/bold]  [cyan]{secret_key}[/cyan]")
    console.print("[dim]Value will not be shown while typing[/dim]")

    secret_value = getpass.getpass("› ")

    if not secret_value.strip():
        console.print(f"[yellow]⚠ Skipped empty value[/yellow]")
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
            console.print(f"[green]✓ Saved[/green]")
            return True
        else:
            error_msg = result.stderr.decode() if result.stderr else "Unknown error"
            console.print(f"[red]✗ Failed[/red] [dim]{error_msg}[/dim]")
            return False

    except subprocess.TimeoutExpired:
        console.print(f"[red]✗ Timeout[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Error[/red] [dim]{str(e)}[/dim]")
        return False


def prompt_manual_secret_setup(server_name: str, secret_keys: List[str]):
    console.print()
    console.print(Rule("[bold yellow]Manual Secret Setup"))
    console.print(f"[bold]Server:[/bold] [cyan]{server_name}[/cyan]\n")

    console.print("[bold]Run the following commands:[/bold]\n")

    for key in secret_keys:
        console.print(f"  [dim]docker mcp secret set {server_name}/{key}[/dim]")

    console.print("\n[dim]Press Enter once finished[/dim]")

from rich.rule import Rule

def handle_secrets_interactive(server: Dict):
    """
    Handle secret configuration interactively.
    Returns True if user chooses to continue / secrets configured.
    """
    if not server.get("required_secrets"):
        return True  # No secrets needed

    server_name = server["name"]
    required_secrets = server["required_secrets"]

    console.print()
    console.print(Rule("[bold yellow]Secrets Required"))
    console.print(f"[bold]Server:[/bold] [cyan]{server_name}[/cyan]")
    console.print(f"[bold]Secrets:[/bold] {', '.join(required_secrets)}\n")

    console.print("[bold]Choose how to proceed:[/bold]")
    console.print("  [cyan]1[/cyan] Interactive — enter secret values now")
    console.print("  [cyan]2[/cyan] Manual — I will run docker commands myself")
    console.print("  [cyan]3[/cyan] Skip — configure later\n")

    choice = Prompt.ask("›", choices=["1", "2", "3"], default="1")

    if choice == "1":
        console.print("\n[bold cyan]Interactive secret setup[/bold cyan]\n")

        success_count = 0

        for secret_key in required_secrets:
            if set_docker_secret_interactive(server_name, secret_key):
                success_count += 1
            else:
                console.print(f"[yellow]⚠ Secret not set:[/yellow] {secret_key}")
                if Confirm.ask("Retry?", default=True):
                    if set_docker_secret_interactive(server_name, secret_key):
                        success_count += 1

        if success_count == len(required_secrets):
            console.print(f"\n[green]✓ All secrets configured successfully[/green]")
            return True

        console.print(
            f"\n[yellow]⚠ Configured {success_count}/{len(required_secrets)} secrets[/yellow]"
        )
        return Confirm.ask("Continue anyway?", default=False)

    if choice == "2":
        console.print()
        console.print(Rule("[bold cyan]Manual Secret Setup"))
        console.print(f"[bold]Server:[/bold] [cyan]{server_name}[/cyan]\n")

        console.print("[bold]Run the following commands:[/bold]\n")
        for key in required_secrets:
            console.print(f"  [dim]docker mcp secret set {server_name}/{key}[/dim]")

        Prompt.ask("\n[dim]Press Enter once finished[/dim]", default="")
        console.print("[green]✓ Continuing[/green]\n")
        return True

    console.print(
        "\n[yellow]⚠ Secrets were not configured. "
        "This server may not function correctly.[/yellow]"
    )
    return Confirm.ask("Continue anyway?", default=False)

    
def hil_configs(server: Dict):
    config_schema = server["config_schema"][0]

    console.print()
    console.print(Rule("[bold cyan]Configuration Required"))
    console.print(f"[dim]{config_schema.get('description', '')}[/dim]\n")

    config_server_name = config_schema["name"]
    config_keys = list(config_schema["properties"].keys())
    required_keys = config_schema.get("required", [])

    console.print(f"[bold]Required:[/bold] {required_keys}")
    console.print(f"[dim]Optional:[/dim] {[k for k in config_keys if k not in required_keys]}\n")

    config_values = []

    for key in config_keys:
        prop = config_schema["properties"][key]
        label = f"{key}"
        if prop.get("description"):
            label += f" — {prop['description']}"

        if key in required_keys:
            value = Prompt.ask(f"[yellow]*[/yellow] {label}")
            while not value.strip():
                console.print(f"[red]Required[/red]")
                value = Prompt.ask(f"[yellow]*[/yellow] {label}")
        else:
            value = Prompt.ask(f"  {label}", default="")

        config_values.append(value)

    return config_server_name, config_keys, config_values
