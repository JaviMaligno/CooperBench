"""Uniform test-feedback block shown to the agent after each round."""


def format_feedback(test_result: dict, round_idx: int, max_output_chars: int = 2000) -> str:
    if test_result.get("error"):
        return (
            f"## Test results — Round {round_idx}\n"
            f"HARNESS ERROR (does not reflect your code): {test_result['error']}\n"
        )
    passed = test_result.get("tests_passed", 0)
    failed = test_result.get("tests_failed", 0)
    if test_result.get("passed"):
        return (
            f"## Test results — Round {round_idx}\n"
            f"ALL TESTS PASSED ({passed} passed).\n"
        )
    output = test_result.get("output", "") or ""
    if len(output) > max_output_chars:
        output = "…(truncated)…\n" + output[-max_output_chars:]
    return (
        f"## Test results — Round {round_idx}\n"
        f"{passed} passed, {failed} failed.\n\n"
        f"Failing test output (tail):\n```\n{output}\n```\n"
    )
