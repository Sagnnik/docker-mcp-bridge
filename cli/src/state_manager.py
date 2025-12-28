import json
from pathlib import Path
from typing import Dict, List, Optional
from src.mcp_catalog import MCPCatalogManager

class MCPStateManager:
    """Tracks active servers, tools, and session state"""
    
    def __init__(self, catalog: MCPCatalogManager = None):
        self.catalog = catalog
        self.session_id: Optional[str] = None
        
        # Server state: {name: {status, config, tools, error}}
        self.servers: Dict[str, dict] = {}
        
        # Tool registry: {tool_name: {description, schema, server}}
        self.tools: Dict[str, dict] = {}
        
        # Fast tool->server lookup
        self.tool_to_server: Dict[str, str] = {}
    
    # Session
    def set_session_id(self, session_id: str):
        self.session_id = session_id
    
    def get_session_id(self) -> str:
        return self.session_id
    
    # Servers
    def add_server(self, name: str, activate: bool = False):
        """Add a server to state"""
        if name not in self.servers:
            self.servers[name] = {
                'status': 'active' if activate else 'inactive',
                'config': {},
                'tools': [],
                'error': None
            }
        elif activate:
            self.servers[name]['status'] = 'active'
            self.servers[name]['error'] = None
    
    def remove_server(self, name: str):
        """Remove server and its tools"""
        if name in self.servers:
            # Remove associated tools
            for tool in list(self.servers[name]['tools']):
                self.remove_tool(tool)
            del self.servers[name]
    
    def set_server_error(self, name: str, error: str):
        """Mark server as errored"""
        if name in self.servers:
            self.servers[name]['status'] = 'error'
            self.servers[name]['error'] = error
    
    def update_server_config(self, name: str, key: str, value):
        """Update server configuration"""
        if name in self.servers:
            self.servers[name]['config'][key] = value
    
    def activate_server(self, name: str):
        """Mark server as active"""
        if name in self.servers:
            self.servers[name]['status'] = 'active'
            self.servers[name]['error'] = None
    
    def get_server(self, name: str) -> Optional[dict]:
        """Get server state"""
        return self.servers.get(name)
    
    # Tools
    def add_tool(self, name: str, description: str, schema: dict, server: str = None):
        """Add a tool to registry"""
        self.tools[name] = {
            'name': name,
            'description': description,
            'schema': schema,
            'server': server
        }
        
        if server:
            self.tool_to_server[name] = server
            if server in self.servers:
                if name not in self.servers[server]['tools']:
                    self.servers[server]['tools'].append(name)
    
    def remove_tool(self, name: str):
        """Remove a tool"""
        if name in self.tools:
            tool = self.tools[name]
            server = tool.get('server')
            
            if server and server in self.servers:
                if name in self.servers[server]['tools']:
                    self.servers[server]['tools'].remove(name)
            
            if name in self.tool_to_server:
                del self.tool_to_server[name]
            
            del self.tools[name]
    
    def has_tool(self, name: str) -> bool:
        """Check if tool exists"""
        return name in self.tools
    
    def get_tool_server(self, tool_name: str) -> Optional[str]:
        """Get server that provides this tool"""
        return self.tool_to_server.get(tool_name)
    
    def sync_tools(self, tools_list: List[dict]):
        """Sync tools from MCP tools/list response"""
        # Clear old tools
        self.tools.clear()
        self.tool_to_server.clear()
        for server in self.servers.values():
            server['tools'].clear()
        
        # Add new tools
        for tool_data in tools_list:
            name = tool_data.get('name')
            description = tool_data.get('description', '')
            schema = tool_data.get('inputSchema', {})
            
            # Try to find server from catalog
            server = None
            if self.catalog:
                server = self.catalog.get_server_by_tool(name)
            
            self.add_tool(name, description, schema, server)
    
    def get_stats(self) -> dict:
        """Get state statistics"""
        return {
            'servers': len(self.servers),
            'active_servers': sum(1 for s in self.servers.values() if s['status'] == 'active'),
            'tools': len(self.tools),
            'has_session': self.session_id is not None
        }