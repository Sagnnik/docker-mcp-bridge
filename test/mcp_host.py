import httpx
import json
import asyncio
from typing import Optional, List, Dict, Any
from utils import parse_sse_json, extract_text_from_content
from provider import LLMProviderFactory
from prompts import MCP_BRIDGE_MESSAGES
from configs_secrets import hil_configs, handle_secrets_interactive

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_URL = "http://localhost:8811/mcp"

def handle_mcp_find(servers):
    """
    Handle mcp-find
    - if it returns only one server auto add it
    - if it returns multiple servers another let the user choose it
    - let user input configs and secrets interactively using cli
    """
    additional_info = ""
    print("\n=== Servers Found ===\n")
    if not servers:
        print("No relevant MCP server found!")
        additional_info = "No relevant MCP server found!"
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
        
    return final_server, additional_info

class MCPGatewayClient:
    def __init__(self):
        self.gateway_url = MCP_URL
        self.session_id:Optional[str]=None
        self._next_id = 1
        self.dynamic_tools_enabled = False
        self.code_mode_enabled = False
        self.active_servers: List[str] = []
        self.available_tools: Dict[str, Dict] = {}

    async def initialize(self, client: httpx.AsyncClient):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "gpt-mcp-bridge",
                    "version": "1.0.0"
                }
            }
        }
        self._next_id+=1
        try:
            response = await client.post(
                url=self.gateway_url,
                json=payload,
                headers={
                    "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
                    "Accept": "application/json, text/event-stream",
                }
            )
            response.raise_for_status()
            self.session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
            data = parse_sse_json(response.text)
            if not data:
                raise RuntimeError(f"Invalid initialize response: {response.text}")
            
            notif_payload = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            notif_headers = {
                "Mcp-Session-Id": self.session_id,
                "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
            }
            notif_response = await client.post(
                url=self.gateway_url,
                json=notif_payload,
                headers=notif_headers
            )
            notif_response.raise_for_status()

            return data
        except Exception as e:
            print(f"Error connecting to MCP Gateway: {str(e)}")
    
    async def list_tools(self, client: httpx.AsyncClient):
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
            "params": {}
        }
        self._next_id+=1
        headers = {
            "Mcp-Session-Id": self.session_id,
            "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Accept": "application/json, text/event-stream",
        }
        try:
            response = await client.post(
                url=self.gateway_url,
                json=payload,
                headers=headers
            )
            data = parse_sse_json(response.text)
            if "error" in data:
                raise RuntimeError(f"MCP tools/list error: {data['error']}")
            
            tools = data.get('result').get('tools')
            # tools = data.get('result')
            # return tools
            for tool in tools:
                self.available_tools[tool["name"]] = tool

            #print(f"Loaded {len(self.available_tools)} tools from MCP Gateway")

            if "mcp-find" in self.available_tools and 'mcp-add' in self.available_tools and 'mcp-remove' in self.available_tools:
                self.dynamic_tools_enabled = True
                #print("Docker Dynamic Tools (mcp-find, mcp-add, mcp-remove) available")

            if "code-mode" in self.available_tools:
                self.code_mode_enabled = True
                #print("Docker code-mode available")
            
            return tools
        except Exception as e:
            print(f"Error connecting to MCP Gateway: {str(e)}")
    
    async def call_tool(self, client:httpx.AsyncClient, name:str, arguments: Dict[str, Any]):
        if name not in self.available_tools:
            raise ValueError(f"Tool {name} not found")
        
        payload ={
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments
            }
        }
        self._next_id+=1
        headers = {
            "Mcp-Session-Id": self.session_id,
            "Mcp-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Accept": "application/json, text/event-stream",
        }
        try:
            response = await client.post(
                url=self.gateway_url,
                json=payload,
                headers=headers
            )
            data = parse_sse_json(response.text)
            if 'error' in data:
                raise RuntimeError(f"MCP tools/call error: {data['error']}")
            
            return data["result"]
        except Exception as e:
            raise RuntimeError(f"Error calling tool {name}: {e}")
        
    async def find_mcp_servers(self,client: httpx.AsyncClient, query:str, limit:int=5):
        if not self.dynamic_tools_enabled:
            return []
        
        try:
            result = await self.call_tool(client=client, name="mcp-find", arguments={"query": query, "limit":limit})
            result = json.loads(result['content'][0]['text'])
            # return result['servers']
            return result
        except Exception as e:
            print(f"Error finding MCP servers: {e}")
            return []
        
    async def add_mcp_configs(self, client:httpx.AsyncClient, server:str, keys:List[str], values:List[Any]):
        try: 
            results = []
            for i, key in enumerate(keys):
                result = await self.call_tool(client=client, name="mcp-config-set", arguments={"server":server, "key":key, "value": values[i]})
                results.append(result)
            return results
        except Exception as e:
            print(f"Error setting configs using mcp-config-set: {str(e)}")

    async def add_mcp_servers(self, client: httpx.AsyncClient, server_name:str, activate:bool=True):
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-add", arguments={"name": server_name, "activate": activate})
            if result.get('content'):
                if server_name not in self.active_servers:
                    self.active_servers.append(server_name)
                _ = await self.list_tools(client=client)
            return result
        
        except Exception as e:
            print(f"Error adding MCP server {server_name}: {e}")
            return False
        
    async def remove_mcp_servers(self, client: httpx.AsyncClient, server_name: str):
        # this is not working
        if not self.dynamic_tools_enabled:
            return False
        
        try:
            result = await self.call_tool(client=client, name="mcp-remove", arguments={"name": server_name})
            print(f"Remove result: {result}")  # Debug line
            
            if result.get('content'):
                if server_name in self.active_servers:
                    self.active_servers.remove(server_name)
                    print(f"Removed {server_name} from active_servers")  # Debug line
                
                tools = await self.list_tools(client=client)
                print(f"Active servers after removal: {self.active_servers}")  # Debug line
                print(f"Available tools count: {len(self.available_tools)}")  # Debug line
                
            return result
        
        except Exception as e:
            print(f"Error removing MCP server {server_name}: {e}")
            return False
        
    async def create_dynamic_code_tool(self, client: httpx.AsyncClient, code: str, name: str, servers: List[str], timeout: int = 30):
        """This creates a dynamic tool"""
        if not self.code_mode_enabled:
            raise RuntimeError("Code mode not available in gateway")
        if not servers or len(servers) == 0:
            raise ValueError("At least one server must be provided for code-mode")
        
        arguments = {
            "code": code,
            "name": name,
            "servers": servers,  
            "timeout": timeout
        }
        
        try:
            result = await self.call_tool(
                client=client, 
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
        
    async def execute_dynamic_code_tool(self, client: httpx.AsyncClient, tool_name: str, script:str):
        """Execute the created tool"""
        try:
            result = await self.call_tool(
                client=client,
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
        
    async def chat_with_llm(
            self,
            provider_name: str, 
            user_message: str,
            model:str,
            initial_servers: List[str],
            mode:str = "dynamic",
            system_message: Optional[str]="",
            max_iterations: int=5,
            enable_dynamic_tools: bool=True,
            enable_code_mode: bool = False
    ):
        provider = LLMProviderFactory.get_provider(provider_name)

        async with httpx.AsyncClient(timeout=300) as client:
            # Initialize
            await self.initialize(client)

            # Load with initial servers requested
            if initial_servers:
                for server in initial_servers:
                    print(f"Adding initial server: {server}")
                    await self.add_mcp_servers(client, server)

            mcp_tools = await self.list_tools(client)
            messages = [
                {
                    "role": "system",
                    "content": system_message+MCP_BRIDGE_MESSAGES.get(mode)
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]

            for iteration in range(max_iterations):
                response, assistant_message, finish_reason = await provider.chat(
                    messages=messages,
                    model=model,
                    tools=mcp_tools,
                    mode=mode
                )

                messages.append(assistant_message)
                
                if finish_reason == 'stop':
                    return {
                        "content": assistant_message.get('content'),
                        "active_servers": self.active_servers,
                        "available_tools": list(self.available_tools.keys()),
                        "full_response": response
                    }
                
                if finish_reason == "tool_calls" and assistant_message.get('tool_calls'):
                    tool_calls = assistant_message['tool_calls']
                    print(f"\n==== Iteration {iteration+1}/{max_iterations} ==== Processing {len(tool_calls)} tool calls ====\n")
                    tools_changed = False

                    for tc in tool_calls:
                        tool_name = tc['function']['name']
                        tool_args = json.loads(tc['function']['arguments'])
                        tool_call_id = tc['id']

                        print(f"Calling tool: {tool_name} with args: {tool_args}")

                        try:
                            if tool_name == "mcp-find":
                                servers = await self.find_mcp_servers(client, tool_args.get('query'))
                                final_server, additional_info = handle_mcp_find(servers)
                                if not final_server:
                                    print(additional_info)
                                    continue

                                # Handle config schema
                                if 'config_schema' in final_server:
                                    config_server, config_keys, config_values = hil_configs(final_server)
                                    await self.add_mcp_configs(
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
                                            exit(0)

                                # Add the MCP server
                                if mode in ['dynamic', 'default']:
                                    activate=True
                                elif mode == 'code':
                                    activate=False
                                final_server_name = final_server['name']
                                print(f"\nAdding server '{final_server_name}'...")
                                add_mcp_result = await self.add_mcp_servers(
                                    client=client, 
                                    server_name=final_server_name, 
                                    activate=activate
                                )
                                await asyncio.sleep(1)
                                stringified_add_mcp_result = json.dumps(add_mcp_result)

                                print("\n=== Add Server Result ===")
                                print(json.dumps(add_mcp_result, indent=2))
                                if stringified_add_mcp_result.startswith("Successfully"):
                                    add_status = "success"
                                elif stringified_add_mcp_result.startswith("Error"):
                                    add_status = "failed"
                                else:
                                    add_status = "undefined"
                                
                                print(f"\n✓ Server '{final_server_name}' successfully added and activated!")
                                tools_changed = True

                                result_text = additional_info + json.dumps(
                                    {
                                        "server": final_server, 
                                        "status": add_status,
                                        "message": stringified_add_mcp_result
                                    }
                                )
                            
                            # Handle code-mode - create a custom tool code-mode-{name}
                            elif tool_name == "code-mode":
                                result = await self.create_dynamic_code_tool(
                                    client,
                                    code='',
                                    name=tool_args.get('name'),
                                    servers=tool_args.get('servers'),
                                    timeout=tool_args.get('timeout', 30)
                                )

                                tools_changed = True
                                result_text = json.dumps(result)

                            # Handle mcp-exec - Runs the generated script
                            elif tool_name == "mcp-exec":
                                exec_tool_name = tool_args.get('name')
                                exec_arguments = tool_args.get('arguments', {})
                                script = exec_arguments.get('script', '')

                                print("\n=== Code to be Executed ===\n")
                                print(script if script else "No script provided")

                                exec_result = await self.execute_dynamic_code_tool(
                                    client,
                                    tool_name=exec_tool_name,
                                    script=script
                                )
                                if isinstance(exec_result, dict) and 'content' in exec_result:
                                    result_text = extract_text_from_content(exec_result['content'])
                                else:
                                    result_text = json.dumps(exec_result)

                            else:
                                # Regular MCP tool call
                                tool_result = await self.call_tool(
                                    client=client, 
                                    name=tool_name, 
                                    arguments=tool_args
                                )
                                
                                if isinstance(tool_result, dict) and 'content' in tool_result:
                                    result_text = extract_text_from_content(tool_result['content'])
                                else:
                                    result_text = json.dumps(tool_result)

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
                            print(error_msg)
                            messages.append({
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": tool_name,
                                "content": error_msg
                            })

                    if tools_changed:
                        print("Tools changed, refreshing tool list...")
                        mcp_tools = await self.list_tools(client)
                        print(f"Now have {len(mcp_tools)} tools available")

                    continue
                # Unexpected finish reason
                print(f"Unexpected finish_reason: {finish_reason}")
                break

            return {
                "content": "Maximum iterations reached without completion",
                "messages": messages,
                "active_servers": self.active_servers,
                "available_tools": list(self.available_tools.keys()),
                "full_response": response
            }