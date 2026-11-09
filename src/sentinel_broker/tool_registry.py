"""Sentinel Dynamic Tool Registry.
Enables dynamic tool discovery, schema introspection, and decoupled execution handlers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sentinel_core.side_effects import EffectClass


@dataclass
class ToolDefinition:
    name: str
    description: str
    effect_class: EffectClass
    parameters_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        effect_class: EffectClass | str,
        parameters_schema: dict[str, Any] | None = None,
    ) -> Callable:
        """Decorator to dynamically register tools into the catalog."""
        eff = EffectClass(effect_class) if isinstance(effect_class, str) else effect_class
        schema = parameters_schema or {}

        def decorator(fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]):
            tool = ToolDefinition(
                name=name,
                description=description,
                effect_class=eff,
                parameters_schema=schema,
                handler=fn,
            )
            self._tools[name] = tool
            return fn

        return decorator

    def get_tool(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "effect_class": t.effect_class.value,
                "parameters_schema": t.parameters_schema,
            }
            for t in self._tools.values()
        ]

    def execute_tool(self, name: str, params: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        tool = self.get_tool(name)
        if not tool:
            raise KeyError(f"Tool '{name}' is not registered in ToolRegistry")
        ctx = context or {}
        return tool.handler(params, ctx)
