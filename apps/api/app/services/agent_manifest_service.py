from __future__ import annotations

import io
import json
import re
import uuid
import zipfile
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.services.agent_config_secrets import (
    SHOPIFY_SECRET_FIELDS,
    SHOPIFY_TOP_LEVEL_SECRET_FIELDS,
)
from app.services.prompt_assembler import PromptAssembler
from app.services.tool_registry import ToolRegistryService

try:  # pragma: no cover - exercised only when PyYAML is installed.
    import yaml
except Exception:  # pragma: no cover - keep the backend dependency-free.
    yaml = None


MANIFEST_VERSION = "agent-manifest:v1"
REQUIRED_PACKAGE_PATHS = (
    "agent.yaml",
    "SOUL.md",
    "RULES.md",
    "AGENTS.md",
    "INSTRUCTIONS.md",
    "knowledge/index.yaml",
    "memory/MEMORY.md",
    "tools/index.yaml",
    "skills/index.yaml",
    "hooks/hooks.yaml",
    "workflows/index.yaml",
    "compliance/regulatory-map.yaml",
)
SECRET_SUFFIX = "_encrypted"
SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|api[_-]?key|authorization|credential)",
    re.IGNORECASE,
)


class AgentManifestError(ValueError):
    """Raised when an agent package is malformed or unsafe to import."""


def _json_yaml_dump(value: Any) -> str:
    """Emit JSON-compatible YAML so imports work without a PyYAML dependency."""
    return json.dumps(value, indent=2, sort_keys=True, default=str) + "\n"


def _parse_structured_text(value: str, *, path: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return {}
    if yaml is not None:
        loaded = yaml.safe_load(stripped)
        return loaded if loaded is not None else {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise AgentManifestError(
            f"{path} must be JSON-compatible YAML on this backend."
        ) from exc


def _stable_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return _json_yaml_dump(value).strip()


def _deep_without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: cleaned
            for key, nested in value.items()
            if (cleaned := _deep_without_none(nested)) is not None
        }
    if isinstance(value, list):
        return [_deep_without_none(item) for item in value]
    return value


def _is_placeholder(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    return (
        (stripped.startswith("${") and stripped.endswith("}"))
        or (stripped.startswith("{{") and stripped.endswith("}}"))
        or stripped.startswith("<")
        and stripped.endswith(">")
    )


def _placeholder_for(tool_id: str, field: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", f"{tool_id}_{field}").strip("_")
    return "${" + normalized.upper() + "}"


def _strip_secretish_values(value: Any, *, placeholders: bool = False, tool_id: str = "tool") -> Any:
    if isinstance(value, list):
        return [
            _strip_secretish_values(item, placeholders=placeholders, tool_id=tool_id)
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    sanitized: dict[str, Any] = {}
    for key, nested in value.items():
        key_string = str(key)
        if key_string.endswith(SECRET_SUFFIX):
            continue
        if key_string.endswith("_placeholder") and _is_placeholder(nested):
            sanitized[key_string] = nested
            continue
        if SECRET_KEY_PATTERN.search(key_string):
            if placeholders and _is_placeholder(nested):
                sanitized[key_string] = nested
            elif placeholders:
                sanitized[key_string] = _placeholder_for(tool_id, key_string)
            continue
        sanitized[key_string] = _strip_secretish_values(
            nested,
            placeholders=placeholders,
            tool_id=tool_id,
        )
    return sanitized


class AgentManifestService:
    def __init__(self, tool_registry: ToolRegistryService | None = None) -> None:
        self.tool_registry = tool_registry or ToolRegistryService()
        self.prompt_assembler = PromptAssembler()

    def build_package_files(self, agent_doc: dict[str, Any]) -> dict[str, str]:
        config = deepcopy(agent_doc.get("configuration") or {})
        prompt_layers = self.prompt_assembler.normalize_prompt_layers(agent_doc, config)
        agent_yaml = self._build_agent_yaml(agent_doc, config)

        files = {
            "agent.yaml": _json_yaml_dump(agent_yaml),
            "SOUL.md": _stable_text(prompt_layers.get("soul")),
            "RULES.md": _stable_text(prompt_layers.get("rules")),
            "AGENTS.md": _stable_text(config.get("agents_md"))
            or self._default_agents_md(agent_doc),
            "INSTRUCTIONS.md": _stable_text(config.get("instructions_md"))
            or _stable_text(agent_doc.get("system_prompt")),
            "knowledge/index.yaml": _json_yaml_dump(
                self._build_knowledge_index(config, prompt_layers)
            ),
            "memory/MEMORY.md": _stable_text(config.get("memory"))
            or "No portable long-term memory entries are included in this export.\n",
            "tools/index.yaml": _json_yaml_dump(self._build_tools_index(config)),
            "skills/index.yaml": _json_yaml_dump(self._build_skills_index(config)),
            "hooks/hooks.yaml": _json_yaml_dump(
                _strip_secretish_values(config.get("hooks") or {})
            ),
            "workflows/index.yaml": _json_yaml_dump(config.get("workflows") or {}),
            "compliance/regulatory-map.yaml": _json_yaml_dump(
                config.get("compliance", {}).get("regulatory_map")
                or config.get("regulatory_map")
                or {}
            ),
        }
        return {path: files.get(path, "") for path in REQUIRED_PACKAGE_PATHS}

    def build_zip(self, agent_doc: dict[str, Any]) -> bytes:
        package_files = self.build_package_files(agent_doc)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, content in package_files.items():
                archive.writestr(path, content)
        return buffer.getvalue()

    def parse_zip(self, payload: bytes) -> dict[str, str]:
        try:
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                files: dict[str, str] = {}
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    normalized = info.filename.lstrip("/")
                    if normalized.startswith("../") or "/../" in normalized:
                        raise AgentManifestError(f"Unsafe zip member path: {info.filename}")
                    files[normalized] = archive.read(info).decode("utf-8")
        except zipfile.BadZipFile as exc:
            raise AgentManifestError("Uploaded file is not a valid zip archive.") from exc

        if "agent.yaml" not in files:
            raise AgentManifestError("Agent package must include agent.yaml.")
        return files

    def build_import_document(
        self,
        package_files: dict[str, str],
        *,
        brand_id: str | None = None,
        brand_slug: str | None = None,
    ) -> dict[str, Any]:
        manifest = _parse_structured_text(package_files["agent.yaml"], path="agent.yaml")
        if not isinstance(manifest, dict):
            raise AgentManifestError("agent.yaml must contain a mapping/object.")

        agent_section = manifest.get("agent") or manifest.get("metadata") or {}
        if not isinstance(agent_section, dict):
            raise AgentManifestError("agent.yaml agent section must be a mapping/object.")

        name = str(agent_section.get("name") or manifest.get("name") or "").strip()
        if not name:
            raise AgentManifestError("agent.yaml must include agent.name.")
        description = str(agent_section.get("description") or manifest.get("description") or "").strip()

        imported_brand_id = (
            brand_id
            or agent_section.get("brand_id")
            or (manifest.get("source") or {}).get("brand_id")
            or "portable"
        )
        imported_brand_slug = (
            brand_slug
            or agent_section.get("brand_slug")
            or (manifest.get("source") or {}).get("brand_slug")
            or "portable"
        )
        config = self._config_from_package(manifest, package_files)
        now = datetime.utcnow()
        agent_id = str(uuid.uuid4())

        return {
            "id": agent_id,
            "brand_id": str(imported_brand_id),
            "brand_slug": str(imported_brand_slug),
            "slug": self.generate_slug(name),
            "name": name,
            "description": description,
            "system_prompt": package_files.get("SOUL.md", "").strip(),
            "metadata": _deep_without_none(
                {
                    "purpose": agent_section.get("purpose"),
                    "role": agent_section.get("role"),
                    "source_manifest_version": manifest.get("manifest_version"),
                    "imported_from": "agent_manifest_zip",
                }
            ),
            "configuration": config,
            "status": "draft",
            "created_at": now,
            "updated_at": now,
        }

    @staticmethod
    def generate_slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return slug or "imported-agent"

    def _build_agent_yaml(self, agent_doc: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        metadata = agent_doc.get("metadata") or {}
        prompt_layers = config.get("prompt_layers") or {}
        duties = prompt_layers.get("duties") if isinstance(prompt_layers.get("duties"), dict) else {}
        return _deep_without_none(
            {
                "manifest_version": MANIFEST_VERSION,
                "agent": {
                    "name": agent_doc.get("name"),
                    "description": agent_doc.get("description"),
                    "purpose": metadata.get("purpose") or duties.get("purpose"),
                    "role": metadata.get("role") or duties.get("role"),
                    "version": metadata.get("version") or "1.0.0",
                },
                "source": {
                    "agent_id": agent_doc.get("id"),
                    "brand_id": agent_doc.get("brand_id"),
                    "brand_slug": agent_doc.get("brand_slug"),
                    "slug": agent_doc.get("slug"),
                },
                "model": config.get("llm") or {},
                "runtime": {
                    "features": config.get("features") or {},
                    "security": config.get("security") or {},
                    "agent_api": _strip_secretish_values(config.get("agent_api") or {}),
                    "url_context_boost": _strip_secretish_values(config.get("url_context_boost") or {}),
                },
                "domain": _strip_secretish_values(config.get("domain") or {}),
                "template_data": _strip_secretish_values(config.get("template_data") or {}),
            }
        )

    def _build_knowledge_index(
        self,
        config: dict[str, Any],
        prompt_layers: dict[str, Any],
    ) -> dict[str, Any]:
        return _deep_without_none(
            {
                "data_source": config.get("data_source") or "none",
                "data_source_policy": prompt_layers.get("data_source_policy") or {},
                "rag": config.get("rag") or {"enabled": False},
                "api_data_source": _strip_secretish_values(config.get("api_data_source") or {}),
                "documents": config.get("documents") or [],
            }
        )

    def _build_tools_index(self, config: dict[str, Any]) -> dict[str, Any]:
        tools = deepcopy(config.get("tools") or {})
        exported_tools: dict[str, Any] = {}
        if isinstance(tools, dict):
            for tool_id, tool_config in tools.items():
                if tool_id in {"selected", "selected_tool_ids"}:
                    continue
                if not isinstance(tool_config, dict):
                    continue
                exported_tools[str(tool_id)] = self._sanitize_tool_config(str(tool_id), tool_config)
            selected = tools.get("selected") or tools.get("selected_tool_ids")
        elif isinstance(tools, list):
            selected = []
            for entry in tools:
                if not isinstance(entry, dict):
                    continue
                tool_id = str(entry.get("tool_id") or entry.get("id") or "")
                if not tool_id:
                    continue
                exported_tools[tool_id] = self._sanitize_tool_config(tool_id, entry)
                selected.append(tool_id)
        else:
            selected = []

        shopify = config.get("shopify")
        if isinstance(shopify, dict):
            exported_tools["shopify"] = {
                **exported_tools.get("shopify", {}),
                **self._sanitize_tool_config("shopify", shopify),
                "enabled": True,
            }

        return _deep_without_none(
            {
                "tools": exported_tools,
                "selected_tool_ids": selected if isinstance(selected, list) else [],
            }
        )

    def _sanitize_tool_config(self, tool_id: str, tool_config: dict[str, Any]) -> dict[str, Any]:
        sanitized = _strip_secretish_values(tool_config, placeholders=True, tool_id=tool_id)
        for field in self.tool_registry.secret_fields_for(tool_id):
            if field in tool_config or f"{field}{SECRET_SUFFIX}" in tool_config:
                if _is_placeholder(tool_config.get(field)):
                    sanitized[field] = tool_config[field]
                else:
                    sanitized[field] = _placeholder_for(tool_id, field)
            sanitized.pop(f"{field}{SECRET_SUFFIX}", None)
        if tool_id == "shopify":
            for field in SHOPIFY_SECRET_FIELDS:
                if field in tool_config or f"{field}{SECRET_SUFFIX}" in tool_config:
                    sanitized[field] = (
                        tool_config[field]
                        if _is_placeholder(tool_config.get(field))
                        else _placeholder_for(tool_id, field)
                    )
                sanitized.pop(f"{field}{SECRET_SUFFIX}", None)
            for top_level_field, nested_field in SHOPIFY_TOP_LEVEL_SECRET_FIELDS.items():
                sanitized.pop(top_level_field, None)
                if top_level_field in tool_config and nested_field not in sanitized:
                    sanitized[nested_field] = _placeholder_for(tool_id, nested_field)
        return sanitized

    def _build_skills_index(self, config: dict[str, Any]) -> dict[str, Any]:
        skills = deepcopy(config.get("skills") or [])
        if isinstance(skills, dict):
            selected = skills.get("selected") or skills.get("selected_skill_ids") or []
            entries = {
                key: value
                for key, value in skills.items()
                if key not in {"selected", "selected_skill_ids"}
            }
        elif isinstance(skills, list):
            selected = [
                entry.get("skill_id") or entry.get("id")
                for entry in skills
                if isinstance(entry, dict) and (entry.get("skill_id") or entry.get("id"))
            ]
            entries = {
                str(entry.get("skill_id") or entry.get("id")): entry
                for entry in skills
                if isinstance(entry, dict) and (entry.get("skill_id") or entry.get("id"))
            }
        else:
            selected = []
            entries = {}
        return {"skills": entries, "selected_skill_ids": selected}

    def _config_from_package(self, manifest: dict[str, Any], files: dict[str, str]) -> dict[str, Any]:
        knowledge = self._read_optional_structured(files, "knowledge/index.yaml")
        tools_index = self._read_optional_structured(files, "tools/index.yaml")
        skills_index = self._read_optional_structured(files, "skills/index.yaml")
        hooks = self._read_optional_structured(files, "hooks/hooks.yaml")
        workflows = self._read_optional_structured(files, "workflows/index.yaml")
        regulatory_map = self._read_optional_structured(files, "compliance/regulatory-map.yaml")

        runtime = manifest.get("runtime") if isinstance(manifest.get("runtime"), dict) else {}
        config = _deep_without_none(
            {
                "llm": manifest.get("model") if isinstance(manifest.get("model"), dict) else {},
                "prompt_layers": {
                    "version": "layers:v1",
                    "soul": files.get("SOUL.md", "").strip(),
                    "rules": self._markdown_or_structured(files.get("RULES.md", "")),
                    "data_source_policy": knowledge.get("data_source_policy") or {},
                    "runtime_variables_schema": manifest.get("runtime_variables_schema") or {},
                },
                "rag": knowledge.get("rag") or {"enabled": False},
                "data_source": knowledge.get("data_source") or "none",
                "features": runtime.get("features") or {},
                "security": runtime.get("security") or {},
                "agent_api": runtime.get("agent_api") or {},
                "url_context_boost": runtime.get("url_context_boost") or {},
                "api_data_source": knowledge.get("api_data_source") or {},
                "tools": self._import_tools_config(tools_index),
                "skills": self._import_skills_config(skills_index),
                "hooks": hooks,
                "workflows": workflows,
                "compliance": {"regulatory_map": regulatory_map},
                "domain": manifest.get("domain") if isinstance(manifest.get("domain"), dict) else {},
                "template_data": manifest.get("template_data")
                if isinstance(manifest.get("template_data"), dict)
                else {},
                "instructions_md": files.get("INSTRUCTIONS.md", "").strip(),
                "agents_md": files.get("AGENTS.md", "").strip(),
                "memory": files.get("memory/MEMORY.md", "").strip(),
            }
        )
        return _strip_secretish_values(config, placeholders=False)

    def _read_optional_structured(self, files: dict[str, str], path: str) -> dict[str, Any]:
        if path not in files or not files[path].strip():
            return {}
        parsed = _parse_structured_text(files[path], path=path)
        return parsed if isinstance(parsed, dict) else {}

    def _markdown_or_structured(self, value: str) -> Any:
        if not value.strip():
            return {}
        try:
            return _parse_structured_text(value, path="RULES.md")
        except AgentManifestError:
            return value.strip()

    def _import_tools_config(self, tools_index: dict[str, Any]) -> dict[str, Any]:
        tools = tools_index.get("tools") if isinstance(tools_index.get("tools"), dict) else {}
        imported: dict[str, Any] = {}
        for tool_id, tool_config in tools.items():
            if not isinstance(tool_config, dict):
                continue
            sanitized = _strip_secretish_values(tool_config, placeholders=False, tool_id=str(tool_id))
            for field in self.tool_registry.secret_fields_for(str(tool_id)):
                if _is_placeholder(tool_config.get(field)):
                    sanitized[f"{field}_placeholder"] = tool_config[field]
                sanitized.pop(field, None)
                sanitized.pop(f"{field}{SECRET_SUFFIX}", None)
            imported[str(tool_id)] = sanitized

        selected = tools_index.get("selected_tool_ids")
        if isinstance(selected, list):
            imported["selected_tool_ids"] = [str(tool_id) for tool_id in selected]
        return imported

    def _import_skills_config(self, skills_index: dict[str, Any]) -> Any:
        skills = skills_index.get("skills")
        if isinstance(skills, dict):
            return skills
        selected = skills_index.get("selected_skill_ids")
        if isinstance(selected, list):
            return {"selected_skill_ids": [str(skill_id) for skill_id in selected]}
        return {}

    def _default_agents_md(self, agent_doc: dict[str, Any]) -> str:
        name = agent_doc.get("name") or "Imported Agent"
        description = agent_doc.get("description") or ""
        return f"# {name}\n\n{description}\n"
