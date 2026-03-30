"""MCP App HTML templates (`text/html;profile=mcp-app`), loaded from this package directory."""

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load_mcp_html(filename: str) -> str:
    """Return UTF-8 HTML for ``filename`` from the MCP UI package."""
    path = _DIR / filename
    if path.is_file():
        return path.read_text(encoding="utf-8")

    # Unified UI fallback: legacy resource filenames map to dashboard.html.
    dashboard = _DIR / "dashboard.html"
    if dashboard.is_file():
        return dashboard.read_text(encoding="utf-8")

    raise FileNotFoundError(f"MCP UI template not found: {path}")
