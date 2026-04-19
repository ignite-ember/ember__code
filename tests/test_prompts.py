"""Tests for prompts/__init__.py — prompt template loading."""

import pytest

from ember_code.core.prompts import PROMPTS_DIR, load_prompt


class TestLoadPrompt:
    def test_loads_main_agent_prompt(self):
        result = load_prompt("main_agent")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_raises_on_missing_prompt(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_prompt_xyz")

    def test_prompts_dir_exists(self):
        assert PROMPTS_DIR.exists()
        assert PROMPTS_DIR.is_dir()

    def test_result_is_stripped(self):
        result = load_prompt("main_agent")
        assert result == result.strip()
