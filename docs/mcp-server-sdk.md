# MCP Python SDK Reference - Building Servers
**Version**: 1.26.0 (January 2026) | **Updated**: 2026-03-14

## Quick Reference

| Task | Method |
|------|--------|
| Create server | `from mcp.server.fastmcp import FastMCP; mcp = FastMCP("Name")` |
| Add tool | `@mcp.tool()` decorator on function with type hints |
| Define parameters | Use Python function parameters with type annotations (`a: int`, `b: str = "default"`) |
| Return structured data | Return Pydantic model, dataclass, or primitive type (auto-wrapped) |
| Serve to Claude Desktop | `mcp.run(transport="stdio")` + configure `claude_desktop_config.json` |
| Run for development | `mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)` |

## Installation

```bash
# Using uv (recommended for Python projects)
uv add "mcp[cli]"

# Using pip
pip install "mcp[cli]"
```

**Requirements**: Python >=3.10, MIT License

## Core Concepts

### MCP Server Components

1. **Tools**: Functions that LLMs can call to perform actions. Automatically generate JSON schemas from type hints.
2. **Resources**: File-like data endpoints (similar to GET) that clients can read.
3. **Prompts**: Reusable interaction templates with parameters.

This guide focuses on **Tools**, which are the primary way to expose functions to Claude.

## Creating a Simple MCP Server with FastMCP

### Basic Structure

```python
from mcp.server.fastmcp import FastMCP

# Create server instance
mcp = FastMCP(
    name="MyServer",
    description="What this server does",
    instructions="How Claude should use these tools"
)

# Define a tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b

# Run the server
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

### FastMCP vs MCPServer

**FastMCP** (modern, recommended):
- Lightweight decorator-based API
- Handles parameter extraction from function signatures automatically
- Cleaner syntax for simple use cases

**MCPServer** (legacy):
- More explicit control
- Same decorator pattern
- Slightly more verbose initialization

This guide uses **FastMCP** unless otherwise noted.

## Defining Tools with Parameters

### Type Annotations Drive Schema Generation

The MCP Python SDK automatically generates JSON schemas from Python type hints. This is the core mechanism for defining tool parameters.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Calculator")

# Simple parameters with type hints
@mcp.tool()
def calculate(
    a: int,
    b: int,
    operation: str = "add"  # Default = optional parameter
) -> int:
    """Perform math operations."""
    if operation == "add":
        return a + b
    elif operation == "subtract":
        return a - b
    elif operation == "multiply":
        return a * b
    return 0
```

**Generated Schema** (automatically created):
```json
{
  "name": "calculate",
  "description": "Perform math operations.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "a": { "type": "integer" },
      "b": { "type": "integer" },
      "operation": {
        "type": "string",
        "default": "add"
      }
    },
    "required": ["a", "b"]
  }
}
```

### Supported Parameter Types

| Python Type | JSON Schema Type | Notes |
|-------------|-----------------|-------|
| `int` | integer | 32-bit or 64-bit int |
| `float` | number | IEEE 754 double |
| `str` | string | Unicode text |
| `bool` | boolean | True/False |
| `list[T]` | array | Homogeneous list of type T |
| `dict[str, T]` | object | Key-value pairs |
| `Optional[T]` | T with null | Can be None |
| Enum | string (constrained) | Pre-defined values |
| `dataclass` | object | Structured type with fields |
| `TypedDict` | object | Dictionary with typed keys |

### Using Pydantic Models for Complex Types

For validated, structured parameters:

```python
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("UserAPI")

class UserInput(BaseModel):
    name: str
    email: str
    age: int = Field(ge=0, le=150, description="Must be 0-150")
    tags: list[str] = Field(default_factory=list)

@mcp.tool()
def create_user(user: UserInput) -> dict:
    """Create a new user with validation."""
    return {
        "id": 123,
        "name": user.name,
        "email": user.email,
        "age": user.age,
        "tags": user.tags
    }
```

Claude receives the full validation rules (min/max, regex patterns, descriptions) in the schema and can use them to construct valid inputs.

### Using Python Dataclasses

Similar to Pydantic but without runtime validation:

```python
from dataclasses import dataclass
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DataTools")

@dataclass
class Point:
    x: float
    y: float

@mcp.tool()
def distance(p1: Point, p2: Point) -> float:
    """Calculate Euclidean distance between two points."""
    return ((p2.x - p1.x)**2 + (p2.y - p1.y)**2) ** 0.5
```

## Return Types and Output Schemas

### Primitive Returns (Auto-Wrapped)

Primitive types are automatically wrapped in a result object:

```python
@mcp.tool()
def greet(name: str) -> str:
    """Generate a greeting."""
    return f"Hello, {name}!"

# Claude receives: {"result": "Hello, Alice!"}
```

### Structured Returns with Pydantic

For validated output schemas:

```python
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Weather")

class WeatherInfo(BaseModel):
    city: str
    temp_celsius: float
    condition: str
    humidity: float  # 0-100

@mcp.tool()
def get_weather(city: str) -> WeatherInfo:
    """Get current weather for a city."""
    return WeatherInfo(
        city=city,
        temp_celsius=22.5,
        condition="Partly cloudy",
        humidity=65.0
    )
```

Claude receives structured, validated output that can be used in subsequent processing.

### Dictionary/Object Returns

```python
@mcp.tool()
def analyze_text(text: str) -> dict:
    """Analyze text and return metrics."""
    return {
        "length": len(text),
        "words": len(text.split()),
        "sentences": text.count(".") + text.count("!") + text.count("?")
    }
```

## Advanced: Context and LLM Integration

### Accessing Tool Context

Tools can receive a `Context` parameter to access MCP session capabilities:

```python
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession

mcp = FastMCP("LLMIntegration")

@mcp.tool()
async def generate_poem(topic: str, ctx: Context[ServerSession, None]) -> str:
    """Generate a poem using LLM sampling."""
    from mcp.types import SamplingMessage, TextContent

    prompt = f"Write a short, creative poem about {topic}"

    result = await ctx.session.create_message(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=prompt),
            )
        ],
        max_tokens=100,
    )

    if result.content.type == "text":
        return result.content.text
    return str(result.content)
```

### Progress Reporting

Report progress for long-running operations:

```python
@mcp.tool()
async def process_dataset(
    size: int,
    ctx: Context[ServerSession, None]
) -> str:
    """Process a large dataset with progress updates."""
    for i in range(size):
        await ctx.report_progress(progress=i, total=size)
        # Do work...
    return f"Processed {size} items"
```

## Claude Desktop Integration

### Configuration File Format

Claude Desktop launches MCP servers as **stdio child processes** (only supported transport for Claude Desktop).

Edit `claude_desktop_config.json`:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Linux** (preview): `~/.config/claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Stdio Server Configuration

```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "python",
      "args": ["/path/to/server.py"]
    },
    "another-server": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "/path/to/server.py"],
      "env": {
        "LOG_LEVEL": "DEBUG"
      }
    }
  }
}
```

### Key Requirements for Stdio Servers

1. **Never write to stdout**: All output on stdout corrupts JSON-RPC messages. Use stderr for logging only (via `logging` module).
2. **Use absolute paths**: Always use full paths for commands and scripts.
3. **Environment variables**: Pass via `env` object in config, not inline.
4. **Restart Claude**: Close entirely (including system tray/Task Manager) after config changes.

### Example: Python Project Setup

**Directory structure**:
```
my-mcp-server/
├── pyproject.toml
├── src/
│   └── my_server.py
└── .python-version
```

**pyproject.toml**:
```toml
[project]
name = "my-mcp-server"
version = "0.1.0"

[project.optional-dependencies]
mcp = ["mcp[cli]>=1.26.0"]
```

**src/my_server.py**:
```python
#!/usr/bin/env python3
"""MCP server example."""
import logging
from mcp.server.fastmcp import FastMCP

# Use logging for debug output (goes to stderr, not stdout)
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

mcp = FastMCP("MyServer")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    logger.debug(f"Adding {a} + {b}")  # Safe: goes to stderr
    return a + b

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**claude_desktop_config.json**:
```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--chdir", "/absolute/path/to/my-mcp-server", "src/my_server.py"]
    }
  }
}
```

## Running MCP Servers

### For Development (Streamable HTTP)

```python
if __name__ == "__main__":
    # Serves on localhost:8000 with live reloading
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
```

Access the server at `http://localhost:8000` during development.

### For Claude Desktop (Stdio)

```python
if __name__ == "__main__":
    # Runs in stdio mode - Claude Desktop will control it
    mcp.run(transport="stdio")
```

Configure in `claude_desktop_config.json` as shown above.

### Server Initialization Options

```python
mcp = FastMCP(
    name="MyServer",
    description="What this server does",
    instructions="How Claude should use these tools",
    json_response=True,  # Return JSON responses
    debug=True,          # Enable debug logging
    log_level="INFO"     # Logging level
)
```

## Best Practices

### 1. Tool Design

**DO**:
- Name tools for their primary action (`get_weather`, `create_issue`, `list_files`)
- Write clear docstrings - first line is a short description, used in Claude's tool list
- Use type hints for all parameters and return values
- Keep tools focused on a single capability

**DON'T**:
- Create tools that return massive datasets - paginate or provide filtering
- Use print() for output - use logging.debug() instead
- Store state in global variables - pass state through parameters
- Make tools with side effects that aren't documented in their docstring

### 2. Parameter Design

**DO**:
- Use meaningful default values for optional parameters
- Validate inputs within tools (or use Pydantic models)
- Provide clear descriptions in Pydantic Field() definitions
- Use enums for constrained choice parameters

```python
from enum import Enum
from pydantic import BaseModel, Field

class SortOrder(str, Enum):
    ASC = "ascending"
    DESC = "descending"

class SearchParams(BaseModel):
    query: str
    sort: SortOrder = SortOrder.ASC
    limit: int = Field(default=10, ge=1, le=100)

@mcp.tool()
def search(params: SearchParams) -> list[str]:
    """Search with validated parameters."""
    ...
```

**DON'T**:
- Use generic parameter names like `data`, `args`, `config`
- Mix required and optional parameters without clear patterns
- Accept dictionary inputs when structured types would be clearer

### 3. Error Handling

**DO**:
- Raise exceptions with clear messages
- Log errors for debugging (use logging module)
- Return error information in the response (when appropriate)

```python
@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

**DON'T**:
- Return error strings - raise exceptions instead
- Print error messages - log them with `logging.error()`
- Silently fail on invalid input

### 4. Logging Instead of Print

```python
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG)

@mcp.tool()
def process(data: str) -> str:
    """Process data."""
    logger.debug(f"Processing: {data}")
    try:
        result = do_work(data)
        logger.info(f"Success: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed: {e}")
        raise
```

All logging goes to stderr; stdout remains reserved for JSON-RPC protocol messages.

### 5. Documentation and Discoverability

**Tool docstrings** should:
1. Be concise (one-sentence summary first)
2. Explain what the tool does and when Claude should use it
3. Describe any important side effects or prerequisites

```python
@mcp.tool()
def delete_file(path: str) -> bool:
    """Permanently delete a file at the given path. Warning: this cannot be undone."""
    ...
```

**Pydantic Field descriptions**:
```python
class FileOperation(BaseModel):
    path: str = Field(description="Absolute file path")
    force: bool = Field(default=False, description="Skip safety checks")
```

## Common Patterns

### Pattern: Query with Filtering and Pagination

```python
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("DatabaseAPI")

class QueryOptions(BaseModel):
    query: str = Field(description="Search term")
    limit: int = Field(default=10, ge=1, le=100, description="Results per page")
    offset: int = Field(default=0, ge=0, description="Number of results to skip")

@mcp.tool()
def search_database(options: QueryOptions) -> dict:
    """Search the database with pagination."""
    # Simulate database query
    total = 250
    results = [f"Result {i}" for i in range(options.offset, min(options.offset + options.limit, total))]
    return {
        "results": results,
        "total": total,
        "offset": options.offset,
        "limit": options.limit,
        "has_more": options.offset + options.limit < total
    }
```

**Use Case**: Large datasets where Claude needs to refine queries progressively.

### Pattern: State-Modifying Operation with Dry Run

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Operations")

@mcp.tool()
def apply_patch(
    target: str,
    patch_content: str,
    dry_run: bool = True
) -> dict:
    """Apply a patch to a file. Use dry_run=True to preview changes first."""
    if dry_run:
        return {
            "status": "preview",
            "would_modify": target,
            "changes_count": patch_content.count("\n")
        }
    else:
        # Apply the patch
        return {
            "status": "applied",
            "modified_file": target,
            "timestamp": "2026-03-14T10:30:00Z"
        }
```

**Use Case**: Destructive operations where Claude should verify before committing.

### Pattern: Async Tool with External API Call

```python
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("WeatherAPI")

@mcp.tool()
async def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.weatherapi.com/v1/current.json",
            params={"q": city, "key": "YOUR_API_KEY"}
        )
        data = response.json()
        return {
            "city": city,
            "temperature": data["current"]["temp_c"],
            "condition": data["current"]["condition"]["text"]
        }

if __name__ == "__main__":
    mcp.run(transport="stdio")
```

**Use Case**: Tools that call external APIs or perform I/O operations.

## Troubleshooting

### Server Fails to Start in Claude Desktop

**Symptom**: "Service failed to start" error in Claude Desktop.

**Solutions**:
1. **Restart Claude fully**: Close Claude Desktop, terminate any background processes (Task Manager/Activity Monitor), reopen.
2. **Check the config path**: Ensure `claude_desktop_config.json` is in the correct location.
3. **Verify paths are absolute**: All `command` and `args` paths must be fully qualified.
4. **Test the command manually**: Run the server command in a terminal to see actual error messages.
5. **Check stderr logs**: If server prints debug info, it goes to stderr (check system logs).

### Tools Not Appearing in Claude

**Symptom**: Server connects but tools don't show up.

**Solutions**:
1. **Verify @mcp.tool() decorator**: Tools without the decorator won't be registered.
2. **Check docstrings**: Tools without docstrings may not be listed.
3. **Use /mcp command**: In Claude Code, use `/mcp` to check server status and available tools.
4. **Check MCP tool search**: If you have many tools, Claude Code may defer loading them (see Context7 docs).

### "Connection closed" or "spawn... ENOENT"

**Symptom**: Stdio connection fails immediately on Windows.

**Solution**: Windows requires `cmd /c` wrapper for npx/npm commands:
```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "cmd",
      "args": ["/c", "uv", "run", "server.py"]
    }
  }
}
```

### Tool Parameter Validation Failures

**Symptom**: Claude Code says parameter types don't match.

**Solutions**:
1. **Use Pydantic for complex types**: Ensures schema is valid.
2. **Check type annotations**: Missing or incorrect type hints cause schema generation to fail.
3. **Use Field() for constraints**: Pydantic Field() defines min/max, regex, descriptions.

## Resources

- **Official GitHub**: [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
- **PyPI Package**: [mcp](https://pypi.org/project/mcp/)
- **MCP Specification**: [modelcontextprotocol.io](https://modelcontextprotocol.io)
- **Claude Desktop Guide**: [support.claude.com - Getting Started with Local MCP Servers](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)
- **Claude Code MCP Docs**: [code.claude.com/docs/en/mcp](https://code.claude.com/docs/en/mcp)
- **Quickstart Example**: [github.com/modelcontextprotocol/quickstart-resources](https://github.com/modelcontextprotocol/quickstart-resources)
