"""Eval reporter — format eval results for terminal output."""

from ember_code.core.evals.runner import CaseResult, SuiteResult


def _case_details(result: CaseResult) -> list[str]:
    """Return detail lines for a failed case."""
    details: list[str] = []
    if result.error:
        details.append(f"    error: {result.error}")
    if result.reliability_passed is False:
        details.append(f"    reliability: {result.reliability_detail}")
    if result.unexpected_passed is False:
        details.append(f"    {result.unexpected_detail}")
    if result.accuracy_passed is False:
        details.append(f"    accuracy: score {result.accuracy_score or '?'}")
    for atype, passed, detail in result.file_results:
        if not passed:
            details.append(f"    {atype}: {detail}")
    return details


def format_results(results: list[SuiteResult]) -> str:
    """Format eval results as a readable report string."""
    lines: list[str] = ["## Eval Results", ""]

    total_passed = 0
    total_failed = 0
    total_elapsed = 0.0

    for suite_result in results:
        suite = suite_result.suite
        lines.append(f"**{suite.agent}** ({suite_result.total} cases)")

        for cr in suite_result.case_results:
            extras: list[str] = []
            if cr.reliability_passed is not None:
                extras.append(f"reliability: {'PASS' if cr.reliability_passed else 'FAIL'}")
            if cr.accuracy_score is not None:
                extras.append(f"accuracy: {cr.accuracy_score:.1f}")
            if cr.file_results:
                file_ok = all(p for _, p, _ in cr.file_results)
                extras.append(f"files: {'PASS' if file_ok else 'FAIL'}")

            extra_str = f"  [{', '.join(extras)}]" if extras else ""
            symbol = "+" if cr.passed else "x"
            lines.append(f"  {symbol} {cr.case.name:<35} {cr.elapsed:.1f}s{extra_str}")

            if not cr.passed:
                for detail in _case_details(cr):
                    lines.append(detail)

        lines.append(f"  {suite_result.passed}/{suite_result.total} passed")
        lines.append("")

        total_passed += suite_result.passed
        total_failed += suite_result.failed
        total_elapsed += suite_result.elapsed

    total = total_passed + total_failed
    lines.append("---")
    lines.append(
        f"**Total: {total_passed}/{total} passed "
        f"({total_passed * 100 // total if total else 0}%) "
        f"in {total_elapsed:.1f}s**"
    )
    if total_failed:
        failed_names = [
            f"{sr.suite.agent}.{cr.case.name}"
            for sr in results
            for cr in sr.case_results
            if not cr.passed
        ]
        lines.append(f"Failed: {', '.join(failed_names)}")

    return "\n".join(lines)
