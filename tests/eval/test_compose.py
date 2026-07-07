"""Pure patch-composition used by seq / c3c4 eval (N patches from base)."""

from cooperbench.eval.sandbox import compose_filtered_patches


class TestComposeFilteredPatches:
    A = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b\n"
    B = "diff --git a/y.py b/y.py\n--- a/y.py\n+++ b/y.py\n@@ -1 +1 @@\n-c\n+d\n"
    TESTS = "diff --git a/tests/test_z.py b/tests/test_z.py\n--- a/tests/test_z.py\n+++ b/tests/test_z.py\n@@ -1 +1 @@\n-e\n+f\n"

    def test_single_patch_roundtrips(self):
        out = compose_filtered_patches(self.A)
        assert "x.py" in out and out.endswith("\n")

    def test_concatenates_in_order(self):
        out = compose_filtered_patches(self.A, self.B)
        assert out.index("x.py") < out.index("y.py")

    def test_three_patches(self):
        C = "diff --git a/z.py b/z.py\n--- a/z.py\n+++ b/z.py\n@@ -1 +1 @@\n-g\n+h\n"
        out = compose_filtered_patches(self.A, self.B, C)
        assert "x.py" in out and "y.py" in out and "z.py" in out

    def test_filters_test_files(self):
        out = compose_filtered_patches(self.A, self.TESTS)
        assert "x.py" in out and "test_z.py" not in out

    def test_skips_empty_and_none(self):
        out = compose_filtered_patches(self.A, "", None, self.B)
        assert "x.py" in out and "y.py" in out

    def test_all_empty_returns_empty(self):
        assert compose_filtered_patches("", None) == ""
