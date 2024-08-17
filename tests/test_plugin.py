import collections
import typing
from typing import Type, Hashable

import pytest
from _pytest.pytester import RunResult

from pytest_scrutinize import (
    Timing,
    CollectionTiming,
    WorkerTiming,
    TestTiming as PyTestTiming,
    FixtureTiming,
    MockTiming,
    DjangoSQLTiming,
    GCTiming,
)
from pytest_scrutinize.timer import Duration

T = typing.TypeVar("T", bound=Timing)


def get_timing_items(results: list[Timing], cls: Type[T]) -> list[T]:
    return [result for result in results if isinstance(result, cls)]


def assert_duration(duration: Duration | None):
    assert duration is not None
    assert duration.as_nanoseconds != 0
    assert duration.as_microseconds == duration.as_nanoseconds // 1_000


H = typing.TypeVar("H", bound=Hashable)


def assert_unique(items: typing.Iterable[H]) -> set[H]:
    items = list(items)
    unique = set(items)
    assert len(unique) == len(items)
    return unique


def assert_not_master(results: list[T]):
    for result in results:
        assert result.meta.worker != "master"


def assert_results_collection(results: list[Timing]):
    collection_times = get_timing_items(results, CollectionTiming)
    assert collection_times != []
    unique = assert_unique(ev.meta.worker for ev in collection_times)
    assert "master" in unique

    for collection in collection_times:
        assert_duration(collection.runtime)


def assert_xdist_workers_ready(results: list[Timing]):
    worker_ready = get_timing_items(results, WorkerTiming)
    assert worker_ready != []
    assert_unique(ev.meta.worker for ev in worker_ready)
    assert_not_master(worker_ready)
    for ev in worker_ready:
        assert_duration(ev.ready)
        assert_duration(ev.runtime)


def assert_tests(results: list[Timing], is_xdist: bool):
    test_timings = get_timing_items(results, PyTestTiming)
    assert test_timings != []
    assert_unique(ev.test_id for ev in test_timings)

    if is_xdist:
        assert_not_master(test_timings)

    for test_timing in test_timings:
        assert_duration(test_timing.runtime)


def assert_fixture(fixture: FixtureTiming, root_name: str):
    assert_duration(fixture.setup)

    if not fixture.name.startswith(f"{root_name}."):
        return

    if fixture.name.startswith(f"{root_name}.teardown_"):
        assert_duration(fixture.teardown)
    else:
        assert fixture.teardown is None


def assert_fixtures(results: list[Timing], is_xdist: bool, root_name: str):
    fixture_timings = get_timing_items(results, FixtureTiming)
    assert fixture_timings != []
    if is_xdist:
        assert_not_master(fixture_timings)

    test_names_map = {
        test.test_id: test for test in get_timing_items(results, PyTestTiming)
    }

    for fixture_timing in fixture_timings:
        if fixture_timing.test_id is not None:
            assert fixture_timing.test_id in test_names_map
        assert_fixture(fixture_timing, root_name)


def assert_mocks(results: list[Timing], is_xdist: bool, root_name: str):
    fixture_timings = get_timing_items(results, FixtureTiming)
    mock_timings = get_timing_items(results, MockTiming)
    assert mock_timings != []
    if is_xdist:
        assert_not_master(mock_timings)

    mock_names = {mock.name for mock in mock_timings}
    assert mock_names == {
        "urllib.parse.parse_qs",
        "urllib.parse.quote",
        "urllib.parse.urlparse",
    }

    assert set(
        mock.test_id.split("::")[1] for mock in mock_timings if mock.test_id
    ) == {"test_case"}

    fixture_map = {fixture.name: fixture for fixture in fixture_timings}

    # All fixtures should have called the mock, excluding the indirect fixture
    expected_fixtures = {
        f"{root_name}.fixture",
        f"{root_name}.teardown_fixture",
    }
    fixtures_calling_mock = {
        mock_timing.fixture_name
        for mock_timing in mock_timings
        if mock_timing.fixture_name is not None
    }
    assert fixtures_calling_mock == expected_fixtures

    for mock_timing in mock_timings:
        assert_duration(mock_timing.runtime)
        assert mock_timing.fixture_name or mock_timing.test_id
        if mock_timing.test_id:
            assert mock_timing.test_id == f"{root_name}.py::test_case"
        # Check that the fixture name is in the map
        if mock_timing.fixture_name is not None:
            assert mock_timing.fixture_name in fixture_map


def assert_suite(result: RunResult, timings: list[Timing], with_xdist: bool):
    result.assert_outcomes(passed=1)

    assert_results_collection(timings)
    assert_tests(timings, with_xdist)
    assert_fixtures(timings, with_xdist, root_name="test_suite")

    if with_xdist:
        assert_xdist_workers_ready(timings)


def test_simple(run_tests, output_file, with_xdist):
    result, timings = run_tests("test_simple.py")
    assert_suite(result, timings, with_xdist)


def test_mocks(run_tests, output_file, with_xdist):
    result, timings = run_tests(
        "test_mock.py",
        "--scrutinize-func=urllib.parse.urlparse,urllib.parse.parse_qs",
        "--scrutinize-func=urllib.parse.quote",
    )
    assert_suite(result, timings, with_xdist)
    assert_mocks(timings, with_xdist, root_name="test_mock")


def test_gc(run_tests, output_file, with_xdist):
    result, timings = run_tests("test_simple.py", "--scrutinize-gc")
    assert_suite(result, timings, with_xdist)
    gc_timings = get_timing_items(timings, GCTiming)
    assert gc_timings != []
    for gc_timing in gc_timings:
        assert_duration(gc_timing.runtime)

    if with_xdist:
        all_workers = {result.meta.worker for result in timings}
        assert all_workers != {"master"}


@pytest.mark.parametrize("with_query", [True, False])
def test_django(run_tests, output_file, with_xdist, with_query):
    flag = "--scrutinize-django-sql"
    if with_query:
        flag = f"{flag}=query"
    result, timings = run_tests(
        "test_django.py", "--ds=tests.django_app.settings", flag
    )
    assert_suite(result, timings, with_xdist)
    sql_timings = get_timing_items(timings, DjangoSQLTiming)
    assert sql_timings != []

    timings_by_fixture: dict[str, list[DjangoSQLTiming]] = collections.defaultdict(list)
    timings_by_test: dict[str, list[DjangoSQLTiming]] = collections.defaultdict(list)

    for sql_timing in sql_timings:
        assert_duration(sql_timing.runtime)
        if sql_timing.fixture_name:
            timings_by_fixture[sql_timing.fixture_name].append(sql_timing)
        elif sql_timing.test_id:
            # Only test queries, no fixtures at all
            timings_by_test[sql_timing.test_id].append(sql_timing)

    # All of our SQL hashes (and queries) should be the same
    sql_hashes = set(
        (timing.sql_hash, timing.sql)
        for fixture_name in ("test_django.teardown_fixture", "test_django.fixture")
        for timing in timings_by_fixture[fixture_name]
    )
    assert len(sql_hashes) == 1

    assert_unique(
        (timing.sql_hash, timing.sql)
        for timing in timings_by_test["test_django.py::test_case"]
    )


def test_all(run_tests, output_file, with_xdist):
    result, timings = run_tests(
        "test_simple.py",
        "--scrutinize-django-sql",
        "--scrutinize-gc",
        "--scrutinize-func=urllib.parse.urlparse",
    )
    assert_suite(result, timings, with_xdist)
