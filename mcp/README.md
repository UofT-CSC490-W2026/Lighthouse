# Lighthouse MCP Service

## Setup

1. **Create a virtual environment with [uv](https://docs.astral.sh/uv/pip/environments/):**
   ```shell
   uv venv
   ```
   Optionally specify a path (e.g. `uv venv .venv`) or Python version (e.g. `uv venv --python 3.12`). With the default name, uv will automatically use `.venv` in this directory for later commands.

2. **Install dependencies:**
   ```shell
   uv pip install -r requirements.txt
   ```

3. **Configure environment variables:** copy the example env file and set the required values:
   ```shell
   cp .env.example .env
   ```

## Running the server

Run the server with `uvicorn`:

```shell
uvicorn src.server:app --reload --host 0.0.0.0 --port 8000 --env-file .env
```

Session endpoints are also exposed as MCP tools at **`./tools`** via [fastapi-mcp](https://fastapi-mcp.tadata.com/) (tools/list, tools/call over SSE/streamable-http).

**MCP client config** (e.g. Cursor, Codex, Claude Desktop). Add to your MCP config (e.g. `mcp.json` or Cursor MCP settings):
```json
{
  "mcpServers": {
    "lighthouse": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```
If your client expects a transport type explicitly: use `"type": "streamable-http"` or `"type": "sse"` with the same `url` when the client supports it.

**Test the MCP server** with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector). You need [Node.js](https://nodejs.org/) and `npx` (included with npm) to run the inspector.

1. Start this service: `uvicorn src.server:app --reload --host 0.0.0.0 --port 8000 --env-file .env`
2. In another terminal, run the inspector and connect to the MCP URL:
   ```shell
   npx @modelcontextprotocol/inspector
   ```
   Open the UI at http://localhost:6274, then connect to **Streamable HTTP** with URL `http://localhost:8000/mcp`. Or open directly:
   ```
   http://localhost:6274/?transport=streamable-http&serverUrl=http://localhost:8000/mcp
   ```
3. In the inspector you can list tools and call them (e.g. init, develop, query) with JSON arguments.
