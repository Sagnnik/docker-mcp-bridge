MCP_BRIDGE_MESSAGES = {
    "default": """You are a helpful assistant with access to MCP tools.
You may use any available MCP tools to answer user questions when appropriate.""",

    "dynamic": """You are a helpful assistant with access to Docker MCP dynamic management tools.
You can discover and add MCP servers at runtime, but you CANNOT configure servers, manage secrets, execute code, or request code-mode environments.

Available capabilities (exposed to you):
- `mcp-find`: Search for available MCP servers by query (e.g., "github", "database", "file system", "wikipedia").
- `mcp-add`: Add and optionally activate a discovered MCP server.

Dynamic workflow (what you should do):
1. When you need a capability or provider that is not currently available, call `mcp-find` with a concise, specific query describing the server or capability you need.
2. Select the most appropriate server from the search results and call `mcp-add` to add (and activate) it.
3. If the server requires configuration or secrets, the runtime will INTERRUPT the conversation and prompt the user to provide them.
4. After the runtime confirms that the server is fully configured and ready, its tools will become available in your context.
5. Continue using the newly available tools to fulfill the user’s request.

Behavior rules and constraints:
- You are ONLY allowed to call `mcp-find` and `mcp-add` in dynamic mode.
- You MUST NOT attempt to configure servers, set secrets, or supply configuration values.
- Do NOT request or assume access to `mcp-config-set`, `code-mode`, or `mcp-exec`.
- Prefer already-available tools before discovering new servers.
- Be specific in `mcp-find` queries to minimize ambiguity and speed up discovery.
- If server setup is interrupted for configuration or secrets, wait for the runtime to resume you with confirmation before proceeding.""",

    "code": """You are a helpful assistant with access to MCP execution tools and the ability to create and run custom JavaScript/TypeScript logic via code-mode.

Available capabilities (exposed to you in code mode):
- `code-mode`: Request creation of a code-mode tool environment.
- `mcp-exec`: Execute JavaScript/TypeScript code inside a code-mode environment.

Code-mode workflow (how to request and use code-mode):
1. Request a `code-mode` environment by specifying:
   - `name`: a unique name (the runtime will prefix it with `code-mode-`).
   - `servers`: an explicit list of MCP servers to include.
   - Do NOT include executable source code in the creation request.
2. The runtime will return documentation describing:
   - helper functions mapped from the selected MCP servers,
   - function signatures and example usage.
3. Use `mcp-exec` to execute JavaScript/TypeScript code:
   - `name`: the code-mode tool name (e.g., `code-mode-my-tool`).
   - `arguments.script`: your JS/TS code string calling the provided helper functions.
4. The sandbox will execute the script and return results for use in answering the user’s question.

Best practices:
- Inspect the returned helper documentation before writing code.
- Keep scripts short, focused, and deterministic.
- Call only the helper functions you need.
- Code-mode supports JavaScript/TypeScript only.
- Server discovery, secrets, and configuration MUST be completed by the runtime BEFORE entering code mode."""
}






LLM_TOOL_SCHEMAS = {
        'mcp-find': {
            'type': 'object',
            'required': ['query'],
            'properties': {
                'query': {
                    'type': 'string',
                    'description': 'Search query to find MCP servers by name, title, or description. Be specific (e.g., "wikipedia", "github", "filesystem") for best results.'
                },
                'limit': {
                    'type': 'integer',
                    'description': 'Maximum number of results to return',
                    'default': 10
                }
            },
            'additionalProperties': False
        },
        'code-mode': {
            'type': 'object',
            'required': ['name', 'servers'],
            'properties': {
                'name': {
                    'type': 'string',
                    'description': "Unique identifier for your custom tool (will be prefixed with 'code-mode-'). Use descriptive names like 'wiki-summary' or 'multi-search'."
                },
                'servers': {
                    'type': 'array',
                    'description': 'List of MCP server names whose tools will be available as JavaScript helper functions in your code environment.',
                    'items': {
                        'type': 'string'
                    },
                    'minItems': 1
                },
                'timeout': {
                    'type': 'integer',
                    'description': 'Execution timeout in seconds',
                    'default': 30
                }
            },
            'additionalProperties': False
        },
        'mcp-exec': {
            'type': 'object',
            'required': ['name', 'arguments'],
            'properties': {
                'name': {
                    'type': 'string',
                    'description': "Name of the code-mode tool to execute (must start with 'code-mode-', e.g., 'code-mode-wiki-summary')"
                },
                'arguments': {
                    'type': 'object',
                    'required': ['script'],
                    'properties': {
                        'script': {
                            'type': 'string',
                            'description': 'JavaScript/TypeScript code to execute. The code has access to helper functions from the MCP servers specified when creating this tool. Use "return" to return results.'
                        }
                    },
                    'additionalProperties': False,
                    'description': 'Execution arguments containing the script to run'
                }
            },
            'additionalProperties': False
        },
        'mcp-add': {
            'type': 'object',
            'required': ['name'],
            'properties': {
                'name': {
                    'type': 'string',
                    'description': 'Name of the MCP server to add to the registry (must exist in catalog)'
                },
                'activate': {
                    'type': 'boolean',
                    'description': 'Activate all of the server\'s tools in the current session',
                    'default': False
                }
            },
            'additionalProperties': False
        }
    }