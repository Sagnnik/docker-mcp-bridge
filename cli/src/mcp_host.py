import httpx
import json
from typing import Dict, List, Any


class MCPGatewayClient:
    MCP_URL = "http://localhost:8811/mcp"
    MCP_VERSION = "2024-11-05"
    
    def __init__(self, catalog, state, verbose: bool = False):
        self.catalog = catalog
        self.state = state
        self.verbose = verbose
        self._client = None
        self._next_id = 1
    
    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=300)
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
    
    # Core MCP Methods
    
    async def initialize(self):
        """Initialize MCP session"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": self.MCP_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-gateway", "version": "1.0"}
            }
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Protocol-Version": self.MCP_VERSION,
                "Accept": "application/json, text/event-stream"
            }
        )
        response.raise_for_status()
        
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id")
        self.state.set_session_id(session_id)
        
        # Send initialized notification
        await self._client.post(
            self.MCP_URL,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers=self._headers()
        )
    
    async def list_tools(self) -> List[dict]:
        """List all available tools"""
        data = await self._request("tools/list", {})
        tools = data.get('result', {}).get('tools', [])
        self.state.sync_tools(tools)
        return tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> dict:
        """Call an MCP tool"""
        if not self.state.has_tool(name):
            raise ValueError(f"Tool {name} not found")
        
        data = await self._request("tools/call", {
            "name": name,
            "arguments": arguments
        })
        
        if 'error' in data:
            server = self.state.get_tool_server(name)
            if server:
                self.state.set_server_error(server, str(data['error']))
            raise RuntimeError(f"MCP error: {data['error']}")
        
        return data['result']
    
    # Server Management
    
    async def find_servers(self, query: str) -> List[dict]:
        """Find MCP servers (with catalog fallback)"""
        try:
            result = await self.call_tool("mcp-find", {"query": query})
            result = json.loads(result['content'][0]['text'])
            servers = result['servers']
            
            # Enrich with catalog data
            for server in servers:
                name = server.get('name')
                catalog_data = self.catalog.get_server(name)
                if catalog_data:
                    server['title'] = catalog_data.get('title', name)
                    server['tools'] = catalog_data.get('tools', [])
            
            return servers
            
        except Exception as e:
            if self.verbose:
                print(f"mcp-find failed: {e}, using catalog")
            return self.catalog.search(query)
    
    async def add_server(self, name: str, activate: bool = True) -> dict:
        """Add and optionally activate a server"""
        self.state.add_server(name, activate=False)
        
        try:
            result = await self.call_tool("mcp-add", {
                "name": name,
                "activate": activate
            })
            
            if result.get('content'):
                self.state.activate_server(name)
                await self.list_tools()
            else:
                self.state.set_server_error(name, "Failed to activate")
            
            return result
            
        except Exception as e:
            self.state.set_server_error(name, str(e))
            raise
    
    async def remove_server(self, name: str) -> dict:
        """Remove a server"""
        result = await self.call_tool("mcp-remove", {"name": name})
        
        if result.get('content'):
            self.state.remove_server(name)
            await self.list_tools()
        
        return result
    
    async def set_config(self, server: str, key: str, value: Any) -> dict:
        """Set a configuration value for a server"""
        result = await self.call_tool("mcp-config-set", {
            "server": server,
            "key": key,
            "value": value
        })
        self.state.update_server_config(server, key, value)
        return result
    
    async def set_configs(self, server: str, configs: Dict[str, Any]) -> List[dict]:
        """Set multiple configs for a server"""
        results = []
        for key, value in configs.items():
            result = await self.set_config(server, key, value)
            results.append(result)
        return results
    
    # Code Mode (Dynamic Tools)
    
    async def create_code_tool(self, name: str, servers: List[str], timeout: int = 30) -> str:
        """Create a dynamic code-mode tool"""
        if not servers:
            raise ValueError("At least one server required")
        
        await self.call_tool("code-mode", {
            "code": '',
            "name": name,
            "servers": servers,
            "timeout": timeout
        })
        
        tool_name = f"code-mode-{name}"
        await self.list_tools()
        return tool_name
    
    async def exec_code_tool(self, tool_name: str, script: str) -> dict:
        """Execute a code-mode tool"""
        result = await self.call_tool("mcp-exec", {
            "name": tool_name,
            "arguments": {"script": script}
        })
        return result
    
    # Internal helpers
    
    async def _request(self, method: str, params: dict) -> dict:
        """Make MCP JSON-RPC request"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers=self._headers()
        )
        response.raise_for_status()
        return self._parse_response(response.text)
    
    def _headers(self) -> dict:
        """Build request headers"""
        headers = {
            "Mcp-Protocol-Version": self.MCP_VERSION,
            "Accept": "application/json, text/event-stream"
        }
        if self.state.session_id:
            headers["Mcp-Session-Id"] = self.state.session_id
        return headers
    
    def _parse_response(self, content: str) -> dict:
        """Parse SSE or JSON response"""
        if not content:
            return {}
        
        # Try SSE format
        for line in content.strip().split("\n"):
            if line.startswith("data: "):
                try:
                    return json.loads(line[6:])
                except:
                    pass
        
        # Try plain JSON
        try:
            return json.loads(content)
        except:
            return {"error": "Failed to parse response"}