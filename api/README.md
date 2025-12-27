# MCP Gateway API

The MCP Gateway API is a FastAPI-based application that acts as a bridge between a large language model (LLM) and the Docker MCP (Mantle Convenience Proxy). It allows the LLM to interact with various external services and tools through the MCP, enabling it to perform a wide range of tasks.

## Features

- **Dynamic Tool Discovery and Usage**: The LLM can dynamically discover and use tools provided by different MCP servers.
- **Multiple LLM Providers**: Supports multiple LLM providers, including OpenAI and OpenRouter.
- **Streaming and Non-Streaming Chat**: Provides both streaming and non-streaming chat endpoints.
- **State Management**: Manages user sessions and the state of active MCP servers and tools.
- **Secret Management**: Securely manages secrets for MCP servers using Infisical and Docker MCP secrets.
- **Configuration Management**: Allows for dynamic configuration of MCP servers.
- **Observability**: Integrates with Langfuse for tracing and observability.
- **Code Execution**: Allows the LLM to execute JavaScript/TypeScript code in a sandboxed environment.

## Architecture

The application is structured into the following components:

- **`main.py`**: The entry point of the FastAPI application. It initializes the application and includes the API routers.
- **`config.py`**: Defines the application settings using Pydantic, loading values from a `.env` file.
- **`core/`**: This directory contains the core logic of the application.
  - **`core/core.py`**: Defines the `AgentCore` class, which manages the agent loop, tool calls, and message preparation.
  - **`core/gateway_client.py`**: Defines the `MCPGatewayAPIClient` class, which is responsible for communicating with the MCP Gateway.
  - **`core/registry.py`**: Defines the `MCPRegistry` class, which loads and provides information about available MCP servers.
  - **`core/state_manager.py`**: Manages the state of the application, including user-specific data like active MCP servers and tools.
- **`providers/`**: This directory contains the implementations of the LLM providers.
  - **`providers/base.py`**: Defines the abstract base class `LLMProvider`.
  - **`providers/factory.py`**: Defines the `LLMProviderFactory` for creating LLM provider instances.
  - **`providers/openai.py`**: Implements the `LLMProvider` for OpenAI's API.
  - **`providers/openrouter.py`**: Implements the `LLMProvider` for the OpenRouter API.
- **`router/`**: This directory contains the API routers.
  - **`router/chat_routes.py`**: Defines the chat-related API endpoints.
  - **`router/mcp_routes.py`**: Defines the API endpoints for managing MCP servers.
- **`services/`**: This directory contains services used by the application.
  - **`services/docker_secrets.py`**: Manages Docker MCP secrets.
  - **`services/langfuse_client.py`**: Initializes and provides a client for Langfuse.
  - **`services/redis_client.py`**: Manages the Redis connection.
  - **`services/secrets_manager.py`**: Interacts with the Infisical secret management service.
- **`utils/`**: This directory contains utility scripts and modules.
  - **`utils/catalog_yml_to_json.py`**: Converts a YAML catalog to JSON.
  - **`utils/logger.py`**: Configures the logger.
  - **`utils/prompts.py`**: Contains system messages and tool schemas for the LLM.
- **`models.py`**: Contains the Pydantic models for the API requests and responses.

## Getting Started

### Prerequisites

- Docker
- Python 3.12+
- An account with a supported LLM provider (e.g., OpenAI)
- An Infisical account for secret management
- Redis (optional, for persistent state management)

### Installation

1.  **Clone the repository:**

    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

2.  **Install the dependencies:**

    ```bash
    uv sync
    ```

3.  **Set up the environment variables:**

    Create a `.env` file in the root of the project and add the following environment variables:

    ```
    # LLM Provider API Keys
    OPENAI_API_KEY=<your-openai-api-key>
    OPENROUTER_API_KEY=<your-openrouter-api-key>

    # Infisical
    INFISICAL_ENABLED=true
    INFISICAL_URL=<your-infisical-url>
    INFISICAL_TOKEN=<your-infisical-token>
    INFISICAL_ENV=<your-infisical-environment>
    INFISICAL_PROJ=<your-infisical-project>

    # Langfuse
    LANGFUSE_ENABLED=true
    LANGFUSE_BASE_URL=<your-langfuse-base-url>
    LANGFUSE_PUBLIC_KEY=<your-langfuse-public-key>
    LANGFUSE_SECRET_KEY=<your-langfuse-secret-key>

    # Redis
    REDIS_ENABLED=true
    REDIS_URL=<your-redis-url>
    ```

### Running the Application

```bash
uv run uvicorn main:app --reload
```

## API Endpoints

The application exposes the following API endpoints:

### Chat

-   `POST /chat`: Non-streaming chat endpoint.
-   `POST /chat/resume`: Resume a conversation after a configuration interrupt.
-   `POST /sse/chat`: Streaming chat endpoint using Server-Sent Events (SSE).
-   `POST /sse/chat/resume`: Resume a streaming chat conversation after a configuration interrupt.

### MCP Server Management

-   `POST /mcp/find`: Discover available MCP servers.
-   `POST /mcp/add`: Add an MCP server.
-   `POST /mcp/remove`: Remove an MCP server.
-   `GET /mcp/servers`: List currently active MCP servers and available tools.

For detailed information about the request and response models, please refer to the `models.py` file and the OpenAPI documentation available at `/docs` when the application is running.
