<div align="center">
  <h1>Docker MCP Bridge</h1>
  <p><strong>A Dynamic, Secure, and Scalable Tool-Use Engine for Large Language Models</strong></p>
  <p>
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" />
  <img src="https://img.shields.io/badge/Docker-Required-blue?logo=docker" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?logo=python" />
  <img src="https://img.shields.io/badge/LLM-Agent%20Infrastructure-orange" />
  <img src="https://img.shields.io/badge/Status-Active%20Development-yellow" />
</p>
</div>

---

**Docker MCP Bridge** is a middleware layer that makes tool use for LLM agents practical, scalable, and safe.

As agents move beyond simple function calls toward real-world execution — APIs, sandboxes, services, and long-running tasks — the naïve *“dump all tools into the prompt”* approach starts to break down.   

**Docker MCP Bridge** acts as a **central execution gateway**, letting agents reason about what they want to do while the system handles how tools are **discovered**, **executed**, and **isolated**.

**The Result:** agents that are more *flexible*, *cheaper* to run, and far easier to *extend*.

## 🧩 The Core Problems with Traditional Tool-Use
### 1. Context Window Overload

Most tool-use systems require injecting every available tool schema directly into the model’s context. This works for demos — but fails at scale.
- **Context waste**: Tool definitions can dominate the prompt, leaving little room for reasoning or conversation.
- **Higher costs**: You pay for large contexts on every request, even when most tools aren’t used.
- **Worse reasoning**: Overloaded context makes it harder for the model to focus on the actual task.

[*Anthropic’s Advanced Tool Use*](https://www.anthropic.com/engineering/advanced-tool-use) shows that tools should be **discovered** and **loaded dynamically**, not blindly included upfront. **Docker MCP Bridge** follows this principle by keeping tool execution outside the model’s context until it’s actually needed.

### 2. The Static Toolset Limitation

LLMs are surprisingly good at inventing new tools on the fly — writing glue code, composing APIs, or chaining steps dynamically. The real challenge isn’t generation, it’s execution.
- **Predefined tools are brittle**: You can’t anticipate every capability an agent might need.
- **Static schemas don’t teach usage**: Knowing a tool’s shape isn’t the same as knowing how to use it.
- **Unsafe execution**: Letting an LLM run arbitrary code on a host system is a non-starter.

**Docker MCP Bridge** solves this by treating tool use as an execution problem, not a prompting problem. Custom Tools run in *isolated Docker sandboxes*, with explicit boundaries, resource controls, and lifecycle management.

---

## ⚙️ How Docker MCP Bridge Works

Instead of treating tools as static prompt artifacts, tools are managed as **external, containerized services** that the agent can discover and invoke dynamically.

### 🧭 Reducing Context Bloat with a Tool Registry

Rather than injecting every tool definition into the prompt, Docker MCP Bridge maintains an external **MCP Registry**.
The LLM is exposed to a single lightweight discovery primitive: `mcp-find`.
1. The agent decides it needs a capability and calls mcp-find using a natural-language query (e.g. “find a tool for React Query documentation”).
2. The registry returns a short list of relevant tools.
3. Full tool schemas are only loaded at execution time, not during reasoning.

This keeps prompts small, reduces token costs, and scales cleanly as the tool ecosystem grows.

### 🔒 Secure Execution via Docker Isolation

LLMs are capable of composing and generating new tools on demand. The real challenge is executing them safely. Docker MCP Bridge treats **tool execution as a sandboxed runtime concern**, not a prompting concern.

1.  The LLM generates the code or definition for a new tool.
2.  It calls the `code-mode` tool to **programmatically register** this new tool.
3.  The tool is executed inside a dedicated Docker container with isolation and resource boundaries.
4.  Results are returned to the agent without exposing the host system.

This creates a truly dynamic and adaptive agent that can extend its own capabilities in response to user needs.

---

| Approach | Tool Discovery | Execution Safety | Dynamic Tools |
|--------|----------------|------------------|---------------|
| Prompt-injected tools | ❌ | ❌ | ❌ |
| LangChain-style tools | ⚠️ | ⚠️ | ❌ |
| **Docker MCP Bridge** | ✅ | ✅ | ✅ |

---

### Who is Docker MCP Bridge for?

- Developers building LLM agents that need **real tools**, not just function calls
- Teams experimenting with MCP who want **safe execution**
- Anyone hitting **context limits or tool sprawl** with existing agent frameworks

---

## 🏗️ Architecture

The system is designed as a central hub that manages tool discovery, dynamic registration, and secure execution.
```sql
┌────────────────────┐
│   Your App / UI    │
│ (Chat, Agent, API) │
└─────────┬──────────┘
          │
          ▼
┌──────────────────────────┐
│   Docker MCP Bridge API  │  ← the ONLY thing your app talks to
│                          │
│  ┌───────────────────┐   │
│  │    Agent Core     │   │  ← reasoning, tool decisions
│  └─────────┬─────────┘   │
│            │             │
│   ┌────────▼────────┐    │
│   │   Tool Registry │    │  ← what tools exist?
│   │   (Redis / FS)  │    │
│   └────────┬────────┘    │
│            │             │
│   ┌────────▼────────┐    │
│   │ Docker Executor │    │  ← runs tools safely
│   └────────┬────────┘    │
└────────────┼─────────────┘
             │
             ▼
┌──────────────────────────┐
│   Isolated Docker Tools  │
│ (One container per tool) │
└──────────────────────────┘
```


---

## 🚀 Getting Started

### Prerequisites

-   Docker and Docker Compose
-   Python 3.10+
-   An LLM API key (e.g., OpenAI, Anthropic)

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Sagnnik/docker-mcp-bridge.git
    cd docker-mcp-bridge
    ```

2.  **Configure the environment:**
    Copy the example `.env` file. This is where you'll put your secrets.
    ```bash
    cp api/.env.example api/.env
    ```
    Now, edit `api/.env` with your API keys.

3. **Expand the MCP catalog**
    Run the command:
    ```bash
    python ./api/utils/catalog_yml_to_json.py
    ```

4.  **Launch the services:**
    This single command builds the images and starts the API server, Redis, and any other defined services.
    ```bash
    docker-compose up --build -d
    ```
    The API will be available at `http://localhost:8000`. You can view logs with `docker-compose logs -f`.

---

## 💻 API Usage

The API is the primary way to interact with the Docker MCP Bridge.

### `POST /chat` or `POST /sse/chat`

The main endpoints for your application to interact with the agent.

**Example `curl` command:**
```bash
curl -X POST http://localhost:8000/chat \
  -H "X-User-Id: user123" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "can you add the duckduckgo server and summarize the latest financial report of google?"}],
    "model": "gpt-5-mini",
    "provider": "openai",
    "mode": "dynamic"
  }'
```
<details>
<summary>Logs</summary>

```bash
December 27, 2025 - 15:58:18 | INFO | [User: user123] MCP session initialized: DFNY6AW45YAS5FRUXVHZSGWPGR
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:18 | INFO | [User: user123] Gateway returned 6 total tools
December 27, 2025 - 15:58:18 | INFO | [User: user123] Filtered to 6 tools (6 management + 0 user tools)
December 27, 2025 - 15:58:18 | INFO | [User: user123] ---> Iteration 1/10
December 27, 2025 - 15:58:26 | INFO | [User: user123] Calling tool: mcp-find
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:26 | INFO | 
[User: user123] 
[tool name]: mcp-find
[tool args]: {'query': 'duckduckgo', 'limit': 10}

December 27, 2025 - 15:58:26 | INFO | [User: user123] Calling tool 'mcp-find' with Arguments: {'query': 'duckduckgo', 'limit': 10}
December 27, 2025 - 15:58:26 | INFO | [User: user123] Tool 'mcp-find' executed successfully
December 27, 2025 - 15:58:26 | INFO | [User: user123] ---> Iteration 2/10
December 27, 2025 - 15:58:28 | INFO | [User: user123] Calling tool: mcp-add
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:28 | INFO | 
[User: user123] 
[tool name]: mcp-add
[tool args]: {'name': 'duckduckgo', 'activate': True}

December 27, 2025 - 15:58:28 | INFO | [User: user123] LLM requesting server 'duckduckgo'
December 27, 2025 - 15:58:28 | INFO | [User: user123] Calling tool 'mcp-add' with Arguments: {'name': 'duckduckgo', 'activate': True}
December 27, 2025 - 15:58:30 | INFO | [User: user123] Tool 'mcp-add' executed successfully
December 27, 2025 - 15:58:30 | INFO | [User: user123] Gateway returned 8 total tools
December 27, 2025 - 15:58:30 | INFO | [User: user123] Server 'duckduckgo' added with 2 tools: ['fetch_content', 'search']
December 27, 2025 - 15:58:30 | INFO | [User: user123] Gateway returned 8 total tools
December 27, 2025 - 15:58:30 | INFO | [User: user123] Filtered to 8 tools (6 management + 2 user tools)
December 27, 2025 - 15:58:30 | INFO | [User: user123] Tools refreshed, now have 8 tools
December 27, 2025 - 15:58:30 | INFO | [User: user123] ---> Iteration 3/10
December 27, 2025 - 15:58:35 | INFO | [User: user123] Calling tool: search
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:35 | INFO | 
[User: user123] 
[tool name]: search
[tool args]: {'query': 'Alphabet latest earnings report 2025 Q3 Oct 2025 Alphabet press release Google financial report', 'max_results': 5}

December 27, 2025 - 15:58:35 | INFO | [User: user123] Calling tool 'search' with Arguments: {'query': 'Alphabet latest earnings report 2025 Q3 Oct 2025 Alphabet press release Google financial report', 'max_results': 5}
December 27, 2025 - 15:58:38 | INFO | [User: user123] Tool 'search' executed successfully
December 27, 2025 - 15:58:38 | INFO | [User: user123] ---> Iteration 4/10
December 27, 2025 - 15:58:42 | INFO | [User: user123] Calling tool: fetch_content
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:42 | INFO | 
[User: user123] 
[tool name]: fetch_content
[tool args]: {'url': 'https://abc.xyz/investor/news/news-details/2025/Alphabet-Announces-Third-Quarter-2025-Results-2025-mIRgD3AI4A/default.aspx'}

December 27, 2025 - 15:58:42 | INFO | [User: user123] Calling tool 'fetch_content' with Arguments: {'url': 'https://abc.xyz/investor/news/news-details/2025/Alphabet-Announces-Third-Quarter-2025-Results-2025-mIRgD3AI4A/default.aspx'}
December 27, 2025 - 15:58:44 | INFO | [User: user123] Tool 'fetch_content' executed successfully
December 27, 2025 - 15:58:44 | INFO | [User: user123] ---> Iteration 5/10
December 27, 2025 - 15:58:46 | INFO | [User: user123] Calling tool: fetch_content
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 15:58:46 | INFO | 
[User: user123] 
[tool name]: fetch_content
[tool args]: {'url': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204425000087/googexhibit991q32025.htm'}

December 27, 2025 - 15:58:46 | INFO | [User: user123] Calling tool 'fetch_content' with Arguments: {'url': 'https://www.sec.gov/Archives/edgar/data/1652044/000165204425000087/googexhibit991q32025.htm'}
December 27, 2025 - 15:58:47 | INFO | [User: user123] Tool 'fetch_content' executed successfully
December 27, 2025 - 15:58:47 | INFO | [User: user123] ---> Iteration 6/10
INFO:     127.0.0.1:60542 - "POST /chat HTTP/1.1" 200 OK
```
</details>

<details>
<summary>Reponse</summary>

```json
{
   "content":"Done — I added and activated the DuckDuckGo MCP server (it provided the web/search tools I used).\n\nSummary of Alphabet / Google — Third Quarter 2025 (quarter ended Sept 30, 2025)\nSource: Alphabet press release / SEC exhibit (Oct 29, 2025)\n\nKey financials\n- Revenue: $102.3 billion, up 16% year-over-year (constant-currency +15%).\n- Net income: $35.0 billion, up 33%.\n- Diluted EPS: $2.87, up 35%.\n- Operating income: $31.2 billion (operating margin 30.5%). Excluding a $3.5B European Commission (EC) fine, operating income would be up 22% and margin 33.9%.\n- Other income (net): $12.8 billion, largely unrealized gains on non-marketable equity securities.\n\nBusiness / segment highlights\n- Google Services revenue: $87.1 billion (up ~14%). Includes Search & other, YouTube ads, subscriptions, platforms & devices.\n  - Google Search & other: $56.6B\n  - YouTube ads: $10.3B\n  - Google subscriptions, platforms & devices: $12.9B\n- Google Cloud revenue: $15.2 billion, up 34%, with large growth across GCP, AI infrastructure and generative-AI solutions.\n- Other Bets revenue: $0.34 billion (loss continuing).\n- Total Traffic Acquisition Costs (TAC): $14.9 billion.\n\nOperational / strategic notes\n- Alphabet reported its first-ever $100+ billion quarter.\n- Management highlighted AI momentum: first-party models like Gemini processing ~7 billion tokens per minute; Gemini App ~650 million monthly active users.\n- Google Cloud backlog at quarter end: $155 billion.\n- Over 300 million paid subscriptions across Google products.\n- Alphabet expects 2025 capital expenditures of $91–$93 billion (raised to meet demand).\n- EC fine: Alphabet accrued a $3.5B charge related to an EC decision (recorded in Google Services G&A).\n- Dividend: Board declared a quarterly cash dividend of $0.21 per share (payable Dec 15, 2025; record date Dec 8, 2025).\n\nOther items\n- Number of employees: ~190,167.\n- Hedging losses, severance/office charges and Other-Bets losses impacted some Alphabet-level items.\n- The company posted notable unrealized gains that boosted other income in the quarter.\n\nWould you like:\n- A one-page PDF-style brief with the top metrics and a chart?\n- The full earnings release or the SEC exhibit links I used?\n- A deeper dive into Google Cloud, YouTube, or margin drivers?",
   "active_servers":[
      "duckduckgo"
   ],
   "available_tools":[
      "search",
      "fetch_content"
   ],
   "finish_reason":"stop"
}
```
</details>
  

**Example `code-mode` commands with interrupt sequence:**
```bash
curl -X POST http://localhost:8000/chat \
  -H "X-User-Id: user123" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "Add the arxiv mcp server then create a custom tool that fetches recent arXiv papers about recursive transformers, tree-based attention architectures, and hierarchical sequence models using the arxiv-mcp server. Then use that tool to retrieve the top 5 relevant papers for each topic, extract their abstracts, and produce a combined expert-level summary explaining: 1. what recursive transformers are, 2. how they compare to standard Transformers, and 3. current research directions. Return only the final consolidated summary."
      }
    ],
    "model": "gpt-5-mini",
    "provider": "openai",
    "mode": "code"
  }'
```
<details>
<summary>Logs</summary>

```bash
December 27, 2025 - 16:02:24 | INFO | [User: user123] MCP session initialized: W5WYPPB7VUFTN463F5IUFYSCK3
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:02:24 | INFO | [User: user123] Gateway returned 8 total tools
December 27, 2025 - 16:02:24 | INFO | [User: user123] Filtered to 8 tools (6 management + 2 user tools)
December 27, 2025 - 16:02:24 | INFO | [User: user123] ---> Iteration 1/10
December 27, 2025 - 16:02:26 | INFO | [User: user123] Calling tool: mcp-find
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:02:26 | INFO | 
[User: user123] 
[tool name]: mcp-find
[tool args]: {'query': 'arxiv'}

December 27, 2025 - 16:02:26 | INFO | [User: user123] Calling tool 'mcp-find' with Arguments: {'query': 'arxiv'}
December 27, 2025 - 16:02:26 | INFO | [User: user123] Tool 'mcp-find' executed successfully
December 27, 2025 - 16:02:26 | INFO | [User: user123] ---> Iteration 2/10
December 27, 2025 - 16:02:28 | INFO | [User: user123] Calling tool: mcp-add
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:02:28 | INFO | 
[User: user123] 
[tool name]: mcp-add
[tool args]: {'name': 'arxiv-mcp-server', 'activate': True}

December 27, 2025 - 16:02:28 | INFO | [User: user123] LLM requesting server 'arxiv-mcp-server'
December 27, 2025 - 16:02:28 | INFO | [User: user123] Calling tool 'mcp-add' with Arguments: {'name': 'arxiv-mcp-server', 'activate': True}
December 27, 2025 - 16:02:28 | INFO | [User: user123] Tool 'mcp-add' executed successfully
December 27, 2025 - 16:02:28 | WARNING | [User: user123] Server 'arxiv-mcp-server' requires config: ['storage_path']
INFO:     127.0.0.1:53778 - "POST /chat HTTP/1.1" 200 OK
```
</details>

<details>
<summary>Reponse</summary>

```json
{"interrupt_type":"config_required","server":"arxiv-mcp-server","required_configs":[{"key":"storage_path","type":"string","description":"Directory path where downloaded papers will be stored"}],"conversation_state":[{"role":"system","content":"You are a helpful assistant with access to MCP execution tools and the ability to create and run custom JavaScript/TypeScript logic via code-mode.\n\nAvailable capabilities (exposed to you in code mode):\n- `mcp-find`: Search for available MCP servers by query (e.g., \"github\", \"database\", \"file system\", \"wikipedia\").\n- `mcp-add`: Add and optionally activate a discovered MCP server. \n- `code-mode`: Request creation of a code-mode tool environment.\n- `mcp-exec`: Execute JavaScript/TypeScript code inside a code-mode environment.\n\nCode-mode workflow (how to request and use code-mode):\n1. When you need a capability or provider that is not currently available, call `mcp-find` with a concise, specific query describing the server or capability you need.\n2. Select the most appropriate server from the search results and call `mcp-add` to add (and activate) it.\n3. Request a `code-mode` environment by specifying:\n   - `name`: a unique name (the runtime will prefix it with `code-mode-`).\n   - `servers`: an explicit list of MCP servers to include.\n   - Do NOT include executable source code in the creation request.\n4. The runtime will return documentation describing:\n   - helper functions mapped from the selected MCP servers,\n   - function signatures and example usage.\n5. Use `mcp-exec` to execute JavaScript/TypeScript code:\n   - `name`: the code-mode tool name (e.g., `code-mode-my-tool`).\n   - `arguments.script`: your JS/TS code string calling the provided helper functions.\n6. The sandbox will execute the script and return results for use in answering the user's question.\n\nImportant server rules:\n- A server being mentioned by the user (e.g., \"using the arxiv-mcp server\")\n  does NOT mean the server is already available or active.\n- You MUST always verify server availability via the runtime state.\n- If you discover any available server from `mcp-find` tool prefer activating that server\n- If a mentioned server is not active, you MUST add it using `mcp-add`\n  before requesting `code-mode`.\n- You MUST NOT assume server availability based solely on user wording.\n\nBest practices:\n- Server discovery, secrets, and configuration MUST be completed by the runtime BEFORE creating `code-mode` environment.\n- Inspect the returned helper documentation before writing code.\n- Keep scripts short, focused, and deterministic.\n- Call only the helper functions you need.\n- Code-mode supports JavaScript/TypeScript only.\n"},{"role":"user","content":"Add the arxiv mcp server then create a custom tool that fetches recent arXiv papers about recursive transformers, tree-based attention architectures, and hierarchical sequence models using the arxiv-mcp server. Then use that tool to retrieve the top 5 relevant papers for each topic, extract their abstracts, and produce a combined expert-level summary explaining: 1. what recursive transformers are, 2. how they compare to standard Transformers, and 3. current research directions. Return only the final consolidated summary."},{"content":null,"refusal":null,"role":"assistant","annotations":[],"audio":null,"function_call":null,"tool_calls":[{"id":"call_xMgy28WAG5WsqlzIboL1Fn5r","function":{"arguments":"{\"query\":\"arxiv\"}","name":"mcp-find"},"type":"function"}]},{"tool_call_id":"call_xMgy28WAG5WsqlzIboL1Fn5r","role":"tool","name":"mcp-find","content":"{\"content\": [{\"type\": \"text\", \"text\": \"{\\\"query\\\":\\\"arxiv\\\",\\\"servers\\\":[{\\\"config_schema\\\":[{\\\"description\\\":\\\"Configure local storage path for downloaded papers\\\",\\\"name\\\":\\\"arxiv-mcp-server\\\",\\\"properties\\\":{\\\"storage_path\\\":{\\\"description\\\":\\\"Directory path where downloaded papers will be stored\\\",\\\"type\\\":\\\"string\\\"}},\\\"required\\\":[\\\"storage_path\\\"],\\\"type\\\":\\\"object\\\"}],\\\"description\\\":\\\"The ArXiv MCP Server provides a comprehensive bridge between AI assistants and arXiv's research repository through the Model Context Protocol (MCP).   Features: \\u2022 Search arXiv papers with advanced filtering \\u2022 Download and store papers locally as markdown \\u2022 Read and analyze paper content \\u2022 Deep research analysis prompts \\u2022 Local paper management and storage \\u2022 Enhanced tool descriptions optimized for local AI models \\u2022 Docker MCP Gateway compatible with detailed context  Perfect for researchers, academics, and AI assistants conducting literature reviews and research analysis.  **Recent Update**: Enhanced tool descriptions specifically designed to resolve local AI model confusion and improve Docker MCP Gateway compatibility.\\\",\\\"long_lived\\\":false,\\\"name\\\":\\\"arxiv-mcp-server\\\"},{\\\"description\\\":\\\"A MCP for searching and downloading academic papers from multiple sources like arXiv, PubMed, bioRxiv, etc.\\\",\\\"long_lived\\\":false,\\\"name\\\":\\\"paper-search\\\"}],\\\"total_matches\\\":2}\"}]}"},{"content":null,"refusal":null,"role":"assistant","annotations":[],"audio":null,"function_call":null,"tool_calls":[{"id":"call_OBixcwPj0C3NnTZt1oFASrn3","function":{"arguments":"{\"name\":\"arxiv-mcp-server\",\"activate\":true}","name":"mcp-add"},"type":"function"}]},{"tool_call_id":"call_OBixcwPj0C3NnTZt1oFASrn3","role":"tool","name":"mcp-add","content":"{\"status\": \"config_required\", \"required_configs\": [{\"key\": \"storage_path\", \"type\": \"string\", \"description\": \"Directory path where downloaded papers will be stored\"}]}"}],"active_servers":["duckduckgo"],"available_tools":["search","fetch_content"],"interrupt_id":"c7618d48-ae59-441f-8208-b13afcc84612","instructions":"Error: Cannot add server 'arxiv-mcp-server'. Missing required config (arxiv-mcp-server (missing)).\n\nThe server was not added. Please configure these first:\nRequired configuration: arxiv-mcp-server (missing)\nUse the mcp-config-set tool to configure these values."}
```
</details>


```bash
curl -X POST http://localhost:8000/chat/resume \
  -H "X-User-Id: user123" \
  -H "Content-Type: application/json" \
  -d '{
    "interrupt_id": "c7618d48-ae59-441f-8208-b13afcc84612",
    "provided_configs": {
      "storage_path": "/mnt/d/arxiv"
    }
  }'
```

<details>
<summary>Logs</summary>

```bash
December 27, 2025 - 16:25:09 | INFO | [User: user_123] MCP session initialized: KWO2HZAZLOD7DAHPTXWESFNHQ5
December 27, 2025 - 16:25:09 | INFO | [User: user_123] Retrying mcp-add for arxiv-mcp-server
December 27, 2025 - 16:25:09 | INFO | [User: user_123] Calling tool 'mcp-config-set' with Arguments: {'server': 'arxiv-mcp-server', 'key': 'storage_path', 'value': '/mnt/d/arxiv'}
December 27, 2025 - 16:25:09 | INFO | [User: user_123] Tool 'mcp-config-set' executed successfully
December 27, 2025 - 16:25:09 | INFO | [User: user_123] Adding server 'arxiv-mcp-server'
December 27, 2025 - 16:25:09 | INFO | [User: user_123] Calling tool 'mcp-add' with Arguments: {'name': 'arxiv-mcp-server', 'activate': True}
December 27, 2025 - 16:25:12 | INFO | [User: user_123] Tool 'mcp-add' executed successfully
December 27, 2025 - 16:25:12 | INFO | [User: user_123] Gateway returned 10 total tools
December 27, 2025 - 16:25:12 | INFO | [User: user_123] Server 'arxiv-mcp-server' added with 4 tools: ['download_paper', 'list_papers', 'read_paper', 'search_papers']
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:25:12 | INFO | [User: user_123] Gateway returned 10 total tools
December 27, 2025 - 16:25:12 | INFO | [User: user_123] Filtered to 10 tools (6 management + 4 user tools)
December 27, 2025 - 16:25:12 | INFO | [User: user_123] ---> Iteration 3/20
December 27, 2025 - 16:25:14 | INFO | [User: user_123] Calling tool: code-mode
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:25:14 | INFO | 
[User: user_123] 
[tool name]: code-mode
[tool args]: {'name': 'code-mode-arxiv-search', 'servers': ['arxiv-mcp-server'], 'timeout': 120}

December 27, 2025 - 16:25:14 | INFO | [User: user_123] Calling tool 'code-mode' with Arguments: {'name': 'code-mode-arxiv-search', 'servers': ['arxiv-mcp-server'], 'timeout': 120}
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Tool 'code-mode' executed successfully
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Gateway returned 11 total tools
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Added dynamic tool 'code-mode-code-mode-arxiv-search' 
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Gateway returned 11 total tools
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Filtered to 10 tools (6 management + 5 user tools)
December 27, 2025 - 16:25:15 | INFO | [User: user_123] Tools refreshed, now have 10 tools
December 27, 2025 - 16:25:15 | INFO | [User: user_123] ---> Iteration 4/20
December 27, 2025 - 16:25:21 | INFO | [User: user_123] Calling tool: mcp-exec
Authentication error: Langfuse client initialized without public_key. Client will be disabled. Provide a public_key parameter or set LANGFUSE_PUBLIC_KEY environment variable. 
December 27, 2025 - 16:25:21 | INFO | 
[User: user_123] 
[tool name]: mcp-exec
December 27, 2025 - 16:25:21 | INFO | [User: user_123] Calling tool 'mcp-exec' with Arguments: {'name': 'code-mode-code-mode-arxiv-search', 'arguments': {'script': '// Search queries for three topics and return top 5 results each with id, title, authors, abstract\nfunction runQuery(query, categories, max_results) {\n  const args = { query: query, categories: categories, max_results: max_results };\n  const res = search_papers(args);\n  return res;\n}\n\n// 1. Recursive transformers\nconst q1 = \'"recursive transformer" OR "recursive transformers" OR "hierarchical transformer" OR "tree transformer" OR "tree-based transformer"\';\nconst r1 = runQuery(q1, [\'cs.LG\',\'cs.CL\'], 5);\n\n// 2. Tree-based attention architectures\nconst q2 = \'"tree-based" AND (transformer OR attention) OR "tree attention" OR "tree attention" architecture\';\nconst r2 = runQuery(q2, [\'cs.LG\',\'cs.CL\'], 5);\n\n// 3. Hierarchical sequence models\nconst q3 = \'"hierarchical sequence" OR "hierarchical model" AND (transformer OR attention) OR "hierarchical transformer"\';\nconst r3 = runQuery(q3, [\'cs.LG\',\'cs.CL\'], 5);\n\nreturn JSON.stringify({recursive: r1, tree_attention: r2, hierarchical: r3});'}}
December 27, 2025 - 16:25:41 | INFO | [User: user_123] Tool 'mcp-exec' executed successfully
December 27, 2025 - 16:25:41 | INFO | [User: user_123] ---> Iteration 5/20
INFO:     127.0.0.1:42110 - "POST /chat/resume HTTP/1.1" 200 OK
```
</details>

<details>
<summary>Reponse</summary>

```json
{
	"content": "Recursive Transformers — what they are\n- Recursive transformers are architectures that explicitly reuse a small set of Transformer parameters by iterating the same block (or small block stack) multiple times over a hidden state, decoupling parameter depth from compute depth. Instead of stacking many distinct layers, a single “core” (or a small group of cores) is applied recurrently; the model’s effective depth is the number of iterations rather than the count of unique layer parameters. Architecturally this looks like looped application of attention+FFN blocks, sometimes augmented with small per-iteration modulators (e.g., LoRA adapters), external memory buffers, or routing mechanisms. Variants include:\n  - Strict layer tying (one block repeated), and “relaxed” forms that add low-cost per-iteration adaptation (depth-wise LoRA, mixtures-of-adapters) to restore expressivity.\n  - Tree- or composition-driven recursive designs that apply recurrence according to an induced syntactic or binary tree (differentiable CKY-style composition), producing hierarchical abstractions rather than uniform iterations.\n  - Vision-oriented sliced-recursive instantiations that share weights across many effective depths while approximating attention to control compute.\n- Intuitively, recursion forces the model to perform iterative refinement or composition with a compact parameter core. That makes the same parameters do different computational “roles” at different iterations (ideally), enabling extreme parameter compression while retaining the ability to perform deep computation.\n\nHow recursive transformers differ from (and compare with) standard Transformers\n- Parameterization vs compute:\n  - Standard Transformer: many distinct layers (each with its own parameters). Effective depth = number of layers; parameters scale linearly with depth.\n  - Recursive Transformer: few (often one) unique layer(s) reused; effective depth is number of recurrences; parameters are compressed via sharing. This yields much smaller parameter counts for a given effective depth.\n- Expressivity and optimization trade-offs:\n  - Pro: Parameter sharing gives much better parameter efficiency (smaller models that can still perform deep computation). Empirically, well-designed recursive models can match or exceed same-sized vanilla models on many tasks and sometimes approach the performance of much larger full-parameter models.\n  - Con: Naive parameter sharing can collapse expressivity — the shared core can be forced into an “undifferentiated” computation repeated each iteration, which limits capacity compared to a stack of different layers. This appears in empirical gaps under matched compute budgets unless mitigations are used.\n- Sources of the performance gap and remedies:\n  - Undifferentiated computation: repeated application of an identical transform may fail to specialize across iterations. Remedies include lightweight per-iteration modulators (depth-wise LoRA, Mixture-of-LoRAs/expert adapters), conditional computation (token- or iteration-conditioned modulation), and routers that diversify computation across iterations.\n  - Information overload: when one hidden state must carry both long-lived memory and transient signals, capacity and routing problems arise. Solutions include externalizing state into explicit memory buffers or highways (Memory-as-State-Highways) and adding lightweight routing between memory and core so iterations can specialize.\n  - Initialization and optimization: converting pretrained non-recursive models into recursive ones requires careful initialization or distillation to avoid collapse; distillation-based initializations and modernized training recipes (rotary embeddings, GeGLU, FlashAttention) help.\n- Computation & latency considerations:\n  - Recurrence increases the amount of sequential compute for a forward pass if iterations are executed serially, which can raise latency; but recursion enables new inference strategies (early exiting, continuous depth-wise batching) and hardware/algorithmic optimizations that can yield significant throughput gains in practice (e.g., reported 2–3× throughput improvements when paired with early-exit mechanisms and batching strategies).\n  - For tree-structured or hierarchical workloads (multi-call decoding trees, structured physical simulations), specialized tree-aware attention and KV-cache partitioning algorithms can substantially reduce redundant memory I/O and improve throughput (e.g., prefix-aware KV grouping, Flattened Tree KV Splitting).\n- Complexity of attention:\n  - Standard dense self-attention is quadratic in sequence length; many hierarchical/tree-based or ball-tree methods replace global quadratic attention with structured, locality- or hierarchy-aware computation to obtain near-linear scaling while retaining cross-scale interactions. Those methods can be applied inside recursive cores or in hierarchical models that combine local and global processing.\n- Empirical profile:\n  - On NLP benchmarks (GLUE, SQuAD), compact recursive designs with corrective mechanisms can outcompete traditional compact models and sometimes approach larger fully parameterized baselines.\n  - In vision and other modalities, sliced-recursive and hierarchical tree-based approaches have shown gains in parameter efficiency and allows extremely deep effective depths with small parameter costs.\n\nCurrent research directions (what the literature is exploring now)\n1. Restoring/maintaining expressivity under aggressive sharing\n   - Depth-wise low-rank adapters and LoRA-based modulators: add small per-iteration parameterizations to allow the core to behave differently at different iterations while keeping total parameters low.\n   - Mixture-of-LoRAs / conditional expert modules: token- or context-conditioned modulation of a shared FFN to recover layerwise diversity without fully untying parameters. Research also focuses on merging experts at inference time (expert-merging) to reduce runtime overhead.\n   - Router and dynamic specialization: lightweight routers and token-conditional mechanisms that route computation or memory access across iterations for specialization.\n2. Memory and state compartmentalization\n   - External memory buffers or “state highways” that separate transient iteration-level signals from longer-lived information; this reduces interference and enables specialized roles across iterations.\n   - Analysis and probing to identify how hidden states evolve across iterations and how to induce functional specialization in iterative cores.\n3. Initialization, distillation and training recipes\n   - Methods to convert pretrained non-recursive models to recursive ones with minimal performance loss (distillation-based initialization, modernized training primitives like rotary embeddings, GeGLU, FlashAttention).\n   - Pretraining curricula and loss functions adapted to iterative/compositional processing, including objectives that encourage different iterations to perform complementary computations.\n4. Efficient inference algorithms and hardware-aware optimizations\n   - Inference paradigms that exploit the recursion structure: continuous depth-wise batching, early exiting, and batching strategies that enable high throughput.\n   - Tree-aware KV cache partitioning and GPU-efficient attention for tree-structured decoding and multi-branch generation, drastically reducing KV I/O and increasing GPU utilization.\n   - Linear-time attention via spatial/tree partitioning (ball-tree, progressive coarsening) for large-scale physical systems and other irregular grids where pairwise attention is infeasible.\n5. Hierarchical and structure-aware recursion\n   - Differentiable tree-composition models: CKY-like differentiable induction to build hierarchical representations and perform composition in a tree-shaped recurrence rather than fixed uniform iterations — useful for parsing-style composition and more interpretable abstraction hierarchies.\n   - Multi-scale hierarchical transformers that combine fine-grained local attention with coarser global passes for long documents, multi-document summarization, tabular time-series (row/field hierarchies), and physical simulations.\n6. Modality- and task-specific instantiations\n   - Vision: sliced recursion and grouped self-attention to scale effective depth with few parameters while controlling compute and approximation error.\n   - Code and structured data: tree-based encoders that incorporate AST structure and grammar rules using attention over nodes to better capture program structure and long-range dependencies.\n   - Scientific/physical systems: hierarchical tree transformers using spatial partitioning (ball tree) to get linear-time attention while capturing multi-scale interactions.\n7. Interpretability, probing, and theory\n   - Empirical probes revealing iteration specialization patterns and attribution of performance gaps to undifferentiated iteration behavior or information mixing.\n   - Theoretical analyses of throughput/latency tradeoffs enabled by recursive designs and of the representational capacity of shared vs. unshared layers.\n8. Compression & deployment\n   - Combining recursion with adapter-based adaptation, expert merging, and low-rank compression to build deployable compact LLMs that preserve most of a larger model’s capabilities.\n   - Strategies for merging learned conditional modules for inference efficiency while keeping training-time flexibility.\n\nPractical takeaways and design guidance\n- If the goal is parameter efficiency (fit a deep effective model into a small parameter budget), recursive transformers are a strong option, but they must include mechanisms to restore iteration-specific expressivity (LoRA adapters, MoL, routers, memory highways) or use careful initialization/distillation.\n- For tasks with hierarchical structure (language composition, code ASTs, long documents, physical systems), combining recursion with tree/coarsening-aware architectures often yields both computational and representational benefits.\n- For deployment, pair recursive architectures with inference strategies that exploit repetition (early exit, continuous batching) and with algorithmic attention optimizations (tree-aware KV caching, partitioning) to avoid latency penalties from serial recurrence.\n- Open challenges remain in robust training across scales, principled routing/specialization mechanisms, and theoretical understanding of the expressivity vs. efficiency frontier.\n\nShort synthesis\nRecursive transformers are an explicit, principled way to trade unique-parameter depth for iterative computation: they compress parameters by reusing a core while achieving deep computation via multiple passes. That compression introduces predictable failure modes (loss of layerwise specialization and information-mixing bottlenecks), and current research is converging on a small set of effective remedies—lightweight per-iteration adaptation (LoRA-style modules and mixtures), externalized memory and routers to separate roles across iterations, careful initialization/distillation, and inference- and hardware-aware algorithms that exploit the structure (KV reuse, tree partitioning, batching schemes). Combined with hierarchical, tree-structured, or multi-scale attention algorithms, recursive designs promise highly parameter- and compute-efficient models that scale to long contexts and structured modalities; the active frontier is how best to restore the lost expressivity and make these methods robust, interpretable, and deployable at scale.",
	"active_servers": [
		"arxiv-mcp-server",
		"code-mode:code-mode-arxiv-search"
	],
	"available_tools": [
		"list_papers",
		"code-mode-arxiv-search",
		"read_paper",
		"search_papers",
		"download_paper"
	],
	"finish_reason": "stop"
}
```
</details>

### `POST /mcp/add`

**Example `curl` command (to add a server):**
```bash
curl -X POST http://localhost:8000/mcp/add \
  -H "X-User-Id: user123" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "arxiv-mcp-server",
    "activate": true,
    "config": {
      "storage_path": "/mnt/d/arxiv"
    }
  }'
```

### `GET /mcp/remove`

**Example `curl` command (to remove a server):**
```bash
curl -X POST http://localhost:8000/mcp/remove \
  -H "X-User-Id: user123" \
  -H "Content-Type: application/json" \
  -d '{"name": "arxiv-mcp-server"}'
```

**Other Endpoints:**
-   `POST /sse/chat/resume`: Resume a streaming chat conversation after a configuration interrupt.
-   `POST /mcp/find`: Discover available MCP servers.
-   `GET /mcp/servers`: List currently active MCP servers and available tools.

---

## 🔧 The CLI

A command-line interface (`cli/`) is included primarily for testing, debugging, and direct interaction with the MCP Bridge. It's a great way to experiment with the system's capabilities.

```bash
# Install & Run the CLI chat
git clone https://github.com/Sagnnik/docker-mcp-bridge.git
cd docker-mcp-bridge
uv sync
docker compose -f docker-compose.cli.yaml up -d
cd cli
uv run cli_chat.py
```

### Features

- **Interactive Chat**: Chat with an AI that can use tools.
- **MCP Server Management**: Find, add, and remove MCP servers.
- **Tool Discovery**: List available tools from active MCP servers.
- **AI Configuration**: Configure the AI provider (OpenAI, Anthropic, Google, Ollama) and model.
- **Shell Command Execution**: Run shell commands directly in the CLI.
- **Rich Terminal UI**: A user-friendly interface built with `rich` and `questionary`.

### Commands

-   `/help`: Show available commands.
-   `/config`: Configure the LLM provider, model, and other settings.
-   `/add`: Search for and add MCP servers.
-   `/find <query>`: Search for specific servers.
-   `/list`: Show active servers and available tools.
-   `/remove`: Remove a server.
-   `!<command>`: Execute a shell command (e.g., `!ls -l`).
-   `/exit`: Exit the CLI.

## ⚙️ Configuration

All configuration is managed via environment variables in `api/.env`. Key variables include:

-   `OPENAI_API_KEY`: Your API key for OpenAI.
-   `OPENROUTER_API_KEY`: Your API key for OpenRouter.

## 🚧 Upcoming Updates
1. Support for other llm providers
	  - Ollama and Anthropic are next on the list
2. Custom span for langfuse
3. Support for custom mcp catalog and setting up custom mcp servers
4. Resource manager with monitoring (issue: GLM 4.7 just ran for 10+ mins for crawling arxiv mcp)
	  - Something to prevent infinite/recursive agent loops with hard stop
	  - CPU and memory quota
	  - Disk quota
	  - Network monitoring
5. Token and context management
    - Context manager for long running agent loop only
<details>
<summary> Extra </summary>

6. [Maybe]  Test better System Prompts
7. [Maybe] Train and add a smart router model - 
```text
intent:
  - chat
  - code
  - search
  - summarization
  - reasoning

routing:
  - is_non_mcp_request: boolean

capabilities:
  - needs_dynamic_mcp   (bool)
  - needs_code_mode     (bool)
  - needs_web           (bool)
  - needs_long_context  (bool)

performance:
  - latency_priority: fast | balanced | quality
```

</details>

## 🙌 Contributing

This project is still under active development, and I’m sure everyone will have their own ideas to improve it. **All contributions are welcome and greatly appreciated.**

1. **Fork the project**
2. **Install dependencies**
    - Run `uv sync` for the full workspace
    - Or, for an individual workspace:
      ```bash
      uv sync --package <api|cli>
      ```
3.  **Explore the codebase.**
    - If you’re not sure where to start, check out the `exp/` folder — it contains early experiments and prototypes that are easier to dive into.
    - Also look into the my Upcoming updates if you have any ideas to improve upon then you are welcome to add
4.  **Create a new branch**, make your changes, then commit and push them.
5.  **Open a pull request**, and I’ll review it as soon as I can.

Whether it’s a bug fix, documentation improvement, performance tweak, or a new idea — every contribution helps move the project forward 🚀

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.
<p>
  <a href="https://opensource.org/licenses/MIT">
    <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT">
  </a>
  <!-- Add other badges here if you have them, e.g., build status, code coverage -->
</p>