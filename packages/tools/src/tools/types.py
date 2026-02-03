"""
Tool Types - Base classes and data structures for the Agentic Tooling Layer.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Type
from pydantic import BaseModel

@dataclass
class ToolResult:
    """Standardized result from a tool execution."""
    success: bool
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        if self.success:
            return f"Success: {str(self.data)[:500]}..."
        return f"Error: {self.error}"


class BaseTool(ABC):
    """Abstract base class for all tools."""
    
    name: str = "base_tool"
    description: str = "Base tool description"
    parameters_schema: Dict[str, Any] = {}
    
    def __init__(self, **kwargs):
        """Initialize the tool interactively if needed."""
        pass
        
    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        """Execute the tool logic."""
        pass
    
    async def check_health(self) -> bool:
        """Optional health check."""
        return True
