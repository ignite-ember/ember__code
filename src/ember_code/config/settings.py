"""Settings management with hierarchical config loading."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from ember_code.config.defaults import DEFAULT_CONFIG


class ModelsConfig(BaseModel):
    default: str = "MiniMax-M2.7"
    max_context_window: int = 200_000
    registry: dict[str, dict[str, Any]] = Field(default_factory=dict)


class PermissionsConfig(BaseModel):
    file_read: str = "allow"
    file_write: str = "ask"
    shell_execute: str = "ask"
    shell_restricted: str = "allow"
    web_search: str = "allow"
    web_fetch: str = "allow"
    git_push: str = "ask"
    git_destructive: str = "ask"


class SafetyConfig(BaseModel):
    sandbox_shell: bool = False
    sandbox_allowed_network_commands: list[str] = Field(default_factory=list)
    protected_paths: list[str] = Field(
        default_factory=lambda: [
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "credentials.*",
            "secrets.*",
        ]
    )
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            ":(){ :|:& };:",
        ]
    )
    max_file_size_kb: int = 500
    require_confirmation: list[str] = Field(
        default_factory=lambda: [
            "git push",
            "git push --force",
            "npm publish",
            "pip install",
            "docker run",
            "terraform apply",
            "kubectl apply",
            "kubectl delete",
        ]
    )


class StorageConfig(BaseModel):
    backend: str = "sqlite"
    session_db: str = "~/.ember/sessions.db"
    memory_db: str = "~/.ember/memory.db"
    audit_log: str = "~/.ember/audit.log"
    max_history_runs: int = 3


class RulesConfig(BaseModel):
    cross_tool_support: bool = True


class HooksConfig(BaseModel):
    cross_tool_support: bool = True


class ContextConfig(BaseModel):
    project_file: str = "ember.md"
    ignore_patterns: list[str] = Field(
        default_factory=lambda: [
            "node_modules/",
            ".git/",
            "__pycache__/",
            "*.pyc",
            ".venv/",
            "dist/",
            "build/",
        ]
    )


class OrchestrationConfig(BaseModel):
    max_nesting_depth: int = 5
    max_total_agents: int = 20
    sub_team_timeout: int = 120
    max_task_iterations: int = 10
    generate_ephemeral: bool = True
    max_ephemeral_per_session: int = 5
    auto_cleanup: bool = True


class AgentsConfig(BaseModel):
    cross_tool_support: bool = True


class SkillsConfig(BaseModel):
    cross_tool_support: bool = True
    auto_trigger: bool = True
    default_agent: str = "editor"


class MemoryConfig(BaseModel):
    enable_agentic_memory: bool = True
    add_memories_to_context: bool = True


class EmbeddingsConfig(BaseModel):
    """Embeddings provider configuration with BYOM registry."""

    default: str = "ember"
    registry: dict[str, dict[str, Any]] = Field(default_factory=dict)


class KnowledgeConfig(BaseModel):
    enabled: bool = False
    collection_name: str = "ember_knowledge"
    chroma_db_path: str = "~/.ember/chromadb"
    max_results: int = 10
    embedder: str = "ember"  # registry name (or "provider:model_id" format)
    # ── Git-shared knowledge ──────────────────────────────────────
    share: bool = True  # enable git-synced knowledge sharing
    share_file: str = ".ember/knowledge.yaml"  # path relative to project root
    auto_sync: bool = True  # auto-sync on session start/end


class LearningConfig(BaseModel):
    enabled: bool = False
    user_profile: bool = True
    user_memory: bool = True
    session_context: bool = True
    entity_memory: bool = False
    learned_knowledge: bool = False


class ReasoningConfig(BaseModel):
    enabled: bool = False
    add_instructions: bool = True
    add_few_shot: bool = False


class GuardrailsConfig(BaseModel):
    pii_detection: bool = False
    prompt_injection: bool = False
    moderation: bool = False


class EvalsConfig(BaseModel):
    judge_model: str = "MiniMax-M2.7"
    num_iterations: int = 3
    accuracy_threshold: float = 7.0
    timeout_per_case: int = 30


class SchedulerConfig(BaseModel):
    poll_interval: int = 30
    task_timeout: int = 300
    max_concurrent: int = 1


class AuthConfig(BaseModel):
    credentials_file: str = "~/.ember/credentials.json"
    server_url: str = "https://api.ignite-ember.sh"


class DisplayConfig(BaseModel):
    markdown: bool = True
    show_tool_calls: bool = True
    show_routing: bool = False
    show_reasoning: bool = False
    color_theme: str = "auto"
    tool_result_preview_lines: int = 4
    message_truncate_lines: int = 10


class Settings(BaseModel):
    """Complete Ember Code settings."""

    api_url: str = "https://api.ignite-ember.sh"
    version_endpoint: str = "/v1/cli/version"
    update_check_ttl: int = 86400
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    orchestration: OrchestrationConfig = Field(default_factory=OrchestrationConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)
    learning: LearningConfig = Field(default_factory=LearningConfig)
    reasoning: ReasoningConfig = Field(default_factory=ReasoningConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    evals: EvalsConfig = Field(default_factory=EvalsConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    display: DisplayConfig = Field(default_factory=DisplayConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, returning new dict."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict:
    """Load YAML file, returning empty dict if not found."""
    if path.exists():
        with open(path) as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    return {}


def load_settings(
    cli_overrides: dict[str, Any] | None = None,
    project_dir: Path | None = None,
) -> Settings:
    """Load settings by merging: defaults -> user config -> project config -> project local -> CLI.

    Priority (highest first):
    1. CLI flags
    2. .ember/config.local.yaml (project, gitignored)
    3. .ember/config.yaml (project, committed)
    4. ~/.ember/config.yaml (user global)
    5. Built-in defaults
    """
    config = DEFAULT_CONFIG.copy()

    # User global config
    user_config_path = Path.home() / ".ember" / "config.yaml"
    config = _deep_merge(config, _load_yaml(user_config_path))

    # Project config
    if project_dir is None:
        project_dir = Path.cwd()

    project_config = project_dir / ".ember" / "config.yaml"
    config = _deep_merge(config, _load_yaml(project_config))

    # Project local config (gitignored)
    project_local = project_dir / ".ember" / "config.local.yaml"
    config = _deep_merge(config, _load_yaml(project_local))

    # CLI overrides
    if cli_overrides:
        config = _deep_merge(config, cli_overrides)

    return Settings(**config)
