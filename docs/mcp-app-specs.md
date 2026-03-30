# MCP App Specs Reference
**Version**: 2026-01 | **Updated**: 2026-03-14

## Quick Reference

MCP Apps is an official Model Context Protocol extension enabling tools to render interactive HTML interfaces (dashboards, visualizations, forms) directly in Claude Desktop, Claude.ai, VS Code, and other compatible clients. Tools declare UI resources via `_meta.ui.resourceUri` or return Prefab components, and hosts render them in sandboxed iframes.

**Key Benefits**: Context preservation (UI stays in chat), bidirectional communication (app calls tools), security (iframe sandbox with deny-by-default CSP), integration (app calls existing MCP tools).

## Core Concepts

### What is an MCP App?

An MCP App extends the core MCP protocol to let tools return rich interactive interfaces instead of plain text. When a tool declares a UI resource, the host:

1. Preloads the resource before the tool is called
2. Fetches the HTML/JavaScript from the server
3. Renders it in a sandboxed iframe within the chat
4. Enables bidirectional JSON-RPC communication over `postMessage`

### Why Use MCP Apps vs. Web Apps?

| Aspect | MCP App | Web App |
|--------|---------|---------|
| **Context** | Lives in conversation alongside discussion | Separate tab, loses context |
| **Data Flow** | Bidirectional via MCP tools | Own API + auth + state management |
| **Integration** | Calls existing user-connected MCP tools | Must reimplement integrations |
| **Security** | Sandboxed iframe with deny-by-default CSP | Depends on app implementation |

### When to Use MCP Apps

- **Data exploration** - Interactive dashboards (click, filter, drill-down)
- **Configuration** - Multi-option forms with validation and defaults
- **Media review** - Embedded viewers (PDFs, images, 3D models)
- **Real-time monitoring** - Persistent connection with live updates
- **Multi-step workflows** - Navigation, actions, persistent state

## MCP App Specification

### Tool Definition with UI Metadata

Tools declare UI resources via `_meta.ui.resourceUri`:

```python
# FastMCP example with custom HTML
@mcp.tool(app=AppConfig(resource_uri="ui://my-app/dashboard.html"))
def show_data(dataset: str) -> str:
    """Display dataset as interactive dashboard."""
    return json.dumps({"dataset": dataset, "status": "ready"})
```

**Core Fields**:
- `name`: Tool identifier
- `description`: What the tool does
- `inputSchema`: JSON Schema for parameters
- `_meta.ui.resourceUri`: Pointer to `ui://` resource (e.g., `ui://my-app/view.html`)

### Resource Definition

Resources deliver the HTML/JavaScript:

```python
# FastMCP example
@mcp.resource("ui://my-app/dashboard.html")
def dashboard_view() -> str:
    return """<html>
    <head><script src="https://cdn.plot.ly/plotly-latest.min.js"></script></head>
    <body>
        <div id="chart"></div>
        <script>
            // Listen for tool results via postMessage
            window.addEventListener('message', (event) => {
                const data = event.data;
                if (data.type === 'tool_result') {
                    renderChart(data.content);
                }
            });
        </script>
    </body>
    </html>"""
```

### CSP and Security Configuration

Apps run in sandboxed iframes with **deny-by-default** Content Security Policy. Declare allowed external domains explicitly:

```python
from fastmcp.server.apps import AppConfig, ResourceCSP, ResourcePermissions

@mcp.resource(
    "ui://my-app/chart.html",
    app=AppConfig(
        csp=ResourceCSP(
            resource_domains=["https://cdn.plot.ly"],      # Scripts, styles, images
            connect_domains=["https://api.example.com"],   # Fetch/WebSocket
            frame_domains=["https://embedded.com"],        # Nested iframes
            base_uri_domains=["https://base.example.com"]  # Base URI
        ),
        permissions=ResourcePermissions(
            camera={},              # Request camera access
            clipboard_write={}      # Request clipboard write
        )
    )
)
def chart_view() -> str:
    return "<html>...</html>"
```

**CSP Domains**:
- `resource_domains`: External scripts, styles, images, fonts, media
- `connect_domains`: Fetch, XHR, WebSocket endpoints
- `frame_domains`: Nested iframe origins
- `base_uri_domains`: Additional base URI origins

**Permissions**:
- `camera`: Request camera access
- `clipboard_write`: Request clipboard write
- Hosts may decline—implement feature detection as fallback

### Tool Visibility Control

Control which entities can invoke a tool:

```python
# Default: both model and UI can call
@mcp.tool(app=True)
def shared_tool() -> PrefabApp: ...

# Only LLM can call (hidden from UI)
@mcp.tool(app=AppConfig(...), visibility=["model"])
def lm_only_tool() -> str: ...

# Only UI can call (hidden from LLM)
@mcp.tool(app=AppConfig(...), visibility=["app"])
def ui_only_tool() -> str: ...
```

## Implementation Approaches

### 1. Custom HTML Apps (Full Control)

Best for: Plotly charts, embedded viewers, complex UIs with external libraries.

```python
from fastmcp import FastMCP, Context
from fastmcp.server.apps import AppConfig, ResourceCSP, UI_EXTENSION_ID
import json

mcp = FastMCP("dust-analyzer")

# Tool generates data
@mcp.tool(app=AppConfig(
    resource_uri="ui://dust/chart.html",
    csp=ResourceCSP(
        resource_domains=["https://cdn.plot.ly"],
        connect_domains=["https://api.example.com"]
    )
))
async def render_dust_chart(
    lat: float,
    lon: float,
    days: int = 7
) -> str | ToolResult:
    """Render Saharan dust analysis for location as interactive Plotly chart."""
    ctx: Context  # Injected

    # Graceful fallback for non-app clients
    if not ctx.client_supports_extension(UI_EXTENSION_ID):
        return f"Charts require MCP Apps support. Dust data for {lat},{lon}..."

    # Generate chart data
    chart_data = {
        "location": {"lat": lat, "lon": lon},
        "days": days,
        "status": "loading"
    }
    return json.dumps(chart_data)

# Resource delivers HTML
@mcp.resource("ui://dust/chart.html")
def dust_chart_ui() -> str:
    return """<html>
<head>
    <meta charset="utf-8">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { margin: 0; padding: 12px; font-family: sans-serif; background: #f5f5f5; }
        #chart { width: 100%; height: 600px; }
        .info { padding: 12px; background: white; border-radius: 4px; margin-bottom: 12px; }
    </style>
</head>
<body>
    <div class="info">
        <h2 id="title">Dust Analysis</h2>
        <p id="status">Loading...</p>
    </div>
    <div id="chart"></div>
    <script>
        // MCP Apps postMessage protocol
        window.addEventListener('message', async (event) => {
            const message = event.data;

            if (message.type === 'tool_result') {
                const data = JSON.parse(message.content[0].text);
                document.getElementById('title').textContent =
                    `Dust Analysis: ${data.location.lat}, ${data.location.lon}`;

                // Fetch actual measurements from CAMS (via server tool)
                // and render Plotly chart
                const plotData = [{
                    x: ['Day 1', 'Day 2', 'Day 3'],
                    y: [10, 15, 12],
                    name: 'Dust',
                    type: 'scatter',
                    mode: 'lines+markers'
                }];

                Plotly.newPlot('chart', plotData, {
                    title: 'Saharan Dust Concentration',
                    responsive: true,
                    template: 'plotly_dark'
                });
            }
        });

        // Notify host we're ready
        window.parent.postMessage({ type: 'ui_ready' }, '*');
    </script>
</body>
</html>"""
```

### 2. Prefab Apps (Declarative Python UI)

Best for: Forms, tables, simple charts, rapid prototyping.

```python
from fastmcp import FastMCP
from prefab_ui import (
    PrefabApp, Column, Heading, BarChart, LineChart,
    Select, Button, Table, Card
)

mcp = FastMCP("analytics")

@mcp.tool(app=True)
def revenue_dashboard(year: int = 2026) -> PrefabApp:
    """Show revenue analysis dashboard."""
    data = [
        {"month": "Jan", "revenue": 45000},
        {"month": "Feb", "revenue": 52000},
        {"month": "Mar", "revenue": 48000},
    ]

    with Column(gap=4, css_class="p-6") as view:
        Heading(f"{year} Revenue Analysis")
        BarChart(
            data=data,
            series=[
                {"key": "revenue", "label": "Revenue", "color": "#10b981"}
            ],
            x_key="month"
        )
        Table(
            data=data,
            columns=[
                {"key": "month", "label": "Month"},
                {"key": "revenue", "label": "Revenue"}
            ]
        )

    return PrefabApp(view=view)
```

**Features**:
- Type inference auto-enables app rendering
- State management (browser-side mutations, no server round-trips)
- Seamless coexistence with custom HTML tools in same server
- Single shared renderer resource across all Prefab tools

## Common Patterns

### Pattern: Plotly Visualization

**Use Case**: Interactive time series, maps, and comparison charts in dust-analyzer.

```python
import json
from fastmcp import FastMCP
from fastmcp.server.apps import AppConfig, ResourceCSP

mcp = FastMCP("dust-analyzer")

@mcp.tool(app=AppConfig(
    resource_uri="ui://dust/plotly-chart.html",
    csp=ResourceCSP(resource_domains=["https://cdn.plot.ly"])
))
def plot_dust_time_series(lat: float, lon: float) -> str:
    """Render Saharan dust time series as interactive Plotly chart."""
    measurements = [
        {"date": "2026-03-01", "dust": 12.5, "so2": 2.1, "pm25": 35},
        {"date": "2026-03-02", "dust": 15.2, "so2": 2.3, "pm25": 38},
    ]
    return json.dumps({"location": (lat, lon), "data": measurements})

@mcp.resource("ui://dust/plotly-chart.html")
def plotly_view() -> str:
    return """<html>
<head>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { margin: 0; padding: 12px; }
        #chart { width: 100%; height: 500px; }
    </style>
</head>
<body>
    <div id="chart"></div>
    <script>
        window.addEventListener('message', (event) => {
            const msg = event.data;
            if (msg.type === 'tool_result') {
                const result = JSON.parse(msg.content[0].text);
                const data = result.data;

                const trace = {
                    x: data.map(d => d.date),
                    y: data.map(d => d.dust),
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: 'Saharan Dust',
                    line: { color: '#f97316' }
                };

                Plotly.newPlot('chart', [trace], {
                    title: 'Dust Concentration',
                    template: 'plotly_dark',
                    responsive: true
                });
            }
        });
    </script>
</body>
</html>"""
```

**Notes**:
- Tool returns JSON payload, not HTML
- Resource contains HTML/JS for rendering
- `postMessage` protocol passes tool result into iframe
- CSP required to allow `cdn.plot.ly`

### Pattern: App Calling Server Tools

**Use Case**: Dashboard fetching fresh data on user interaction.

```html
<script>
    // App calls tool via MCP protocol
    function refreshData() {
        window.parent.postMessage({
            type: 'tools/call',
            method: 'tools/call',
            params: {
                name: 'fetch_latest_dust',
                arguments: { lat: 52.37, lon: 9.73 }
            }
        }, '*');
    }

    // Receive tool result
    window.addEventListener('message', (event) => {
        if (event.data.type === 'tool_result') {
            console.log('Fresh data:', event.data.content);
            updateChart(event.data.content);
        }
    });
</script>
```

### Pattern: Client Support Detection

**Use Case**: Fallback for non-app clients (text-only).

```python
from fastmcp import Context
from fastmcp.server.apps import UI_EXTENSION_ID

@mcp.tool(app=AppConfig(...))
async def show_chart(ctx: Context) -> str | ToolResult:
    """Show chart if client supports apps, else text."""

    if ctx.client_supports_extension(UI_EXTENSION_ID):
        # Return rich JSON for app rendering
        return json.dumps({"chart": "data", "type": "plotly"})
    else:
        # Fallback to text for basic MCP clients
        return "Chart data: Dust 12.5 μg/m³, SO₂ 2.1 ppb, PM2.5 35 μg/m³"
```

## Best Practices

### DO

- **Bundle assets into HTML** - Embed scripts/styles inline or fetch from whitelisted CDNs
- **Declare CSP domains** - Explicitly list all external origins (resource_domains, connect_domains)
- **Use postMessage protocol** - Secure, auditable communication between app and host
- **Provide text fallbacks** - Detect `UI_EXTENSION_ID`, return plain text for basic clients
- **Validate input** - Tool parameters are untrusted; sanitize before passing to HTML
- **Use responsive design** - Plotly, modern CSS for mobile/dark theme compatibility
- **Handle errors gracefully** - Network failures, invalid data, missing permissions
- **Keep CSP minimal** - Only whitelist domains you actually need

### DON'T

- **Don't load arbitrary scripts** - Only from whitelisted CSP domains
- **Don't rely on cookies/localStorage** - Apps run in restricted sandbox
- **Don't assume permissions** - Camera, clipboard, etc. may be denied; detect feature availability
- **Don't hardcode data** - Fetch via `tools/call` for dynamic, real-time content
- **Don't bypass sandbox** - You can't access parent window, localStorage, or escape iframe
- **Don't include sensitive data in HTML** - Resources are preloaded, visible to host
- **Don't nest deep iframes** - Restrict `frame_domains` to prevent recursive nesting

## Security Model

### Sandbox Isolation

Apps run in sandboxed iframes with:
- No access to parent window DOM
- No reading host cookies or localStorage
- No navigating parent page
- No executing scripts in parent context
- All communication via `postMessage` API

### CSP (Content Security Policy)

**Default (most restrictive)**:
```
script-src 'self' 'unsafe-inline'
style-src 'self' 'unsafe-inline'
img-src 'self'
font-src 'self'
connect-src 'self'
```

**With custom domains**:
```python
ResourceCSP(
    resource_domains=["https://cdn.plot.ly"],
    connect_domains=["https://api.example.com"]
)
# Expands CSP to include these origins
```

### Permissions Model

Browser capabilities (camera, clipboard, microphone) are explicit and user-granted:
```python
ResourcePermissions(
    camera={},              # User will be prompted
    clipboard_write={}
)
```

Implement fallbacks for denied permissions:
```javascript
navigator.clipboard?.writeText(data)
    .catch(() => console.log("Clipboard unavailable"));
```

### Audit Trail

All communication via `postMessage` is:
- Loggable (structured JSON-RPC)
- Auditable (host sees all tool calls from UI)
- Subject to user consent (host can restrict tools)

## FastMCP Integration

### Installation

```bash
uv add fastmcp
uv add "fastmcp[apps]"  # With Prefab UI support
```

### Basic Server Setup

```python
from fastmcp import FastMCP, Context
from fastmcp.server.apps import AppConfig, ResourceCSP, UI_EXTENSION_ID
import json

mcp = FastMCP("my-server")

@mcp.tool(app=AppConfig(
    resource_uri="ui://my-app/view.html",
    csp=ResourceCSP(
        resource_domains=["https://cdn.plot.ly"],
        connect_domains=["https://api.example.com"]
    )
))
async def my_tool(param: str, ctx: Context) -> str:
    if not ctx.client_supports_extension(UI_EXTENSION_ID):
        return "Text fallback"
    return json.dumps({"status": "ready", "param": param})

@mcp.resource("ui://my-app/view.html")
def my_view() -> str:
    return """<html>..."""
```

### Running the Server

```bash
# HTTP transport (development)
python server.py

# Stdio transport (production/Claude Desktop)
python server.py --stdio
```

### Claude Desktop Configuration

Add to `~/.config/Claude/claude_desktop_config.json` (Linux) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "dust-analyzer": {
      "command": "python",
      "args": ["path/to/server.py", "--stdio"]
    }
  }
}
```

## Client Support Matrix

| Client | MCP Apps | Notes |
|--------|----------|-------|
| **Claude** (web) | ✓ | Full support, launched Jan 2026 |
| **Claude Desktop** | ✓ | Native implementation |
| **VS Code Copilot** | ✓ | GitHub Copilot integration |
| **Goose** | ✓ | AI coding agent |
| **ChatGPT** | ✓ | OpenAI platform |
| **Cursor** | ✗ | Basic MCP only, no apps |
| **Windsurf** | ✗ | Basic MCP only |
| **MCPJam** | ✓ | Experimental platform |

## Common Issues & Solutions

### Issue: External Script/Style Not Loading

**Symptoms**: Chart doesn't render, JavaScript errors in console.

**Cause**: Missing CSP domain declaration.

**Solution**:
```python
ResourceCSP(
    resource_domains=["https://cdn.plot.ly"],  # Add required domain
    connect_domains=["https://api.example.com"]
)
```

### Issue: App Cannot Call Server Tools

**Symptoms**: `tools/call` returns error or doesn't execute.

**Cause**:
- Tool visibility set to `["model"]` only
- Host restricted the tool
- Malformed `tools/call` message

**Solution**:
```python
# Ensure tool is callable from app
@mcp.tool(visibility=["model", "app"])  # Or default (both)
def my_tool() -> str: ...

# Verify message format
{
    "type": "tools/call",
    "method": "tools/call",
    "params": {
        "name": "tool_name",
        "arguments": {...}
    }
}
```

### Issue: Permissions Not Granted

**Symptoms**: Feature unavailable (clipboard, camera, etc.).

**Cause**: Host or user denied permission.

**Solution**: Implement graceful fallback:
```javascript
try {
    await navigator.clipboard.writeText(data);
} catch (e) {
    console.log("Clipboard unavailable, falling back to manual copy");
    // Provide alternative UI
}
```

### Issue: App Works Locally, Fails in Claude Desktop

**Symptoms**: UI renders in browser but blank/error in Claude Desktop.

**Cause**:
- CSP mismatch (local has different policies)
- Missing `UI_EXTENSION_ID` detection
- Resource not found (wrong `ui://` path)

**Solution**:
1. Always declare CSP domains
2. Detect extension support: `ctx.client_supports_extension(UI_EXTENSION_ID)`
3. Test with `fastmcp --client` or actual Claude Desktop

## Resources

### Official Documentation
- [MCP Apps Specification](https://modelcontextprotocol.io/docs/extensions/apps) - Official spec and concepts
- [FastMCP Apps Guide](https://gofastmcp.com/apps/overview) - Python framework guide
- [FastMCP Prefab Apps](https://gofastmcp.com/apps/prefab) - Declarative UI with Python
- [FastMCP Custom HTML Apps](https://gofastmcp.com/apps/low-level) - Full control with custom HTML
- [MCP Apps API Docs](https://apps.extensions.modelcontextprotocol.io/api/) - JavaScript SDK reference

### Examples
- [Official ext-apps Repository](https://github.com/modelcontextprotocol/ext-apps) - All official examples (19+ servers)
  - [Map Server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/map-server) - CesiumJS globe
  - [System Monitor](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/system-monitor-server) - Real-time metrics
  - [PDF Server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/pdf-server) - Document viewer
  - [QR Server](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/qr-server) - Python minimal example
  - [Wiki Explorer](https://github.com/modelcontextprotocol/ext-apps/tree/main/examples/wiki-explorer-server) - Force-directed graph
- [Plotly MCP Server](https://github.com/arshlibruh/plotly-mcp-cursor) - 49+ chart types, natural language UI
- [MCP Visualization Server](https://github.com/xoniks/mcp-visualization-duckdb) - DuckDB + Plotly integration

### Related Tools
- [FastMCP Framework](https://github.com/prefecthq/fastmcp) - Python MCP framework (1M+ daily downloads)
- [MCP-UI](https://mcpui.dev/) - React components for building MCP app clients
- [MCP Servers Directory](https://fastmcp.me) - 1800+ MCP servers (many with app support)

### Blog Posts & Tutorials
- [MCP Apps Blog](http://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/) - Launch announcement
- [5 Tips for Building MCP Apps](https://block.github.io/goose/blog/2026/01/30/5-tips-building-mcp-apps/) - Goose team guidelines
- [Building MCP Servers with FastMCP](https://www.firecrawl.dev/blog/fastmcp-tutorial-building-mcp-servers-python/) - Complete tutorial
- [Why Data Visualization Needs MCP](https://python.plainenglish.io/building-my-first-mcp-server-why-data-visualization-needs-the-model-context-protocol-2fabbca834b4) - Use case article

## Use Case: dust-analyzer as MCP App Server

### Current Architecture
The dust-analyzer CLI generates standalone Plotly HTML charts. With MCP Apps, you can:

1. **Expose via MCP server** - HTTP or stdio transport
2. **Integrate with Claude Desktop** - Users browse CAMS data interactively in chat
3. **Multi-location analysis** - App calls tools to fetch data for new coordinates
4. **Real-time updates** - Refresh button fetches latest CAMS measurements

### Example Implementation

```python
# src/dust_analyzer/mcp_server.py
from fastmcp import FastMCP, Context
from fastmcp.server.apps import AppConfig, ResourceCSP, UI_EXTENSION_ID
from dust_analyzer import download, extract, Location
import json

mcp = FastMCP("dust-analyzer")

@mcp.tool(app=AppConfig(
    resource_uri="ui://dust/chart.html",
    csp=ResourceCSP(resource_domains=["https://cdn.plot.ly"])
))
async def render_dust_analysis(
    lat: float,
    lon: float,
    days: int = 7,
    ctx: Context = None
) -> str:
    """Analyze Saharan dust for location (renders as interactive chart)."""

    if ctx and not ctx.client_supports_extension(UI_EXTENSION_ID):
        return f"Dust analysis requires MCP Apps. Data for {lat},{lon}..."

    # Download and extract CAMS data
    location = Location(lat=lat, lon=lon)
    nc_path = await download(location, days)
    measurements = extract(nc_path)

    return json.dumps({
        "location": {"lat": lat, "lon": lon},
        "measurements": [
            {
                "date": m["date"].isoformat(),
                "dust": m["dust_conc"],
                "so2": m["so2_conc"],
                "pm25": m["pm25_conc"]
            }
            for m in measurements
        ]
    })

@mcp.resource("ui://dust/chart.html")
def dust_chart_ui() -> str:
    # Embed current plot.py HTML generation or use Plotly.js directly
    return """<html>
    <head>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>body { margin: 0; padding: 12px; }</style>
    </head>
    <body>
        <div id="chart" style="width:100%;height:600px;"></div>
        <script>
            window.addEventListener('message', (e) => {
                if (e.data.type === 'tool_result') {
                    const data = JSON.parse(e.data.content[0].text);
                    // Render Plotly chart with dust/SO2/PM2.5 traces
                }
            });
        </script>
    </body>
    </html>"""

if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run()  # stdio transport for Claude Desktop
    else:
        import uvicorn
        uvicorn.run(mcp.asgi(), host="0.0.0.0", port=8000)
```

### Configuration for Claude Desktop

```json
{
  "mcpServers": {
    "dust-analyzer": {
      "command": "uv",
      "args": ["run", "dust-analyzer", "--mcp"]
    }
  }
}
```

---

**Last Updated**: 2026-03-14 | **Status**: Production-ready (MCP Apps v1 launched Jan 2026)
