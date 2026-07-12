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
