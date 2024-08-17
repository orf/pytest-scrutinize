import gzip
from pathlib import Path
from typing import Callable

import pytest
from _pytest.pytester import RunResult, Pytester

from pytest_scrutinize import Timing, TimingAdapter

pytest_plugins = [
    "pytester",
]


def read_results_file(path: Path) -> list[Timing]:
    with gzip.open(path, mode="rt") as fd:
        return [TimingAdapter.validate_json(line) for line in fd]


@pytest.fixture(params=[True, False], ids=["xdist", "normal"])
def with_xdist(request) -> bool:
    return request.param


@pytest.fixture()
def output_file(tmp_path) -> Path:
    return tmp_path / "output.jsonl.gz"


@pytest.fixture()
def run_tests(
    pytester_pretty: Pytester, with_xdist, output_file
) -> Callable[..., tuple[RunResult, list[Timing]]]:
    flags = []
    if with_xdist:
        flags.append("-n 2")

    def _run(test_name: str, *args: str):
        pytester_pretty.copy_example(test_name)
        result: RunResult = pytester_pretty.runpytest(
            "--scrutinize", output_file, *flags, *args
        )
        parsed_results = read_results_file(output_file)
        return result, parsed_results

    return _run
