from mcp_host import MCPGatewayClient
from configs_secrets import hil_configs, handle_secrets_interactive
import httpx
import asyncio
import json
script = """
const fib = (n) => {
    if (n <= 1) return n;
    let a = 0, b = 1;
    for (let i = 2; i <= n; i++) {
        [a, b] = [b, a + b];
    }
    return b;
};

const sequence = [];
for (let i = 0; i < 10; i++) {
    sequence.push(fib(i));
}

return JSON.stringify({
    fibonacci_sequence: sequence,
    fib_20: fib(20)
}, null, 2);
"""
async def dynamic_mcp_test():
    mcp = MCPGatewayClient()
    async with httpx.AsyncClient(timeout=300) as client:
        # Initialize
        await mcp.initialize(client)
        tools_list = await mcp.list_tools(client)
        print("\n===Tools List===\n")
        print(tools_list)
        # exit(0)

        # Find Servers
        query = input("Enter search query for MCP servers: ").strip() or "github"
        servers = await mcp.find_mcp_servers(client=client, query=query)

        print("\n=== Servers Found ===\n")
        if not servers:
            print("No relevant MCP server found!")
            return
        
        final_server = None
        if len(servers) == 1:
            final_server = servers[0]
            print(f"Found 1 server: {final_server['name']}")
            print(f"Description: {final_server.get('description', 'N/A')}")
        else:
            for i, server in enumerate(servers):
                has_config = '✓ config' if 'config_schema' in server else ''
                has_secrets = '✓ secrets' if 'required_secrets' in server else ''
                badges = ' '.join([has_config, has_secrets]).strip()
                
                print(f"{i+1}. {server['name']} {f'({badges})' if badges else ''}")
                print(f"   {server.get('description', 'No description')[:100]}...")
            
            server_index = int(input("\nEnter the server number: ")) - 1
            if server_index not in range(len(servers)):
                raise ValueError("Invalid server selection")
            final_server = servers[server_index]
        
        final_server_name = final_server['name']
        print(f"\n✓ Selected server: {final_server_name}")

        # Handle config schema
        if 'config_schema' in final_server:
            config_server, config_keys, config_values = hil_configs(final_server)
            await mcp.add_mcp_configs(
                client=client, 
                server=config_server, 
                keys=config_keys, 
                values=config_values
            )
            print("✓ Configuration completed")
        
        # Handle required secrets
        if 'required_secrets' in final_server:
            secrets_configured = handle_secrets_interactive(final_server)
            
            if not secrets_configured:
                print("\n⚠️  Warning: Proceeding without proper secret configuration")
                proceed = input("Continue adding server? (y/n): ").strip().lower()
                if proceed != 'y':
                    print("Aborted.")
                    return
        
        # Add the MCP server
        print(f"\nAdding server '{final_server_name}'...")
        add_mcp_result = await mcp.add_mcp_servers(
            client=client, 
            server_name=final_server_name, 
            activate=True
        )
        await asyncio.sleep(2)

        print("\n=== Add Server Result ===")
        print(json.dumps(add_mcp_result, indent=2))
        
        print(f"\n✓ Server '{final_server_name}' successfully added and activated!")

        tools = await mcp.list_tools(client)
        print("\n===Printing initial tools output===\n")
        print(tools)
        exit(0)
        

        create_result = await mcp.create_dynamic_code_tool(
            client=client,
            code='',
            name="wiki-test",
            servers=[final_server_name],
            timeout=30
        )   # This creates a text (.md) result of tool descriptions available in the mcp server as a reference for the LLM
        print("\n=== Create Tool Result ===")
        print(create_result)
        tool_name = create_result["tool_name"]

        result = await mcp.execute_dynamic_code_tool(
            client=client,
            tool_name=tool_name,
            script=script
        )
        
        print("\n=== RUNNING JS CODE ===")
        content_text = result['content'][0]['text']
        
        try:
            parsed = json.loads(content_text)
            print(json.dumps(parsed, indent=2))
        except:
            print(content_text)
        # finally:
        #     await mcp.remove_mcp_servers(client=client, server_name=server_name)


if __name__ == "__main__":
    asyncio.run(dynamic_mcp_test())