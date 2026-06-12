from __future__ import annotations

from copy import deepcopy
from typing import Any

from tools.types import BaseTool, ToolResult


BUILT_IN_SKILLS: list[dict[str, Any]] = [
    {
        "id": "knowledge_qa",
        "name": "Knowledge Q&A",
        "description": "Answer questions from approved brand knowledge and citations.",
        "category": "knowledge",
        "enabled_by_default": True,
        "config_schema": {
            "required_citations": {"type": "boolean", "default": True},
            "max_context_chunks": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
        },
    },
    {
        "id": "product_recommendation",
        "name": "Product Recommendation",
        "description": "Recommend products using catalog metadata and user preferences.",
        "category": "commerce",
        "enabled_by_default": True,
        "config_schema": {
            "max_products": {"type": "integer", "default": 4, "minimum": 1, "maximum": 12},
            "require_catalog_match": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "api_data_lookup",
        "name": "API Data Lookup",
        "description": "Use the configured API data source for approved external context such as astrology, pricing, or operational records.",
        "category": "integration",
        "enabled_by_default": False,
        "config_schema": {
            "require_configured_source": {"type": "boolean", "default": True},
            "max_result_chars": {"type": "integer", "default": 4000, "minimum": 500, "maximum": 12000},
        },
    },
    {
        "id": "url_context_boost",
        "name": "URL Context Boost",
        "description": "Use the current page URL, SKU, category, title, and metadata to boost retrieval and product relevance.",
        "category": "context",
        "enabled_by_default": True,
        "config_schema": {
            "use_url_path": {"type": "boolean", "default": True},
            "use_page_metadata": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "dealer_locator",
        "name": "Dealer Locator",
        "description": "Find nearby dealers or showrooms from configured dealer data.",
        "category": "commerce",
        "enabled_by_default": True,
        "config_schema": {
            "max_dealers": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            "require_location": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "lead_capture",
        "name": "Lead Capture",
        "description": "Collect contact details and intent for handoff or CRM sync.",
        "category": "conversion",
        "enabled_by_default": False,
        "config_schema": {
            "required_fields": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["name", "phone"],
            },
            "consent_required": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "conversation_summary",
        "name": "Conversation Summary",
        "description": "Summarize conversations for operators and downstream systems.",
        "category": "operations",
        "enabled_by_default": True,
        "config_schema": {
            "include_user_profile": {"type": "boolean", "default": True},
            "include_next_steps": {"type": "boolean", "default": True},
        },
    },
    {
        "id": "human_handoff",
        "name": "Human Handoff",
        "description": "Escalate a conversation to a human operator when policy requires it.",
        "category": "operations",
        "enabled_by_default": False,
        "config_schema": {
            "handoff_message": {"type": "string", "default": "I can connect you with a specialist."},
            "capture_reason": {"type": "boolean", "default": True},
        },
    },
]


class BuiltInSkillRegistry:
    def list_skills(self) -> list[dict[str, Any]]:
        return deepcopy(BUILT_IN_SKILLS)

    def get_skill(self, skill_id: str) -> dict[str, Any] | None:
        for skill in BUILT_IN_SKILLS:
            if skill["id"] == skill_id:
                return deepcopy(skill)
        return None

    def enabled_skill_tools(self, agent_config: dict[str, Any] | None) -> list[BaseTool]:
        config = agent_config or {}
        raw_skills = config.get("skills") or []
        enabled_entries: list[dict[str, Any]] = []

        if isinstance(raw_skills, list):
            enabled_entries = [
                entry for entry in raw_skills
                if isinstance(entry, dict) and entry.get("enabled") and entry.get("skill_id")
            ]
        elif isinstance(raw_skills, dict):
            selected = raw_skills.get("selected") or raw_skills.get("selected_skill_ids") or []
            if isinstance(selected, list):
                enabled_entries.extend(
                    {"skill_id": skill_id, "enabled": True, "config": {}}
                    for skill_id in selected
                )
            enabled_entries.extend(
                {"skill_id": skill_id, **entry}
                for skill_id, entry in raw_skills.items()
                if skill_id not in {"selected", "selected_skill_ids"}
                and isinstance(entry, dict)
                and entry.get("enabled")
            )

        tools: list[BaseTool] = []
        seen_skill_ids: set[str] = set()
        for entry in enabled_entries:
            skill_id = str(entry.get("skill_id"))
            if skill_id in seen_skill_ids:
                continue
            seen_skill_ids.add(skill_id)
            definition = self.get_skill(skill_id)
            if definition:
                tools.append(BuiltInSkillTool(definition, entry.get("config") or {}))
        return tools

    def agent_config_shape(self) -> dict[str, Any]:
        skills = [
            {
                "skill_id": skill["id"],
                "id": skill["id"],
                "enabled": skill["enabled_by_default"],
                "config": {
                    key: field.get("default")
                    for key, field in skill.get("config_schema", {}).items()
                    if "default" in field
                },
            }
            for skill in BUILT_IN_SKILLS
        ]
        return {
            "skills": skills,
            "enabled_skills": [
                {
                    "id": skill["id"],
                    "enabled": skill["enabled"],
                    "config": deepcopy(skill["config"]),
                }
                for skill in skills
            ],
        }


class BuiltInSkillTool(BaseTool):
    """Expose a built-in skill as a deterministic orchestrator capability."""

    parameters_schema = {
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "The user task or context this skill should handle.",
            },
            "metadata": {
                "type": "object",
                "description": "Optional structured context for the skill.",
            },
        },
        "required": ["input"],
    }

    def __init__(self, definition: dict[str, Any], config: dict[str, Any] | None = None):
        self.definition = deepcopy(definition)
        self.config = deepcopy(config or {})
        self.name = f"skill_{self.definition['id']}"
        self.description = self.definition.get("description") or self.definition.get("name") or self.name

    async def run(self, input: str, metadata: dict[str, Any] | None = None, **kwargs) -> ToolResult:
        return ToolResult(
            success=True,
            data={
                "skill_id": self.definition["id"],
                "skill_name": self.definition.get("name"),
                "input": input,
                "metadata": metadata or {},
                "config": self.config,
                "instruction": self.description,
            },
            metadata={
                "skill_id": self.definition["id"],
                "skill_category": self.definition.get("category"),
            },
        )
