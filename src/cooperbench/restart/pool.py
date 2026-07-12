"""Feature pool for the restart-vs-iterate loop.

The loop's task unit is a single feature; the pool is every distinct
(repo, task_id, feature_id) appearing in a subset's pairs, frozen and
sorted so all policies see the same features in the same order.
"""

from pathlib import Path

from cooperbench.runner.tasks import load_subset


def build_feature_pool(subset_name: str, dataset_dir: Path | str | None = None) -> list[dict]:
    subset = load_subset(subset_name, dataset_dir=dataset_dir)
    triples: set[tuple[str, int, int]] = set()
    for (repo, task_id), pairs in subset["pairs"].items():
        for pair in pairs:
            for feature_id in pair:
                triples.add((repo, task_id, feature_id))
    return [
        {"repo": repo, "task_id": task_id, "feature_id": feature_id}
        for repo, task_id, feature_id in sorted(triples)
    ]
