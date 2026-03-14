"""Prompt templates — loads prompt files from the prompts directory."""

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt template by name (without extension).

    Raises ``FileNotFoundError`` if the prompt file does not exist.
    """
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text().strip()
