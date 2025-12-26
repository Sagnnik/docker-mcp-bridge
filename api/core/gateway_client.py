from typing import Optional, Dict, List, Any, Set
import httpx
import json
import re
from utils.logger import logger
from models import AddServerResult
import state_manager

class MCPGatewayAPIClient:
    MCP_PROTOCOL_VERSION = "2024-11-05"
    MCP_URL = "http://localhost:8811/mcp"
    MCP_MANAGEMENT_TOOLS = {
        "code-mode",
        "mcp-add",
        "mcp-config-set",
        "mcp-exec",
        "mcp-find",
        "mcp-remove"
    }

    def __init__(self, user_id:str):
        self.user_id = user_id
        self.session_id: Optional[str] = None
        self._next_id = 1
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
                "clientInfo": {
                        "name": "mcp-api-gateway", 
                        "version": "1.0.0", 
                        "userId": self.user_id
                    }
            }
        }
        self._next_id += 1
        
        response = await self._client.post(
            self.MCP_URL,
            json=payload,
            headers={
                "Mcp-Protocol-Version": self.MCP_PROTOCOL_VERSION,
                "Accept": "application/json, text/event-stream",
                "X-User-Id": self.user_id,
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
                "X-User-Id": self.user_id,
            }
        )
        logger.info(f"[User: {self.user_id}] MCP session initialized: {self.session_id}")

    async def list_tools(self, filter_by_user: bool = True)-> List[Dict]:
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
                "X-User-Id": self.user_id,
            }
        )

        data = self._parse_response(response.text)
        all_tools = data.get('result', {}).get('tools', [])
        
        logger.info(f"[User: {self.user_id}] Gateway returned {len(all_tools)} total tools")
        
        if not filter_by_user:
            return all_tools
        
        # Filter by user's active server tools
        user_tool_names = await state_manager.get_user_tools(self.user_id)
        allowed_tools = self.MCP_MANAGEMENT_TOOLS | user_tool_names
        filtered_tools = [
            tool for tool in all_tools 
            if tool.get("name") in allowed_tools
        ]
        
        logger.info(
            f"[User: {self.user_id}] Filtered to {len(filtered_tools)} tools "
            f"({len(self.MCP_MANAGEMENT_TOOLS)} management + {len(user_tool_names)} user tools)"
        )
        return filtered_tools
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]):
        """Call an MCP tool with access control"""
        # No access check (excluding mangement tools)
        if name not in self.MCP_MANAGEMENT_TOOLS:
            user_tool_names = await state_manager.get_user_tools(self.user_id)

            if name not in user_tool_names:
                raise PermissionError(
                    f"Access denied: Tool '{name}' is not available to user {self.user_id}. "
                    f"Please activate the required MCP server first."
                )
        
        logger.info(f"[User: {self.user_id}] Calling tool '{name}' with Arguments: {arguments}")
        
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
                "X-User-Id": self.user_id,
            }
        )
        
        data = self._parse_response(response.text)
        if 'error' in data:
            logger.error(f"[User: {self.user_id}] Tool '{name}' error: {data['error']}")
            raise RuntimeError(f"MCP error: {data['error']}")
        
        logger.info(f"[User: {self.user_id}] Tool '{name}' executed successfully")
        return data["result"]

    async def add_server(self, server_name: str, activate: bool = True, 
                        config: Optional[Dict] = None, secrets: Optional[Dict] = None):
        """
        Add MCP server programmatically (no interactive prompts)
        
        Args:
            server_name: Server name to add
            activate: Whether to activate immediately
            config: Optional config dict (key-value pairs)
            secrets: Optional secrets dict (handled via environment or external secret manager)
        """
        if config:
            for key, value in config.items():
                await self.call_tool("mcp-config-set", {
                    "server": server_name,
                    "key": key,
                    "value": value
                })

        logger.info(f"[User: {self.user_id}] Adding server '{server_name}'")
            
        # Get the tools before adding
        tools_before = await self.list_tools(filter_by_user=False)
        tools_before_names = {tool["name"] for tool in tools_before}

        result = await self.call_tool("mcp-add", {
            "name": server_name,
            "activate": activate
        })

        # Get tools after adding
        tools_after = await self.list_tools(filter_by_user=False)
        tools_after_names = {tool["name"] for tool in tools_after}

        new_tool_names = (tools_after_names - tools_before_names) - self.MCP_MANAGEMENT_TOOLS

        if new_tool_names:
            # Add these tools to user's available tools
            await state_manager.add_user_tools(self.user_id, new_tool_names)
            logger.info(
                f"[User: {self.user_id}] Server '{server_name}' added {len(new_tool_names)} "
                f"tools: {sorted(new_tool_names)}"
            )
        else:
            logger.warning(f"[User: {self.user_id}] Server '{server_name}' added no new tools")
        
        # Track server activation
        await state_manager.add_user_server(self.user_id, server_name)
        
        return result
    
    async def add_server_llm(self, server_name: str, activate:str=True, mcp_find_result: Optional[List[Dict]] = None) -> AddServerResult:
        """
        Attempt to add server dynamically requested by the LLM
        - LLM can only request addition {name: deepwiki, activate: true}
        - Runtime need to enforce configs and secrets
        - Returns a structured interruption when needed

        Decision order:
        1. Missing secrets  -> HARD STOP
        2. Missing config   -> INTERRUPT
        3. Success          -> ADDED
        4. Anything else    -> FAILED
        """

        server_name = server_name.strip()
        logger.info(f"[User: {self.user_id}] LLM requesting server '{server_name}'")
        
        # Get tools before adding
        tools_before = await self.list_tools(filter_by_user=False)
        tools_before_names = {tool["name"] for tool in tools_before}

        try:
            result = await self.call_tool(
                "mcp-add",
                {
                    "name": server_name,
                    "activate": True
                }
            )
        except Exception as e:
            logger.error(f"[User: {self.user_id}] Failed to add server '{server_name}': {e}")
            return AddServerResult(
                status="failed",
                server=server_name,
                message=str(e)
            )
        
        if isinstance(result, dict) and "content" in result:
            response_text = self._parse_response(result["content"])
        else:
            response_text = str(result)

        response_text = response_text.strip()

        # 1. Missing secrets (HARD STOP)
        secret_match = re.search(
            r"Missing required secrets\s*\(([^)]+)\)",
            response_text,
            re.IGNORECASE
        )

        if secret_match:
            required_secrets: List[str] = []

            # Enrich from mcp-find (authoritative)
            if mcp_find_result:
                for res in mcp_find_result:
                    if res.get("name") == server_name:
                        required_secrets.extend(
                            res.get("required_secrets", [])
                        )

            # Fallback if MCP metadata missing
            if not required_secrets:
                raw_match = re.search(
                    r"Missing required secrets\s*\(([^)]+)\)",
                    response_text,
                    re.IGNORECASE
                )
                if raw_match:
                    required_secrets = [
                        s.strip() for s in raw_match.group(1).split(",")
                    ]

            logger.warning(f"[User: {self.user_id}] Server '{server_name}' requires secrets: {required_secrets}")

            return AddServerResult(
                status="secrets_required",
                server=server_name,
                required_secrets=required_secrets,
                instructions=response_text,
                raw_response=response_text
            )
        
        # 2. Missing config (INTERRUPT)
        config_match = re.search(
            r"Missing required config\s*\(([^)]+)\)",
            response_text,
            re.IGNORECASE
        )

        if config_match:
            required_configs: List[Dict[str, Any]] = []

            # Try to enrich config details from mcp-find (optional)
            if mcp_find_result:
                for res in mcp_find_result:
                    if res.get("name") == server_name and "config_schema" in res:
                        for schema in res["config_schema"]:
                            required = schema.get("required", [])
                            properties = schema.get("properties", {})

                            for key in required:
                                prop = properties.get(key, {})
                                required_configs.append({
                                    "key": key,
                                    "type": prop.get("type", "string"),
                                    "description": prop.get(
                                        "description",
                                        "Configuration value required"
                                    )
                                })

            # Fallback when schema is unavailable
            if not required_configs:
                required_configs.append({
                    "key": "unknown",
                    "type": "string",
                    "description": (
                        "This MCP server requires configuration, "
                        "but no config_schema was returned. "
                        "Refer to MCP documentation."
                    )
                })

            logger.warning(f"[User: {self.user_id}] Server '{server_name}' requires config: {required_configs}")

            return AddServerResult(
                status="config_required",
                server=server_name,
                required_configs=required_configs,
                instructions=response_text,
                raw_response=response_text
            )
        
        # 3. Success
        success_indicators = [
            "successfully added",
            "success",
            "ready to use",
        ]

        is_success = any(indicator in response_text.lower() for indicator in success_indicators)
        
        if is_success:
            # Get tools after adding
            tools_after = await self.list_tools(filter_by_user=False)
            tools_after_names = {tool["name"] for tool in tools_after}
            
            # Find NEW tools
            new_tool_names = (tools_after_names - tools_before_names) - self.MCP_MANAGEMENT_TOOLS
            
            if new_tool_names:
                # Add to user's tool list
                await state_manager.add_user_tools(self.user_id, new_tool_names)
                logger.info(
                    f"[User: {self.user_id}] Server '{server_name}' added {len(new_tool_names)} "
                    f"tools: {sorted(new_tool_names)}"
                )
            else:
                logger.warning(f"[User: {self.user_id}] Server '{server_name}' added no new tools")
            
            # Track server
            await state_manager.add_user_server(self.user_id, server_name)
            
            return AddServerResult(
                status="added",
                server=server_name,
                message=f"Server added with {len(new_tool_names)} tools"
            )

        # Failed
        logger.error(f"[User: {self.user_id}] Failed: {response_text}")
        return AddServerResult(
            status="failed",
            server=server_name,
            message=response_text,
            raw_response=response_text
        )
    
    async def _rebuild_user_tools(self):
        """
        Rebuild user tool list from current gateway state
        Called after removing a server
        """
        # Get current user's servers
        user_servers = await state_manager.get_user_servers(self.user_id)

        # Get all current tools from gateway
        all_tools = await self.list_tools(filter_by_user=False)
        current_tool_names = {tool["name"] for tool in all_tools} - self.MCP_MANAGEMENT_TOOLS

        # Get user's current tool list
        user_tool_names = await state_manager.get_user_tools(self.user_id)

        # Keep only tools that still exist in gateway
        valid_tools = user_tool_names & current_tool_names

        await state_manager.set_user_tools(self.user_id, valid_tools)
        
        logger.debug(f"[User: {self.user_id}] Rebuilt tool list: {len(valid_tools)} tools remaining")

    
    async def remove_server(self, server_name: str):
        """
        Remove server and clear its tools from user's list
        We rebuild the user's tool list from scratch since we cannot know which tools belonged to this server
        """
        logger.info(f"[User: {self.user_id}] Removing server '{server_name}'")
        
        result = await self.call_tool("mcp-remove", {"name": server_name})
        
        # Remove from user's servers
        await state_manager.remove_user_server(self.user_id, server_name)
        
        # Rebuild user's tool list by checking what's still available
        await self._rebuild_user_tools()
        
        logger.info(f"[User: {self.user_id}] Removed server '{server_name}'")
        return result
    
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