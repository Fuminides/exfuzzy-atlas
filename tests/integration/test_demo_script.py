"""B2 (AT-061): `make demo` serves with several workers and no reload; `make api` keeps --reload; `make qa-volume`."""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEMO = (REPO / "scripts/qa/demo.sh").read_text()
MAKEFILE = (REPO / "Makefile").read_text()


def uvicorn_lines(text):
    return [line for line in text.splitlines() if "uvicorn" in line and not line.lstrip().startswith("#")]


def test_demo_runs_uvicorn_with_configurable_workers_and_no_reload():
    (line,) = uvicorn_lines(DEMO)
    assert '--workers "$WORKERS"' in line and "--reload" not in line
    assert 'WORKERS="${ATLAS_API_WORKERS:-2}"' in DEMO


def test_demo_refuses_a_bad_worker_count_before_doing_anything_else(tmp_path):
    for bad in ("0", "two", "-1"):
        run = subprocess.run(
            ["bash", str(REPO / "scripts/qa/demo.sh")], capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "ATLAS_API_WORKERS": bad,
                 "ATLAS_PUBLISHED_DIR": str(tmp_path)},
        )
        assert run.returncode == 1 and "ATLAS_API_WORKERS" in run.stderr


def test_make_api_keeps_reload_and_qa_volume_exists():
    api = re.search(r"^api:\n\t(.*)$", MAKEFILE, re.M).group(1)
    assert "--reload" in api and "--workers" not in api
    volume = re.search(r"^qa-volume:\n\t(.*)$", MAKEFILE, re.M).group(1)
    assert "ATLAS_QA_VOLUME=1" in volume and "test_volume_budget.py" in volume
    assert "qa-volume" in MAKEFILE.split(".PHONY:")[1].splitlines()[0]
