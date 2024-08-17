import abc
import threading
from datetime import datetime
from typing import Literal

import pydantic
from pydantic import computed_field
from pydantic.fields import Field

from .timer import now, Duration


def get_worker_field_default() -> str:
    # Work around circular imports. to-do: refactor this
    from .plugin_xdist import get_worker_id

    return get_worker_id()


class Meta(pydantic.BaseModel):
    worker: str = Field(default_factory=get_worker_field_default)
    recorded_at: datetime = Field(default_factory=now)
    thread_name: str = Field(default_factory=lambda: threading.current_thread().name)


class BaseTiming(pydantic.BaseModel, abc.ABC):
    meta: Meta = Field(default_factory=Meta)


class GCTiming(BaseTiming):
    type: Literal["gc"] = "gc"

    runtime: Duration
    collected_count: int
    generation: int


class CollectionTiming(BaseTiming):
    type: Literal["collection"] = "collection"

    runtime: Duration


class WorkerTiming(BaseTiming):
    type: Literal["worker"] = "worker"

    ready: Duration
    runtime: Duration | None = None


class BaseMockTiming(BaseTiming, abc.ABC):
    name: str
    test_id: str | None
    fixture_name: str | None

    runtime: Duration


class MockTiming(BaseMockTiming):
    type: Literal["mock"] = "mock"


class DjangoSQLTiming(BaseMockTiming):
    type: Literal["django-sql"] = "django-sql"
    sql_hash: str
    sql: str | None


class TestTiming(BaseTiming):
    type: Literal["test"] = "test"

    name: str
    test_id: str
    requires: list[str]

    runtime: Duration


class FixtureTiming(BaseTiming):
    type: Literal["fixture"] = "fixture"

    name: str
    short_name: str
    test_id: str | None
    scope: str

    setup: Duration
    teardown: Duration | None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def runtime(self) -> Duration:
        if self.teardown is not None:
            return self.setup + self.teardown
        return self.setup
