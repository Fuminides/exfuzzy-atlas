"""Pack the published models the integration tests use (``tests/integration``) into one tarball for CI.

    python scripts/qa/qa_bundle.py --out <dir> [--published artifacts/published] [--exclude nyc_pickups_h1]

The tarball holds ``published/registry.json`` restricted to the QA tasks that are kept and each of their model
directories, unchanged (``SHA256SUMS`` included, so the store verifies them as it does locally). It is uploaded as an
asset of the release ``qa-artifacts`` of a separate private repo (see ``docs/qa/README.md``); CI downloads it and runs
``make qa``.
Excluded tasks are left out of the registry, so their tests skip with "not in the published registry".
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests" / "integration"))
from qa_support import TASK_IDS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--published", type=Path, default=Path("artifacts/published"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--exclude", nargs="*", default=[], choices=TASK_IDS)
    args = ap.parse_args()

    registry = json.loads((args.published / "registry.json").read_text(encoding="utf-8"))
    # a QA task that is no longer served (Madrid, retired on 2026-11-09) is left out like an excluded one
    tasks = {t: registry["tasks"][t] for t in TASK_IDS if t not in args.exclude and t in registry["tasks"]}
    kept = {**registry, "tasks": tasks}
    args.out.mkdir(parents=True, exist_ok=True)
    reg_path = args.out / "registry.json"
    reg_path.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    tar_path = args.out / "qa-published.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(reg_path, arcname="published/registry.json")
        for task in tasks.values():
            model_dir = args.published / task["model_id"]
            tar.add(model_dir, arcname=f"published/{task['model_id']}")
    digest = hashlib.sha256(tar_path.read_bytes()).hexdigest()
    (args.out / "qa-published.tar.gz.sha256").write_text(f"{digest}  qa-published.tar.gz\n", encoding="utf-8")
    size = tar_path.stat().st_size / 2**20
    print(f"{tar_path} ({size:.1f} MiB, sha256 {digest[:12]}…): {', '.join(tasks)}")


if __name__ == "__main__":
    main()
