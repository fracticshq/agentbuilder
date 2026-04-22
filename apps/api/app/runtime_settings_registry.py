from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeSettingOption:
    value: str
    label: str


@dataclass(frozen=True)
class RuntimeSettingDefinition:
    key: str
    section: str
    label: str
    description: str
    env_var: str | None = None
    input_type: str = "text"
    secret: bool = False
    required: bool = False
    options: tuple[RuntimeSettingOption, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RuntimeSettingSection:
    id: str
    title: str
    description: str
    supports_connection_test: bool = False


SECTIONS: tuple[RuntimeSettingSection, ...] = (
    RuntimeSettingSection(
        id="general",
        title="General",
        description="Global provider defaults used when an agent does not override its runtime provider.",
    ),
    RuntimeSettingSection(
        id="azure_openai",
        title="Azure OpenAI",
        description="Azure inference credentials and Azure resource metadata used for deployment discovery.",
        supports_connection_test=True,
    ),
    RuntimeSettingSection(
        id="voyage",
        title="Voyage",
        description="Embedding and reranking credentials used by retrieval, ingestion, and knowledge workflows.",
        supports_connection_test=True,
    ),
    RuntimeSettingSection(
        id="openai",
        title="OpenAI",
        description="Optional fallback provider settings for future multi-provider use.",
    ),
    RuntimeSettingSection(
        id="qwen",
        title="Qwen",
        description="Optional fallback provider settings for future multi-provider use.",
    ),
)


SETTINGS_REGISTRY: tuple[RuntimeSettingDefinition, ...] = (
    RuntimeSettingDefinition(
        key="general.default_llm_provider",
        section="general",
        label="Default LLM provider",
        description="Used only when an agent does not specify a provider in its own configuration.",
        env_var="DEFAULT_LLM_PROVIDER",
        input_type="select",
        options=(
            RuntimeSettingOption("azure_openai", "Azure OpenAI"),
            RuntimeSettingOption("openai", "OpenAI"),
            RuntimeSettingOption("qwen", "Qwen"),
        ),
    ),
    RuntimeSettingDefinition(
        key="azure_openai.api_key",
        section="azure_openai",
        label="Azure OpenAI API key",
        description="Used by the Azure OpenAI Responses API at runtime.",
        env_var="AZURE_OPENAI_API_KEY",
        input_type="password",
        secret=True,
    ),
    RuntimeSettingDefinition(
        key="azure_openai.endpoint",
        section="azure_openai",
        label="Azure OpenAI endpoint",
        description="The Azure OpenAI resource endpoint used by the inference client.",
        env_var="AZURE_OPENAI_ENDPOINT",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.api_version",
        section="azure_openai",
        label="Azure OpenAI API version",
        description="The API version sent to Azure OpenAI responses requests.",
        env_var="AZURE_OPENAI_API_VERSION",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.deployment",
        section="azure_openai",
        label="Default Azure deployment",
        description="Used as the default deployment for admin validation and for agents that do not specify a model.",
        env_var="AZURE_OPENAI_DEPLOYMENT",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.model",
        section="azure_openai",
        label="Default Azure model label",
        description="Optional display label stored alongside the Azure deployment.",
        env_var="AZURE_OPENAI_MODEL",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.account_name",
        section="azure_openai",
        label="Azure OpenAI account name",
        description="The Azure Cognitive Services account name used to list deployed Azure OpenAI models.",
        env_var="AZURE_OPENAI_ACCOUNT_NAME",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.subscription_id",
        section="azure_openai",
        label="Azure subscription ID",
        description="Subscription that owns the Azure OpenAI account used for deployment discovery.",
        env_var="AZURE_SUBSCRIPTION_ID",
    ),
    RuntimeSettingDefinition(
        key="azure_openai.resource_group",
        section="azure_openai",
        label="Azure resource group",
        description="Resource group containing the Azure OpenAI account used for deployment discovery.",
        env_var="AZURE_RESOURCE_GROUP",
    ),
    RuntimeSettingDefinition(
        key="voyage.api_key",
        section="voyage",
        label="Voyage API key",
        description="Used for embeddings and reranking in retrieval, ingestion, and knowledge processing.",
        env_var="VOYAGE_API_KEY",
        input_type="password",
        secret=True,
    ),
    RuntimeSettingDefinition(
        key="voyage.model",
        section="voyage",
        label="Voyage embedding model",
        description="Embedding model used when generating Voyage document/query vectors.",
        env_var="VOYAGE_MODEL",
    ),
    RuntimeSettingDefinition(
        key="openai.api_key",
        section="openai",
        label="OpenAI API key",
        description="Optional fallback provider key for future non-Azure OpenAI agents.",
        env_var="OPENAI_API_KEY",
        input_type="password",
        secret=True,
    ),
    RuntimeSettingDefinition(
        key="openai.base_url",
        section="openai",
        label="OpenAI base URL",
        description="Optional OpenAI-compatible base URL for future provider fallback.",
        env_var="OPENAI_BASE_URL",
    ),
    RuntimeSettingDefinition(
        key="openai.model",
        section="openai",
        label="Default OpenAI model",
        description="Default model used by the OpenAI provider when an agent does not override it.",
        env_var="OPENAI_MODEL",
    ),
    RuntimeSettingDefinition(
        key="qwen.api_key",
        section="qwen",
        label="Qwen API key",
        description="Optional fallback provider key for future Qwen-backed agents.",
        env_var="QWEN_API_KEY",
        input_type="password",
        secret=True,
    ),
    RuntimeSettingDefinition(
        key="qwen.base_url",
        section="qwen",
        label="Qwen base URL",
        description="Qwen-compatible API endpoint used for future fallback provider support.",
        env_var="QWEN_BASE_URL",
    ),
    RuntimeSettingDefinition(
        key="qwen.model",
        section="qwen",
        label="Default Qwen model",
        description="Default model used by the Qwen provider when an agent does not override it.",
        env_var="QWEN_MODEL",
    ),
)


SETTINGS_BY_KEY = {definition.key: definition for definition in SETTINGS_REGISTRY}
SECTIONS_BY_ID = {section.id: section for section in SECTIONS}
