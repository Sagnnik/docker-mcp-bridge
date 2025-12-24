from fastapi import APIRouter, HTTPException
from utils.logger import logger
import json
from models import (
    MCPRemoveRequest,
    MCPServerConfig,
    MCPFindRequest,
)
from core.gateway_client import MCPGatewayAPIClient

router = APIRouter()

@router.post("/mcp/find", tags=["mcp"])
async def find_mcp_server(request: MCPFindRequest):
    """
    Discover available MCP servers using `mcp-find`.

    Example:
    ```json
    {
        "query": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
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
        logger.error(f"Find MCP server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/mcp/add", tags=['mcp'])
async def add_mcp_server(config: MCPServerConfig):
    """
    Add an MCP server
    
    **Security Note**: Secrets cannot be set via API. Configure them externally:
    - Docker CLI: `docker mcp secret set server/key`
    - Environment variables
    - Secret manager (AWS Secrets Manager, Vault, etc.)
    
    Example:
    ```json
    {
        "name": "github",
        "activate": true,
        "config": {
            "api_version": "v3"
        }
    }
    ```
    """

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
        async with MCPGatewayAPIClient() as client:
            if config.config:
                for key, value in config.config.items():
                    await client.call_tool("mcp-config-set", {
                        "server": config.name,
                        "key": key,
                        "value": value
                    })

                logger.info(f"Set {len(config.config)} configs for {config.name}")

            result = await client.add_server(
                server_name = config.name,
                activate=config.activate
            )

            return {
                "status": "success",
                "server": config.name,
                "active_servers": client.active_servers,
                "message": "Server added. Ensure secrets are configured externally.",
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Add server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.post("/mcp/remove", tags=["mcp"])
async def remove_mcp_server(request: MCPRemoveRequest):
    """
    Remove an MCP server
    
    Example:
    ```json
    {
        "name": "github"
    }
    ```
    """
    try:
        async with MCPGatewayAPIClient() as client:
            result = await client.remove_server(request.name)

            return {
                "status": "success",
                "server": request.name,
                "result": result
            }
    
    except Exception as e:
        logger.error(f"Remove server error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/mcp/servers", tags=["mcp"])
async def list_servers():
    """
    List currently active MCP servers and available tools
    """
    try:
        async with MCPGatewayAPIClient() as client:
            return {
                "active_servers": client.active_servers,
                "available_tools": list(client.available_tools.keys()),
                "tool_count": len(client.available_tools)
            }
    
    except Exception as e:
        logger.error(f"List servers error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
