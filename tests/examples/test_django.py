import pytest
from tests.django_app.models import DummyModel


@pytest.fixture()
def teardown_fixture():
    DummyModel.objects.create(foo="foobar")
    yield
    DummyModel.objects.create(foo="foobar")


@pytest.fixture()
def fixture():
    DummyModel.objects.create(foo="foobar")


@pytest.mark.django_db
def test_case(teardown_fixture, fixture):
    obj = DummyModel.objects.create(foo="foobar")
    assert DummyModel.objects.count() == 3
    assert len(list(DummyModel.objects.all())) == 3
    obj.delete()
