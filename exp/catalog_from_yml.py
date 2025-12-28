import yaml, json, pathlib

SRC = pathlib.Path("./api/assets/catalog.yaml")
OUT = pathlib.Path("./api/catalog")
OUT.mkdir(parents=True, exist_ok=True)

catalog = yaml.safe_load(SRC.read_text())

for name, server in catalog["registry"].items():
    record = {
        "name": name,
        "title": server.get("title"),
        "description": server.get("description"),

        # tools
        "tools": [t["name"] for t in server.get("tools", [])],

        # runtime requirements
        "env": server.get("env", []),
        "secrets": server.get("secrets", []),
        "config": server.get("config", [])
    }

    json.dump(record, open(OUT / f"{name}.json", "w"), indent=2)

print(f"Saved {len(catalog['registry'])} MCP servers into ./api/catalog/")
