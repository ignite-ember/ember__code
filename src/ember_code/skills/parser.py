"""Skill parser — parses SKILL.md files with YAML frontmatter."""

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SkillDefinition(BaseModel):
    """Parsed skill definition from a SKILL.md file."""

    name: str
    description: str = ""
    version: str = "0.1.0"
    argument_hint: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    model: str | None = None
    context: str = "inline"
    agent: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    body: str = ""
    source_dir: Path | None = None

    def render(self, arguments: str = "") -> str:
        """Render the skill body with argument substitutions."""
        text = self.body
        text = text.replace("$ARGUMENTS", arguments)

        args = arguments.split() if arguments else []
        for i, arg in enumerate(args):
            text = text.replace(f"${i + 1}", arg)
            text = text.replace(f"$ARGUMENTS[{i}]", arg)

        if self.source_dir:
            text = text.replace("${EMBER_SKILL_DIR}", str(self.source_dir))
            text = text.replace("${CLAUDE_SKILL_DIR}", str(self.source_dir))

        text = text.replace("${EMBER_SESSION_ID}", "")
        return text


def _as_str(value: object) -> str:
    """Coerce a value to string (YAML parses ``[hint]`` as a list)."""
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value else ""


class SkillParser:
    """Parses skill definitions from SKILL.md files."""

    @staticmethod
    def parse(path: Path) -> SkillDefinition:
        """Parse a SKILL.md file into a SkillDefinition."""
        content = path.read_text()

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)", content, re.DOTALL)
        if not fm_match:
            return SkillDefinition(
                name=path.parent.name,
                body=content.strip(),
                source_dir=path.parent,
            )

        yaml_str = fm_match.group(1)
        body = fm_match.group(2).strip()
        fm = yaml.safe_load(yaml_str) or {}

        tools_raw = fm.get("allowed-tools", fm.get("allowed_tools", []))
        if isinstance(tools_raw, str):
            tools = [t.strip() for t in tools_raw.split(",") if t.strip()]
        elif isinstance(tools_raw, list):
            tools = tools_raw
        else:
            tools = []

        return SkillDefinition(
            name=fm.get("name", path.parent.name),
            description=fm.get("description", ""),
            version=fm.get("version", "0.1.0"),
            argument_hint=_as_str(fm.get("argument-hint", fm.get("argument_hint", ""))),
            allowed_tools=tools,
            model=fm.get("model"),
            context=fm.get("context", "inline"),
            agent=fm.get("agent"),
            disable_model_invocation=fm.get("disable-model-invocation", False),
            user_invocable=fm.get("user-invocable", True),
            body=body,
            source_dir=path.parent,
        )


# Backward compatibility
def parse_skill_md(path: Path) -> SkillDefinition:
    """Convenience wrapper around SkillParser.parse()."""
    return SkillParser.parse(path)
