from typing import Optional, Dict, List, Any, Set
import httpx
import json
import re
from utils.logger import logger
from models import AddServerResult
import core.state_manager as sm
from core.registry import MCPRegistry

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
        self.registry = MCPRegistry()
        self.registry.load()
        

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
        
        # Get user's authorized tools from state manager
        user_tool_names = await sm.get_user_tools(self.user_id)
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
        # Check access for non-management tools
        if name not in self.MCP_MANAGEMENT_TOOLS:
            user_tool_names = await sm.get_user_tools(self.user_id)

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
            
        # Get expected tools from registry
        expected_tools = set(self.registry.get_tools(server_name))
        
        if not expected_tools:
            logger.warning(f"[User: {self.user_id}] Server '{server_name}' has no tools in registry. ")
        
        # Call mcp-add
        result = await self.call_tool("mcp-add", {
            "name": server_name,
            "activate": activate
        })

        # Verify tools are now available in gateway
        all_tools_after = await self.list_tools(filter_by_user=False)
        available_tool_names = {tool["name"] for tool in all_tools_after}
        
        # Find which expected tools are actually present
        verified_tools = expected_tools & available_tool_names
        missing_tools = expected_tools - available_tool_names
        
        if missing_tools:
            logger.warning(
                f"[User: {self.user_id}] Server '{server_name}' expected tools not found in gateway: "
                f"{sorted(missing_tools)}"
            )
        
        if verified_tools:
            await sm.add_user_server(self.user_id, server_name, verified_tools)
            logger.info(
                f"[User: {self.user_id}] Server '{server_name}' added with {len(verified_tools)} tools: "
                f"{sorted(verified_tools)}"
            )
        else:
            await sm.add_user_server(self.user_id, server_name, set())
            logger.warning(
                f"[User: {self.user_id}] Server '{server_name}' added but no tools verified"
            )
        
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
        
        # Get expected tools from registry
        expected_tools = set(self.registry.get_tools(server_name))

        # Get requirements from registry
        requirements = self.registry.check_and_return_configs_secrets(server_name)
        required_secrets_registry = requirements.get("secrets", [])
        required_configs_registry = requirements.get("config", [])

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

        # 1. Check for missing secrets using regex pattern
        secret_match = re.search(
            r"Missing required secrets\s*\(([^)]+)\)",
            response_text,
            re.IGNORECASE
        )

        if secret_match:
            # Use registry as primary source for secrets
            required_secrets: List[Dict[str, str]] = []
            
            if required_secrets_registry:
                # Registry has structured secret info
                for secret in required_secrets_registry:
                    if isinstance(secret, dict):
                        required_secrets.append({
                            "name": secret.get("name", ""),
                            "env": secret.get("env", ""),
                            "description": secret.get("description", ""),
                            "example": secret.get("example", "")
                        })
                    else:
                        # Fallback for simple string format
                        required_secrets.append({
                            "name": str(secret),
                            "env": str(secret).upper().replace(".", "_"),
                            "description": "API key or secret required",
                            "example": "YOUR_KEY_HERE"
                        })
            else:
                # Fallback: parse from error message
                raw_secrets = [s.strip() for s in secret_match.group(1).split(",")]
                for secret_name in raw_secrets:
                    required_secrets.append({
                        "name": secret_name,
                        "env": secret_name.upper().replace(".", "_"),
                        "description": "API key or secret required",
                        "example": "YOUR_KEY_HERE"
                    })
            
            # Also check mcp-find result for additional context
            if mcp_find_result:
                for res in mcp_find_result:
                    if res.get("name") == server_name and "required_secrets" in res:
                        mcp_secrets = res.get("required_secrets", [])
                        # Merge with registry data
                        existing_names = {s.get("name") for s in required_secrets}
                        for mcp_secret in mcp_secrets:
                            if isinstance(mcp_secret, dict):
                                if mcp_secret.get("name") not in existing_names:
                                    required_secrets.append(mcp_secret)

            logger.warning(
                f"[User: {self.user_id}] Server '{server_name}' requires secrets: "
                f"{[s.get('name') for s in required_secrets]}"
            )

            return AddServerResult(
                status="secrets_required",
                server=server_name,
                required_secrets=required_secrets,
                instructions=response_text,
                raw_response=response_text
            )
        
        # 2. Check for missing config using regex pattern
        config_match = re.search(
            r"Missing required config\s*\(([^)]+)\)",
            response_text,
            re.IGNORECASE
        )

        if config_match:
            # Use registry as primary source for configs
            required_configs: List[Dict[str, Any]] = []
            
            if required_configs_registry:
                # Registry has structured config schema
                for config_schema in required_configs_registry:
                    if isinstance(config_schema, dict):
                        # Extract required fields from schema
                        required_fields = config_schema.get("required", [])
                        properties = config_schema.get("properties", {})
                        
                        for field in required_fields:
                            prop = properties.get(field, {})
                            required_configs.append({
                                "key": field,
                                "type": prop.get("type", "string"),
                                "description": prop.get("description", "Configuration value required")
                            })
            else:
                # Fallback: parse from error message
                raw_configs = [c.strip() for c in config_match.group(1).split(",")]
                for config_key in raw_configs:
                    required_configs.append({
                        "key": config_key,
                        "type": "string",
                        "description": "Configuration value required"
                    })
            
            # Also check mcp-find result for additional context
            if mcp_find_result:
                for res in mcp_find_result:
                    if res.get("name") == server_name and "config_schema" in res:
                        for schema in res["config_schema"]:
                            required = schema.get("required", [])
                            properties = schema.get("properties", {})
                            
                            existing_keys = {c.get("key") for c in required_configs}
                            for key in required:
                                if key not in existing_keys:
                                    prop = properties.get(key, {})
                                    required_configs.append({
                                        "key": key,
                                        "type": prop.get("type", "string"),
                                        "description": prop.get("description", "Configuration value required")
                                    })
            
            # Final fallback if nothing found
            if not required_configs:
                required_configs.append({
                    "key": "unknown",
                    "type": "string",
                    "description": (
                        "This MCP server requires configuration, "
                        "but no config_schema was found. "
                        "Refer to MCP documentation."
                    )
                })

            logger.warning(
                f"[User: {self.user_id}] Server '{server_name}' requires config: "
                f"{[c.get('key') for c in required_configs]}"
            )

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
            # Verify tools using registry
            all_tools_after = await self.list_tools(filter_by_user=False)
            available_tool_names = {tool["name"] for tool in all_tools_after}
            
            verified_tools = expected_tools & available_tool_names
            missing_tools = expected_tools - available_tool_names
            
            if missing_tools:
                logger.warning(
                    f"[User: {self.user_id}] Server '{server_name}' expected tools not found: "
                    f"{sorted(missing_tools)}"
                )
            
            if verified_tools:
                await sm.add_user_server(self.user_id, server_name, verified_tools)
                logger.info(
                    f"[User: {self.user_id}] Server '{server_name}' added with {len(verified_tools)} tools: "
                    f"{sorted(verified_tools)}"
                )
            else:
                await sm.add_user_server(self.user_id, server_name, set())
                logger.warning(
                    f"[User: {self.user_id}] Server '{server_name}' added but no tools verified"
                )
            
            return AddServerResult(
                status="added",
                server=server_name,
                message=f"Server added with {len(verified_tools)} tools"
            )

        # Failed
        logger.error(f"[User: {self.user_id}] Failed: {response_text}")
        return AddServerResult(
            status="failed",
            server=server_name,
            message=response_text,
            raw_response=response_text
        )
    
    async def remove_server(self, server_name: str):
        """Remove server"""
        logger.info(f"[User: {self.user_id}] Removing server '{server_name}'")
        tools_to_remove = await sm.get_server_tools(self.user_id, server_name)
        result = await self.call_tool("mcp-remove", {"name": server_name})
        
        # Remove server entry
        await sm.remove_user_server(self.user_id, server_name)
        
        logger.info(
            f"[User: {self.user_id}] Removed server '{server_name}' "
            f"and {len(tools_to_remove)} associated tools: {sorted(tools_to_remove)}"
        )
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