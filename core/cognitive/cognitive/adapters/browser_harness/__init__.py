"""cognitive.adapters.browser_harness -- Track BH BrowserAdapter."""

from .client import BrowserAdapter
from .guard import BrowserToolError, guard_browser_tool
from .mock import MockBrowserAdapter

__all__ = ["BrowserAdapter", "MockBrowserAdapter", "BrowserToolError", "guard_browser_tool"]
