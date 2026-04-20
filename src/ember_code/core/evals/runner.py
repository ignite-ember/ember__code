"""Eval runner — orchestrates agent runs and Agno eval checks."""

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ember_code.core.evals.assertions import check_file_assertion, check_unexpected_tool_calls
from ember_code.core.evals.loader import EvalCase, EvalSuite

logger = logging.getLogger(__name__)


class CaseResult(BaseModel):
    """Result of running a single eval case."""

    case: EvalCase
    passed: bool = False
    reliability_passed: bool | None = None
    reliability_detail: str = ""
    unexpected_passed: bool | None = None
    unexpected_detail: str = ""
    accuracy_score: float | None = None
    accuracy_passed: bool | None = None
    file_results: list[tuple[str, bool, str]] = Field(default_factory=list)
    error: str | None = None
    elapsed: float = 0.0


class SuiteResult(BaseModel):
    """Result of running all cases in an eval suite."""

    suite: EvalSuite
    case_results: list[CaseResult] = Field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.case_results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.case_results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.case_results)

    @property
    def elapsed(self) -> float:
        return sum(r.elapsed for r in self.case_results)

    @classmethod
    async def run(
        cls,
        suite: EvalSuite,
        pool: Any,
        settings: Any,
        project_dir: Path,
    ) -> "SuiteResult":
        """Run all cases in an eval suite."""
        suite_result = cls(suite=suite)

        # Get the agent
        try:
            agent = pool.get(suite.agent)
        except (KeyError, ValueError) as exc:
            for case in suite.cases:
                suite_result.case_results.append(
                    CaseResult(case=case, error=f"agent '{suite.agent}' not found: {exc}")
                )
            return suite_result

        # Set up fixtures
        evals_dir = project_dir / ".ember" / "evals"
        work_dir = _setup_fixtures(suite.fixtures, evals_dir)

        # Get judge model for accuracy evals
        judge_model = None
        try:
            from ember_code.core.config.models import ModelRegistry

            registry = ModelRegistry(settings)
            judge_name = getattr(settings, "evals", None)
            judge_name = getattr(judge_name, "judge_model", None) if judge_name else None
            judge_model = registry.get_model(judge_name)
        except Exception as exc:
            logger.debug("Could not load judge model: %s", exc)

        # Run each case
        for case in suite.cases:
            case_result = await run_eval_case(case, agent, judge_model)
            suite_result.case_results.append(case_result)

        _cleanup_work_dir(work_dir)
        return suite_result

    @classmethod
    async def run_all(
        cls,
        pool: Any,
        settings: Any,
        project_dir: Path,
        agent_filter: str | None = None,
    ) -> list["SuiteResult"]:
        """Load and run all eval suites, optionally filtered by agent name."""
        suites = EvalSuite.load_all(project_dir)
        if not suites:
            return []

        if agent_filter:
            suites = [s for s in suites if s.agent == agent_filter]

        results = []
        for suite in suites:
            result = await cls.run(suite, pool, settings, project_dir)
            results.append(result)
        return results


def _setup_fixtures(
    fixtures: list[dict] | None,
    fallback_dir: Path,
) -> Path:
    """Set up a temp directory with fixtures. Returns the work directory."""
    work_dir = Path(tempfile.mkdtemp(prefix="ember-eval-"))
    if not fixtures:
        return work_dir

    for fix in fixtures:
        src = fallback_dir / fix.get("source", "")
        target = Path(fix.get("target", ""))
        if src.exists() and target.parts:
            target.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, target, dirs_exist_ok=True)
            else:
                shutil.copy2(src, target)
    return work_dir


def _cleanup_work_dir(work_dir: Path) -> None:
    """Remove the temporary work directory."""
    try:
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception as exc:
        logger.debug("Failed to clean up eval work dir %s: %s", work_dir, exc)


async def _run_reliability(
    response: Any,
    expected: list[str],
) -> tuple[bool, str]:
    """Run Agno ReliabilityEval on the response."""
    try:
        from agno.eval.reliability import ReliabilityEval

        rel = ReliabilityEval(
            agent_response=response,
            expected_tool_calls=expected,
            print_results=False,
            telemetry=False,
        )
        result = await rel.arun(print_results=False)
        if result is None:
            return False, "reliability eval returned None"
        if result.eval_status == "PASSED":
            return True, "all expected tools called"
        failed = ", ".join(result.failed_tool_calls) if result.failed_tool_calls else "unknown"
        return False, f"missing tool calls: {failed}"
    except Exception as exc:
        return False, f"reliability eval error: {exc}"


async def _run_accuracy(
    agent: Any,
    case: EvalCase,
    output_text: str,
    judge_model: Any,
) -> tuple[bool, float | None, str]:
    """Run Agno AccuracyEval using already-obtained output."""
    try:
        from agno.eval.accuracy import AccuracyEval

        acc = AccuracyEval(
            agent=agent,
            input=case.input,
            expected_output=case.expected_output,
            model=judge_model,
            additional_guidelines=case.judge_guidelines,
            num_iterations=case.num_iterations,
            print_summary=False,
            print_results=False,
            telemetry=False,
        )
        result = await acc.arun_with_output(
            output=output_text,
            print_summary=False,
            print_results=False,
        )
        if result is None:
            return False, None, "accuracy eval returned None"
        score = result.avg_score
        threshold = case.accuracy_threshold
        passed = score >= threshold
        return passed, score, f"score {score:.1f}/{threshold}"
    except Exception as exc:
        return False, None, f"accuracy eval error: {exc}"


async def run_eval_case(
    case: EvalCase,
    agent: Any,
    judge_model: Any | None,
) -> CaseResult:
    """Run a single eval case against a built agent."""
    result = CaseResult(case=case)
    start = time.monotonic()

    try:
        # Run the agent
        response = await agent.arun(case.input, stream=False)
        output_text = ""
        content = getattr(response, "content", None)
        if isinstance(content, str):
            output_text = content
        elif content is not None:
            output_text = str(content)

        all_passed = True

        # 1. ReliabilityEval — expected tool calls
        if case.expected_tool_calls:
            passed, detail = await _run_reliability(response, case.expected_tool_calls)
            result.reliability_passed = passed
            result.reliability_detail = detail
            if not passed:
                all_passed = False

        # 2. Unexpected tool calls (custom check)
        if case.unexpected_tool_calls:
            passed, detail = check_unexpected_tool_calls(response, case.unexpected_tool_calls)
            result.unexpected_passed = passed
            result.unexpected_detail = detail
            if not passed:
                all_passed = False

        # 3. AccuracyEval — output quality
        if case.expected_output and judge_model:
            passed, score, detail = await _run_accuracy(
                agent,
                case,
                output_text,
                judge_model,
            )
            result.accuracy_passed = passed
            result.accuracy_score = score
            if not passed:
                all_passed = False

        # 4. File assertions
        if case.file_assertions:
            for assertion in case.file_assertions:
                passed, detail = check_file_assertion(assertion)
                result.file_results.append((assertion.get("type", ""), passed, detail))
                if not passed:
                    all_passed = False

        result.passed = all_passed

    except Exception as exc:
        result.error = str(exc)
        result.passed = False

    result.elapsed = time.monotonic() - start
    return result
