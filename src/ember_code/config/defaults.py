"""Default configuration values."""

DEFAULT_CONFIG = {
    "api_url": "https://api.ignite-ember.sh",
    "version_endpoint": "/v1/cli/version",
    "update_check_ttl": 86400,
    "models": {
        "default": "MiniMax-M2.5",
        "registry": {
            "MiniMax-M2.5": {
                "provider": "openai_like",
                "model_id": "MiniMax-Text-01",
                "url": "https://api.ignite-ember.sh/v1",
                "api_key_env": "EMBER_API_KEY",
                "context_window": 204_800,
            },
        },
    },
    "permissions": {
        "file_read": "allow",
        "file_write": "ask",
        "shell_execute": "ask",
        "shell_restricted": "allow",
        "web_search": "deny",
        "web_fetch": "deny",
        "git_push": "ask",
        "git_destructive": "ask",
    },
    "safety": {
        "sandbox_shell": False,
        "protected_paths": [
            ".env",
            ".env.*",
            "*.pem",
            "*.key",
            "credentials.*",
            "secrets.*",
        ],
        "blocked_commands": [
            "rm -rf /",
            ":(){ :|:& };:",
        ],
        "max_file_size_kb": 500,
        "require_confirmation": [
            "git push",
            "git push --force",
            "npm publish",
            "pip install",
        ],
    },
    "storage": {
        "backend": "sqlite",
        "session_db": "~/.ember/sessions.db",
        "memory_db": "~/.ember/memory.db",
        "audit_log": "~/.ember/audit.log",
        "max_history_runs": 10,
    },
    "context": {
        "project_file": "ember.md",
        "auto_load": ["ember.md", ".ember/config.yaml"],
        "ignore_patterns": [
            "node_modules/",
            ".git/",
            "__pycache__/",
            "*.pyc",
            ".venv/",
            "dist/",
            "build/",
        ],
    },
    "orchestration": {
        "max_nesting_depth": 5,
        "max_total_agents": 20,
        "sub_team_timeout": 120,
        "generate_ephemeral": True,
        "max_ephemeral_per_session": 5,
        "auto_cleanup": True,
    },
    "learning": {
        "enabled": False,
        "user_profile": True,
        "user_memory": True,
        "session_context": True,
        "entity_memory": False,
        "learned_knowledge": False,
    },
    "reasoning": {
        "enabled": False,
        "add_instructions": True,
        "add_few_shot": False,
    },
    "guardrails": {
        "pii_detection": False,
        "prompt_injection": False,
        "moderation": False,
    },
    "embeddings": {
        "default": "ember",
        "registry": {
            "ember": {
                "provider": "openai_compatible",
                "model_id": "text2vec-transformers",
                "url": "https://api.ignite-ember.sh",
                "api_key_env": "EMBER_API_KEY",
                "dimensions": 384,
            },
        },
    },
    "knowledge": {
        "enabled": False,
        "collection_name": "ember_knowledge",
        "chroma_db_path": "~/.ember/chromadb",
        "max_results": 10,
        "embedder": "ember",
    },
    "agents": {
        "cross_tool_support": False,
    },
    "skills": {
        "cross_tool_support": False,
        "auto_trigger": True,
    },
    "display": {
        "markdown": True,
        "show_tool_calls": True,
        "show_routing": False,
        "show_reasoning": False,
        "color_theme": "auto",
    },
}
