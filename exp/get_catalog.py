from mcp_host import MCPGatewayClient
import httpx
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tqdm import tqdm

CATALOG_DIR = Path("catalog")
CATALOG_DIR.mkdir(exist_ok=True)


async def store_full_catalog():
    mcp = MCPGatewayClient()

    async with httpx.AsyncClient(timeout=300) as client:
        await mcp.initialize(client)

        await mcp.list_tools(client)

        # Indeterminate progress spinner
        with tqdm(total=1, desc="Fetching MCP catalog", bar_format="{l_bar}{bar} {elapsed}") as pbar:
            catalog = await mcp.find_mcp_servers(
                client=client,
                query=" ",
                limit=1000
            )
            pbar.update(1)

        catalog_payload = {
            "fetched_at": datetime.utcnow().isoformat() + "Z",
            "source": "mcp-find",
            "query": "",
            "limit": 1000,
            "catalog": catalog,
        }

        output_path = CATALOG_DIR / "mcp_catalog.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(catalog_payload, f, indent=2)

        print(f"\nMCP catalog stored at: {output_path.resolve()}")


if __name__ == "__main__":
    asyncio.run(store_full_catalog())   