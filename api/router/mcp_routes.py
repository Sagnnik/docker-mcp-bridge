from fastapi import APIRouter, HTTPException, Header
from utils.logger import logger
import json
from models import (
    MCPRemoveRequest,
    MCPServerConfig,
    MCPFindRequest,
)
from core.gateway_client import MCPGatewayAPIClient
from core.state_manager import get_user_stats

router = APIRouter()

def get_user_id_from_header(x_user_id: str = Header(...)) -> str:
    """
    Extract and validate user ID from header
    Raises HTTPException if missing or invalid
    """
    if not x_user_id or not x_user_id.strip():
        raise HTTPException(
            status_code=401, 
            detail="Missing X-User-Id header. Please provide a valid user identifier."
        )
    return x_user_id.strip()

@router.post("/mcp/find", tags=["mcp"])
async def find_mcp_server(request: MCPFindRequest, x_user_id: str = Header(...)):
    """
    Discover available MCP servers using `mcp-find`.

    Example:
    ```bash
    curl -X POST http://localhost:8000/mcp/find \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{"query": "github"}'
    ```
    """
    user_id = get_user_id_from_header(x_user_id)
    try:
        async with MCPGatewayAPIClient(user_id) as client:
            result = await client.call_tool(
                "mcp-find",
                {"query": request.query}
            )

            return {
                "status": "success",
                "query": request.query,
                "servers": result
            }

    except Exception as e:
        logger.error(f"[User: {user_id}] Find MCP server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mcp/add", tags=['mcp'])
async def add_mcp_server(config: MCPServerConfig, x_user_id: str = Header(...)):
    """
    Add an MCP server
    
    **Security Note**: Secrets cannot be set via API. Configure them externally:
    - Docker CLI: `docker mcp secret set server/key`
    - Environment variables
    - Secret manager (AWS Secrets Manager, Vault, etc.)
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/mcp/add \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "github",
        "activate": true,
        "config": {
          "api_version": "v3"
        }
      }'
    ```
    """
    user_id = get_user_id_from_header(x_user_id)

    if config.secrets:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Secrets cannot be set via API for security reasons",
                "instructions": [
                    f"Run: docker mcp secret set {config.name}=<secret>",
                    "Or configure via environment variables / secrets manager"
                ]
            }
        )
    
    try:
        async with MCPGatewayAPIClient(user_id) as client:
            if config.config:
                for key, value in config.config.items():
                    await client.call_tool("mcp-config-set", {
                        "server": config.name,
                        "key": key,
                        "value": value
                    })

                logger.info(f"[User: {user_id}] Set {len(config.config)} configs for {config.name}")

            result = await client.add_server(
                server_name = config.name,
                activate=config.activate
            )

            user_servers = await get_user_stats(user_id)

            return {
                "status": "success",
                "server": config.name,
                "active_servers": user_servers["active_servers"],
                "available_tools": user_servers["available_tools"],
                "message": "Server added. Ensure secrets are configured externally.",
                "result": result
            }
    
    except Exception as e:
        logger.error(f"[User: {user_id}] Add server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/mcp/remove", tags=["mcp"])
async def remove_mcp_server(request: MCPRemoveRequest, x_user_id: str = Header(...)):
    """
    Remove an MCP server
    
    Example:
    ```bash
    curl -X POST http://localhost:8000/mcp/remove \
      -H "X-User-Id: user123" \
      -H "Content-Type: application/json" \
      -d '{"name": "github"}'
    ```
    """
    user_id = get_user_id_from_header(x_user_id)
    try:
        async with MCPGatewayAPIClient(user_id) as client:
            result = await client.remove_server(request.name)
            user_servers = await get_user_stats(user_id)

            return {
                "status": "success",
                "server": request.name,
                "active_servers": user_servers["active_servers"],
                "available_tools": user_servers["available_tools"],
                "result": result
            }
    
    except Exception as e:
        logger.error(f"[User: {user_id}] Remove server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/mcp/servers", tags=["mcp"])
async def list_servers(x_user_id: str = Header(...)):
    """
    List currently active MCP servers and available tools

    Example:
    ```bash
    curl -X GET http://localhost:8000/mcp/servers \
      -H "X-User-Id: user123"
    ```
    """
    user_id = get_user_id_from_header(x_user_id)
    try:
        user_servers = await get_user_stats(user_id)
        return {
            "user_id": user_id,
            "active_servers": user_servers["active_servers"],
            "available_tools": user_servers["available_tools"],
            "tool_count": user_servers["tool_count"],
            "server_count": user_servers["server_count"],
            "server_tools_info": user_servers.get("server_tools_info", {})
        }
    
    except Exception as e:
        logger.error(f"[User: {user_id}] List servers error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
