import json
import pathlib
from typing import Dict, List

CATALOG_PATH = pathlib.Path("./catalog")

class MCPRegistry:
    def __init__(self):
        self.servers: Dict[str, str] = {}
        self.server_to_tool: Dict[str, str] = {}
        self.server_secrets: Dict[str, str] = {}
        self.server_config: Dict[str, str] = {}
        self.server_desc: Dict[str, str] = {}
    
    def load(self):
        for f in CATALOG_PATH.glob("*.json"):
            data = json.load(open(f))
            name = data['name']

            self.servers[name] = data
            self.server_desc[name] = data.get('description', 'No description')
            self.server_to_tool[name] = data.get('tools', [])
            self.server_secrets[name] = data.get('secrets', [])
            self.server_config[name] = data.get('config', [])

    def get_servers(self):
        return self.servers

    def get_tools(self, server:str) ->List[str]:
        return self.server_to_tool.get(server, [])
    
    def check_and_return_configs_secrets(self, server:str) -> List[Dict[str, str]]:
        return {
            "secrets": self.server_secrets.get(server, []),
            "config": self.server_config.get(server, [])
        }
