"""Tool registry and execution infrastructure for the local agent."""

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolResult(BaseModel):
    """Result returned by a tool execution."""
    success: bool
    data: Any = None
    message: str = ""
    error: Optional[str] = None

    def to_summary(self) -> str:
        """Compact text summary for feeding into small-model context."""
        if not self.success:
            return f"Error: {self.error or self.message}"
        if self.message and not self.data:
            return self.message
        if isinstance(self.data, (dict, list)):
            return json.dumps(self.data, indent=2, default=str)
        return str(self.data or self.message)


@dataclass
class ToolDefinition:
    """Explicit tool declaration with schema and execution callable."""
    name: str
    description: str
    parameters: Dict[str, Any]                             
    func: Callable[..., Any]
    required_params: List[str] = field(default_factory=list)

    def to_schema(self) -> Dict[str, Any]:
        """Format as compact JSON schema for LLM instruction."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """Registry managing available tools and execution dispatch."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable[..., Any],
        required_params: Optional[List[str]] = None,
    ) -> ToolDefinition:
        """Register a new tool."""
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
            required_params=required_params or list(parameters.keys()),
        )
        self._tools[name] = tool
        logger.debug(f"Registered tool: {name}")
        return tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def execute(self, name: str, kwargs: Dict[str, Any]) -> ToolResult:
        """Execute a tool with parameter validation."""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Unknown tool '{name}'. Available tools: {list(self._tools.keys())}",
            )

        try:
            logger.info(f"Executing tool '{name}' with arguments: {kwargs}")
            result = tool.func(**kwargs)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(success=True, data=result, message=f"Tool {name} completed successfully.")
        except Exception as e:
            logger.error(f"Error executing tool '{name}': {e}", exc_info=True)
            return ToolResult(success=False, error=str(e), message=f"Tool {name} failed: {e}")

    def get_tool_prompt(self) -> str:
        """Generate a concise tool catalog prompt for the local agent."""
        lines = [
            "You have access to the following deterministic tools. "
            "To use a tool, respond with ONLY a JSON object in this format:",
            '{"action": "tool_name", "arguments": {"arg1": "value1"}}\n',
            "Available tools:",
        ]
        for tool in self._tools.values():
            param_desc = ", ".join(
                f"{k}: {v.get('type', 'any')} ({v.get('description', '')})"
                for k, v in tool.parameters.items()
            )
            lines.append(f"- `{tool.name}`({param_desc}): {tool.description}")
        return "\n".join(lines)
