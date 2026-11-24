"""Built-in tools. Importing this package registers all tool specs."""

from app.tools import memory_tool, tasks, web_search  # noqa: F401  (registration side-effect)
from app.tools.registry import (  # noqa: F401
    ToolContext,
    ToolSpec,
    declarations_for,
    execute,
    register,
)
