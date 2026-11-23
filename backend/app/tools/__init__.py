"""Built-in tools. Importing this package registers all tool specs.

To add the future Devin/ACP task tools (create/list/update/delete/dispatch/
reply — VoxRelay's codingToolDeclarations), drop a ``tasks.py`` module here,
register its specs gated on ``profile.enable_tasks``, and import it below.
"""

from app.tools import memory_tool, web_search  # noqa: F401  (registration side-effect)
from app.tools.registry import (  # noqa: F401
    ToolContext,
    ToolSpec,
    declarations_for,
    execute,
    register,
)
