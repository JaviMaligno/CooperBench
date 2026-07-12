import json

from cooperbench.restart.pool import build_feature_pool


def _write_subset(tmp_path, name="tiny"):
    (tmp_path / "subsets").mkdir()
    (tmp_path / "subsets" / f"{name}.json").write_text(json.dumps({
        "name": name,
        "tasks": [
            {"repo": "repo_b", "task_id": 2, "pairs": [[1, 5], [5, 7]]},
            {"repo": "repo_a", "task_id": 9, "pairs": [[2, 3]]},
        ],
    }))
    return name


class TestBuildFeaturePool:
    def test_dedupes_and_sorts(self, tmp_path):
        name = _write_subset(tmp_path)
        pool = build_feature_pool(name, dataset_dir=tmp_path)
        assert pool == [
            {"repo": "repo_a", "task_id": 9, "feature_id": 2},
            {"repo": "repo_a", "task_id": 9, "feature_id": 3},
            {"repo": "repo_b", "task_id": 2, "feature_id": 1},
            {"repo": "repo_b", "task_id": 2, "feature_id": 5},  # deduped (in 2 pairs)
            {"repo": "repo_b", "task_id": 2, "feature_id": 7},
        ]

    def test_real_flash_amd64_has_29(self):
        pool = build_feature_pool("flash_amd64")
        assert len(pool) == 29
