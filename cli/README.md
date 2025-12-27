# MCP Gateway CLI

This is an interactive command-line interface (CLI) for interacting with the MCP (Multi-Capability Peripheral) Gateway. It allows you to chat with an AI that can use tools from various MCP servers.

## Features

- **Interactive Chat**: Chat with an AI that can use tools.
- **MCP Server Management**: Find, add, and remove MCP servers.
- **Tool Discovery**: List available tools from active MCP servers.
- **AI Configuration**: Configure the AI provider (OpenAI, Anthropic, Google, Ollama) and model.
- **Shell Command Execution**: Run shell commands directly in the CLI.
- **Rich Terminal UI**: A user-friendly interface built with `rich` and `questionary`.

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/docker_mcp_bridge.git
    cd docker_mcp_bridge/cli
    ```

2.  **Install dependencies:**
    This project uses Python 3.12 or higher.
    ```bash
    uv sync
    ```

## Usage

To start the CLI, run:
```bash
uv run cli_app.py
```

This will open an interactive chat interface. You can type `/help` to see a list of available commands.

## Commands

-   `/help`: Show available commands.
-   `/config`: Configure the LLM provider, model, and other settings.
-   `/add`: Search for and add MCP servers.
-   `/find <query>`: Search for specific servers.
-   `/list`: Show active servers and available tools.
-   `/remove`: Remove a server.
-   `!<command>`: Execute a shell command (e.g., `!ls -l`).
-   `/exit`: Exit the CLI.

## Project Structure

-   `cli_app.py`: The main entry point for the interactive CLI.
-   `mcp_host.py`: Contains the `MCPGatewayClient` class for communicating with the MCP Gateway.
-   `cli_chat.py`: Manages the chat with the AI and handles tool calls.
-   `provider.py`: Interacts with different AI providers (OpenAI, Anthropic, Google, Ollama).
-   `configs_secrets.py`: Handles interactive configuration and secret management for MCP servers.
-   `helpers.py`: Contains helper functions and classes.
-   `utils.py`: Contains utility functions.
-   `prompts.py`: Contains prompts for the AI.
-   `pyproject.toml`: The project's dependency file.

## How it Works

The CLI connects to an MCP Gateway, which acts as a bridge to various MCP servers. These servers expose tools that the AI can use. When you chat with the AI, it can decide to use one of the available tools to answer your query. The CLI then executes the tool call through the MCP Gateway and returns the result to the AI. The AI uses this result to formulate its final response.
