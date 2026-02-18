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

## Running tests

Run MCP tests with `pytest`:

```shell
python -m pytest -q
```

## Docker

Build (from repository root so the shared package is included):

```shell
docker build -f mcp/Dockerfile -t lighthouse-mcp:dev .
```

Run:

```shell
docker run --rm -p 8000:8000 --env-file mcp/.env lighthouse-mcp:dev
```

Session endpoints are also exposed as MCP tools at **`./tools`** via [fastapi-mcp](https://fastapi-mcp.tadata.com/) (tools/list, tools/call over SSE/streamable-http).

**MCP client config** (e.g. Cursor, Codex, Claude Desktop). Add to your MCP config (e.g. `mcp.json` or Cursor MCP settings):
```json
{
  "mcpServers": {
    "lighthouse": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${GITHUB_READ_TOKEN}"
      }
    }
  }
}
```
If your client expects a transport type explicitly: use `"type": "streamable-http"` or `"type": "sse"` with the same `url` when the client supports it.

The GitHub token header is optional and primarily relevant for private-repo-capable flows.
For clients that do not support `Authorization` header templates, you can use `X-GitHub-Token` instead.
The MCP server never logs token values.
Current first-iteration behavior supports one token value per request; per-repo multi-token routing is a planned follow-up.

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
