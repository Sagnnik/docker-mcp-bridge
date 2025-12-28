import json
from pathlib import Path
from typing import Dict, List, Optional


class MCPCatalogManager:
    def __init__(self, catalog_dir: str = "catalog"):
        self.catalog_dir = Path(catalog_dir)
        self.servers: Dict[str, dict] = {}
        self.tool_to_server: Dict[str, str] = {}
    
    def load_catalog(self) -> int:
        """Load all server JSONs from catalog directory"""
        if not self.catalog_dir.exists():
            return 0
        
        for json_file in self.catalog_dir.glob("*.json"):
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                    name = data['name']
                    self.servers[name] = data
                    for tool in data.get('tools', []):
                        self.tool_to_server[tool] = name
                        
            except Exception as e:
                print(f"Error loading {json_file}: {e}")
        
        return len(self.servers)
    
    def get_server(self, name: str) -> Optional[dict]:
        """Get server data by name"""
        return self.servers.get(name)
    
    def get_server_by_tool(self, tool_name: str) -> Optional[str]:
        """Find which server provides a tool"""
        return self.tool_to_server.get(tool_name)
    
    def search(self, query: str) -> List[dict]:
        """Search servers by name or description"""
        query = query.lower()
        return [
            server for server in self.servers.values()
            if query in server.get('name', '').lower() 
            or query in server.get('description', '').lower()
        ]