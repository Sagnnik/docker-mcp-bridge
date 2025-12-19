import httpx
import json
from typing import Optional, List, Dict, Any

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
                self.active_servers.append(server_name)
                await self.list_tools()
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