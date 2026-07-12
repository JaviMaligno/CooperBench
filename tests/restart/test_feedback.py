from cooperbench.restart.feedback import format_feedback


class TestFormatFeedback:
    def test_failing_result_includes_counts_and_tail(self):
        fb = format_feedback(
            {"passed": False, "tests_passed": 3, "tests_failed": 2,
             "output": "x" * 5000 + "FAILED test_foo - AssertionError", "error": None},
            round_idx=1,
        )
        assert "Round 1" in fb
        assert "3 passed, 2 failed" in fb
        assert "FAILED test_foo" in fb
        assert len(fb) < 3000

    def test_truncation_keeps_the_tail_not_the_head(self):
        out = "HEAD" + "y" * 5000 + "TAIL"
        fb = format_feedback({"passed": False, "tests_passed": 0,
                              "tests_failed": 1, "output": out, "error": None}, 2)
        assert "TAIL" in fb and "HEAD" not in fb

    def test_passing_result(self):
        fb = format_feedback({"passed": True, "tests_passed": 7,
                              "tests_failed": 0, "output": "all good", "error": None}, 3)
        assert "ALL TESTS PASSED" in fb

    def test_infra_error_is_labeled(self):
        fb = format_feedback({"passed": False, "tests_passed": 0, "tests_failed": 0,
                              "output": "", "error": "sandbox timeout"}, 1)
        assert "HARNESS ERROR" in fb and "sandbox timeout" in fb
