import pytest
from urllib import parse

url = "https://google.com/foobar"


def call_mocked_function() -> int:
    assert parse.urlparse(url).path == "/foobar"
    assert parse.quote("foo") == "foo"
    assert parse.parse_qs("foo=bar") == {"foo": ["bar"]}
    return 123


@pytest.fixture()
def indirect_fixture():
    call_mocked_function()


@pytest.fixture()
def teardown_fixture():
    call_mocked_function()
    yield
    call_mocked_function()


@pytest.fixture()
def fixture(request: pytest.FixtureRequest):
    request.getfixturevalue("indirect_fixture")
    call_mocked_function()
    return


def test_case(teardown_fixture, fixture):
    call_mocked_function()
    assert True
