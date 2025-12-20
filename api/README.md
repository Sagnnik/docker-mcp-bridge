# MCP Agent Gateway API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An intelligent gateway API that sits between a client application and Large Language Model (LLM) providers. This project supercharges LLMs by giving them dynamic access to a catalog of external tools via the Docker MCP (Multi-Capability Peripheral) framework.

## Abstract

The MCP Agent Gateway is designed to simplify the integration of powerful, tool-using AI agents into applications. It acts as a smart proxy that manages communication with LLMs (like OpenAI and Google) and orchestrates their access to MCP servers—sandboxed tools running in Docker. This enables developers to build sophisticated applications where an LLM can dynamically discover and use tools, such as finding servers with `mcp-find` or executing sandboxed Javascript/TypeScript code with `code-mode`.

## Core Features

- **LLM Agnostic:** Easily switch between supported LLM providers (e.g., OpenAI, Google) via a simple API parameter.
- **Dynamic Tool Management:** Empowers the LLM to dynamically find (`mcp-find`) and add (`mcp-add`) new capabilities from a Docker MCP catalog during a conversation.
- **Sandboxed Code Execution:** Provides a `code-mode` for LLMs to write and execute custom Javascript/TypeScript in a secure, sandboxed environment.
- **Interrupt and Resume:** Gracefully handles situations where a tool requires user configuration (e.g., an API key). The conversation is paused and can be resumed later, preserving the full context.
- **Streaming and Non-Streaming:** Offers both standard request/response (`/chat`) and Server-Sent Events (`/sse/chat`) endpoints for real-time applications.

## Architecture Overview

The gateway operates as a central orchestrator:

1.  **Client Application:** Sends a chat request to the Gateway API.
2.  **Gateway API (`routes.py`):** The FastAPI entry point that receives the request.
3.  **Agent Core (`core.py`):** The "brain" of the gateway. It runs the main agentic loop, preparing prompts and managing the conversation flow.
4.  **LLM Provider (`provider.py`):** The agent core communicates with the selected LLM (e.g., OpenAI) through an abstracted provider interface.
5.  **MCP Gateway Client (`gateway_client.py`):** When the LLM decides to use a tool, the client sends a JSON-RPC request to the locally running MCP Server.
6.  **MCP Server:** A separate process (e.g., `docker mcp host`) running on `localhost:8811` that executes the tool commands.

## Getting Started

### Prerequisites

- Python 3.12+
- Pip and a virtual environment tool (e.g., `venv`)
- Docker
- A running Docker MCP Host instance.

### Installation

1.  **Clone the repository:**
    ```sh
    git clone <your-repository-url>
    cd api
    ```

2.  **Create and activate a virtual environment:**
    ```sh
    python -m venv .venv
    source .venv/bin/activate
    ```

3.  **Populate dependencies:** Your `pyproject.toml` needs to be updated with the project's dependencies. Add the following to the `[project]` section:
    ```toml
    dependencies = [
        "fastapi",
        "uvicorn",
        "httpx",
        "openai",
        "python-dotenv",
        "pydantic"
    ]
    ```

4.  **Install the project:**
    ```sh
    pip install -e .
    ```

### Configuration

1.  Create a `.env` file in the root of the project directory.
2.  Add the necessary API keys for the LLM providers you intend to use.

    ```env
    # .env file

    # For OpenAI
    OPENAI_API_KEY=sk-proj-xxxxxxxx
    ```

### Running the Application

Once installed and configured, run the API using Uvicorn:
```sh
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
The API will be available at `http://localhost:8000`.

## API Endpoints

### `POST /chat`

Executes a full, non-streaming conversation and returns the final result.

**Example Request:**
```json
{
    "messages": [{"role": "user", "content": "Find the MCP server for github and add it."}],
    "model": "gpt-4-turbo",
    "provider": "openai",
    "mode": "dynamic",
    "inital_servers": []
}
```

**Example Success Response:**
```json
{
    "content": "I have successfully found and added the GitHub MCP server.",
    "active_servers": ["github"],
    "available_tools": ["mcp-find", "mcp-add", "github-list-repos"],
    "finish_reason": "stop"
}
```

**Example Interrupt Response (`config_required`):**
When a tool needs configuration from the user.
```json
{
    "interrupt_type": "config_required",
    "server": "github",
    "required_configs": [
        {"key": "token", "type": "string", "description": "GitHub PAT"}
    ],
    "conversation_state": [
        //...full message history...
    ],
    "interrupt_id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8",
    "instructions": "The 'github' server requires a 'token' to be configured."
}
```

### `POST /chat/resume`

Resumes a conversation that was interrupted for configuration.

**Example Request:**
```json
{
    "interrupt_id": "a1b2c3d4-e5f6-7890-g1h2-i3j4k5l6m7n8",
    "provided_configs": {
        "token": "ghp_xxxxxxxxxxxx"
    }
}
```

### Streaming Endpoints

-   **`POST /sse/chat`**: Initiates a streaming chat session using Server-Sent Events.
-   **`POST /sse/chat/resume`**: Resumes a streaming chat session that was interrupted.

These endpoints provide real-time events for `content`, `tool_call`, `tool_result`, and `interrupt` states.

## Roadmap

This project is currently in its initial version. Future improvements include:

-   **Improved Project Structure:** Refactoring into a more scalable, domain-driven structure.
-   **Persistent State Management:** Replacing the in-memory interrupt store with a robust solution like Redis.
-   **Secrets Management:** Integrating with a secrets vault (e.g., HashiCorp Vault, Infisical, AWS/GCP Secrets Manager) for securely handling tool secrets.
-   **Asynchronous Task Handling:** Using a task queue like Celery to manage long-running agent jobs out-of-band from web requests.
-   **Robust Error Handling:** Replacing fragile string parsing with a structured JSON contract for communication with the MCP server.

## Contributing

Contributions are welcome! Please feel free to open an issue or submit a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](https://opensource.org/licenses/MIT) file for details.
