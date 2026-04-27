"""
Tool Registry - Manages available tools for agents.
"""

from typing import Dict, List, Type, Optional
from .types import BaseTool

class ToolRegistry:
    """
    Registry for managing and retrieving tools.
    Acts as a single source of truth for tool availability.
    """
    
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        
    def register(self, tool: BaseTool):
        """Register a tool instance."""
        if tool.name in self._tools:
            # Update/overwrite if exists, or raise error?
            # For now, we allow overwriting with a warning LOG if we had logging here
            pass
        self._tools[tool.name] = tool
        
    def get(self, name: str) -> Optional[BaseTool]:
        """Get a tool instance by name."""
        return self._tools.get(name)
        
    def list_tools(self) -> List[BaseTool]:
        """Return list of all registered tools."""
        return list(self._tools.values())
        
    def get_tool_schemas(self) -> List[Dict]:
        """
        Return list of tool schemas in a format suitable for 
        LLM function calling (e.g., OpenAI compatible).
        """
        schemas = []
        for tool in self._tools.values():
            schemas.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema
                }
            })
        return schemas
