import questionary
async def handle_mcp_find(console, servers, verbose=False):
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
        final_server = await questionary.select(
            "Select a server:",
            choices=choices,
            use_arrow_keys=True
        ).ask_async()
        
        if final_server is None:
            console.print("[red]Server selection cancelled[/red]")
            raise ValueError("Server selection cancelled")

    final_server_name = final_server['name']
    if verbose:
        console.print(f"\n[green]✓ Selected server:[/green] [bold]{final_server_name}[/bold]")
        
    return final_server, additional_info