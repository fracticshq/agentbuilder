"""
Reasoning Core - Internal reasoning and plan generation.
"""

from typing import List, Optional
from dataclasses import dataclass
from pydantic import BaseModel, Field

class Step(BaseModel):
    id: int
    thought: str = Field(..., description="Internal reasoning for this step")
    tool_name: str = Field(..., description="Name of the tool to use")
    tool_input: dict = Field(..., description="Input parameters for the tool")
    
class Plan(BaseModel):
    goal: str
    steps: List[Step]

PROMPT_PLANNING = """
You are an expert Planning Agent.
Your goal is to break down the user's request into a step-by-step plan using the available tools.

User Request: {query}

Available Tools:
{tool_schemas}

Instructions:
1. THINK about the request. Is it simple or complex?
2. If simple (e.g., "Hi"), just use 'final_answer'.
3. If complex, break it down into steps.
4. Each step must use a tool.
5. You must output the plan in strict JSON format.

Output JSON Format:
{{
  "goal": "Brief description of goal",
  "steps": [
    {{
      "id": 1,
      "thought": "I need to find X first...",
      "tool_name": "knowledge_search",
      "tool_input": {{ "query": "..." }}
    }}
  ]
}}
"""
