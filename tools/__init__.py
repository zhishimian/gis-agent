from tools.registry import ToolRegistry
from tools.builtin import builtin_tools
registry=ToolRegistry()

for tool in builtin_tools:
    registry.register(tool)