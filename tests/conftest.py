"""Shared test fixtures."""

import pytest

from ember_code.config.settings import load_settings


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory as Path."""
    return tmp_path


@pytest.fixture
def settings():
    """Default Settings instance with defaults applied."""
    return load_settings()


@pytest.fixture
def project_dir(tmp_path):
    """Temporary project directory with .ember/ structure."""
    ember_dir = tmp_path / ".ember"
    ember_dir.mkdir()
    (ember_dir / "agents").mkdir()
    (ember_dir / "skills").mkdir()
    return tmp_path


@pytest.fixture
def sample_agent_md(tmp_path):
    """Create a sample agent .md file and return its path."""
    md = tmp_path / "test-agent.md"
    md.write_text(
        "---\n"
        "name: test-agent\n"
        "description: A test agent\n"
        "tools: Read, Grep\n"
        "model: MiniMax-M2.5\n"
        "tags: test, example\n"
        "reasoning: true\n"
        "reasoning_min_steps: 2\n"
        "reasoning_max_steps: 8\n"
        "---\n"
        "You are a test agent. Do test things.\n"
    )
    return md


@pytest.fixture
def sample_skill_md(tmp_path):
    """Create a sample SKILL.md file and return its path."""
    skill_dir = tmp_path / "test-skill"
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: test-skill\n"
        "description: A test skill\n"
        "argument-hint: <arg>\n"
        "allowed-tools: Read, Edit\n"
        "---\n"
        "Do something with $ARGUMENTS\n"
    )
    return skill_file
