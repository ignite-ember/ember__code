"""Eval loader — parse YAML eval files into structured data."""

import logging
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EvalCase(BaseModel):
    """A single test case within an eval suite."""

    name: str
    input: str
    description: str = ""
    expected_tool_calls: list[str] | None = None
    unexpected_tool_calls: list[str] | None = None
    expected_output: str | None = None
    accuracy_threshold: float = 7.0
    judge_guidelines: str | None = None
    num_iterations: int = 1
    file_assertions: list[dict] | None = None


class EvalSuite(BaseModel):
    """A collection of eval cases targeting one agent."""

    agent: str
    description: str = ""
    fixtures: list[dict] | None = None
    cases: list[EvalCase] = Field(default_factory=list)

    @classmethod
    def load_all(cls, project_dir: Path) -> list["EvalSuite"]:
        """Discover and load all eval suites from .ember/evals/."""
        evals_dir = project_dir / ".ember" / "evals"
        if not evals_dir.is_dir():
            return []

        suites = []
        for path in sorted(evals_dir.glob("*.yaml")):
            suite = load_eval_file(path)
            if suite:
                suites.append(suite)
        return suites


def _parse_case(data: dict) -> EvalCase:
    """Parse a single case dict from YAML."""
    return EvalCase(
        name=data["name"],
        input=data["input"],
        description=data.get("description", ""),
        expected_tool_calls=data.get("expected_tool_calls"),
        unexpected_tool_calls=data.get("unexpected_tool_calls"),
        expected_output=data.get("expected_output"),
        accuracy_threshold=data.get("accuracy_threshold", 7.0),
        judge_guidelines=data.get("judge_guidelines"),
        num_iterations=data.get("num_iterations", 1),
        file_assertions=data.get("file_assertions"),
    )


def load_eval_file(path: Path) -> EvalSuite | None:
    """Load a single YAML eval file into an EvalSuite."""
    try:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict) or "agent" not in data or "cases" not in data:
            logger.warning("Skipping invalid eval file: %s", path)
            return None

        cases = [_parse_case(c) for c in data["cases"] if "name" in c and "input" in c]
        return EvalSuite(
            agent=data["agent"],
            description=data.get("description", ""),
            fixtures=data.get("fixtures"),
            cases=cases,
        )
    except Exception as exc:
        logger.warning("Failed to load eval file %s: %s", path, exc)
        return None
