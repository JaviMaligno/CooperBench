from restart_metrics import curve, is_plateau, mcnemar


class TestCurve:
    def test_extracts_tests_passed_sequence(self):
        rounds = [{"round": 1, "tests_passed": 2, "passed": False},
                  {"round": 2, "tests_passed": 4, "passed": False}]
        assert curve(rounds) == [2, 4]


class TestPlateau:
    def test_flat_tail_is_plateau(self):
        assert is_plateau([2, 3, 3, 3]) is True

    def test_still_growing_is_not(self):
        assert is_plateau([1, 2, 3, 4]) is False

    def test_solved_run_is_never_plateau(self):
        assert is_plateau([2, 5, 5], solved=True) is False

    def test_too_short_is_not(self):
        assert is_plateau([2]) is False


class TestMcNemar:
    def test_matches_known_values(self):
        assert mcnemar(0, 0) == 1.0
        assert abs(mcnemar(8, 1) - 0.0390625) < 1e-6  # 2*(9C0+9C1)/2^9


class TestCurveExclusion:
    def test_error_rounds_excluded_from_curve(self):
        """curve([1, ERROR, 1]) should skip the error round."""
        rounds = [
            {"round": 1, "tests_passed": 1, "passed": False, "error": None},
            {"round": 2, "tests_passed": 0, "passed": False, "error": "docker flake"},
            {"round": 3, "tests_passed": 1, "passed": False, "error": None},
        ]
        assert curve(rounds) == [1, 1]

    def test_no_errors_unchanged(self):
        rounds = [
            {"round": 1, "tests_passed": 2, "passed": False, "error": None},
            {"round": 2, "tests_passed": 4, "passed": False, "error": None},
        ]
        assert curve(rounds) == [2, 4]


class TestPlateauWithErrors:
    def test_error_middle_not_plateau(self):
        """[1, ERROR, 1] after exclusion is [1, 1] — too short for plateau."""
        rounds = [
            {"round": 1, "tests_passed": 1, "passed": False, "error": None},
            {"round": 2, "tests_passed": 0, "passed": False, "error": "docker flake"},
            {"round": 3, "tests_passed": 1, "passed": False, "error": None},
        ]
        assert is_plateau(curve(rounds)) is False


class TestSummarizeErrors:
    def test_all_error_rounds_feature_in_errors_count(self, tmp_path, capsys):
        """A feature whose every round has an error appears in errors count, not plain fail."""
        from restart_metrics import summarize
        results = {
            "repo:1:1": {
                "solved": False,
                "solve_round": None,
                "total_cost": 0.0,
                "rounds": [
                    {"round": 1, "tests_passed": 0, "passed": False, "error": "cost cap"},
                    {"round": 2, "tests_passed": 0, "passed": False, "error": "cost cap"},
                ],
            }
        }
        summarize("test-run", results)
        captured = capsys.readouterr()
        assert "errors 1" in captured.out

    def test_no_error_features_errors_zero(self, tmp_path, capsys):
        from restart_metrics import summarize
        results = {
            "repo:1:1": {
                "solved": False,
                "solve_round": None,
                "total_cost": 0.0,
                "rounds": [
                    {"round": 1, "tests_passed": 2, "passed": False, "error": None},
                ],
            }
        }
        summarize("test-run", results)
        captured = capsys.readouterr()
        assert "errors 0" in captured.out

    def test_zero_round_crash_with_error_in_errors_count(self, capsys):
        """A feature with rounds: [] and top-level error appears in errors count."""
        from restart_metrics import summarize
        results = {
            "repo:1:1": {
                "solved": False,
                "solve_round": None,
                "total_cost": 0.0,
                "error": "boom",
                "rounds": [],
            }
        }
        summarize("test-run", results)
        captured = capsys.readouterr()
        assert "errors 1" in captured.out


class TestOldStyleFallback:
    def test_old_result_json_fallback_to_tests_json(self, tmp_path):
        """Old-style result.json (no error key in rounds) + tests.json with error → exclusion."""
        import json
        from restart_metrics import curve

        # Old-style round entry: no "error" key
        rounds_old = [
            {"round": 1, "tests_passed": 0, "passed": False},
            {"round": 2, "tests_passed": 2, "passed": False},
        ]

        # Simulate artifact dir with tests.json for round 1 carrying an error
        artifact_dir = tmp_path / "logs" / "run" / "restart" / "repo" / "1" / "f1"
        (artifact_dir / "round_1").mkdir(parents=True)
        (artifact_dir / "round_1" / "tests.json").write_text(
            json.dumps({"passed": False, "tests_passed": 0, "tests_failed": 2, "error": "docker flake"})
        )
        (artifact_dir / "round_2").mkdir(parents=True)
        (artifact_dir / "round_2" / "tests.json").write_text(
            json.dumps({"passed": False, "tests_passed": 2, "tests_failed": 1, "error": None})
        )

        result = {
            "repo": "repo", "task_id": 1, "feature_id": 1,
            "log_dir": str(artifact_dir),
            "rounds": rounds_old,
        }

        c = curve(result["rounds"], log_dir=result.get("log_dir"))
        assert c == [2], f"Expected [2] (round 1 excluded via fallback), got {c}"
