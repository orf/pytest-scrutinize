import gc

import pytest


@pytest.fixture()
def teardown_fixture():
    yield


@pytest.fixture()
def fixture():
    return


def test_case(teardown_fixture, fixture):
    # Force a collection, for --scrutinize-gc tests
    gc.collect()
    assert True
