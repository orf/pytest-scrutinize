import contextlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable, Self, Literal
from unittest import mock
import hashlib
import pydantic

from pytest_scrutinize.io import TimingsOutputFile
from pytest_scrutinize.timer import measure_time, Duration
from pytest_scrutinize.data import MockTiming, DjangoSQLTiming, BaseMockTiming


class SingleMockRecorder(pydantic.BaseModel):
    name: str
    mocked: Any
    original_callable: Callable

    @classmethod
    def from_dotted_path(cls, name: str, mock_path: str, **kwargs) -> Self:
        class_path, attribute_name = mock_path.rsplit(".", 1)
        original_object = pkgutil.resolve_name(class_path)
        original_callable = getattr(original_object, attribute_name)
        mocked = mock.patch(mock_path, side_effect=None, autospec=True)
        return cls(
            name=name, mocked=mocked, original_callable=original_callable, **kwargs
        )

    def record_timing(
        self,
        fixture_name: str | None,
        elapsed: Duration,
        test_id: str | None,
        *,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> BaseMockTiming:
        return MockTiming(
            fixture_name=fixture_name,
            runtime=elapsed,
            name=self.name,
            test_id=test_id,
        )

    @contextlib.contextmanager
    def record_mock(
        self, output: TimingsOutputFile, test_id: str | None, fixture_name: str | None
    ):
        if self.mocked.kwargs["side_effect"] is not None:
            raise RuntimeError(f"Recursive mock call for mock {self}")

        def wrapped(*args, **kwargs):
            with measure_time() as timer:
                result = self.original_callable(*args, **kwargs)
            output.add_timing(
                self.record_timing(
                    fixture_name, timer.elapsed, test_id, args=args, kwargs=kwargs
                )
            )
            return result

        self.mocked.kwargs["side_effect"] = wrapped
        try:
            with self.mocked:
                yield
        finally:
            self.mocked.kwargs["side_effect"] = None


class DjangoSQLRecorder(SingleMockRecorder):
    mode: Literal[True, "query"]

    def record_timing(
        self,
        fixture_name: str | None,
        elapsed: Duration,
        test_id: str | None,
        *,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> DjangoSQLTiming:
        # The django.db.backends.utils.CursorWrapper._execute function takes the
        # SQL as the second argument (the first being `self`):
        query: str | bytes = args[1]
        query_str = query
        if isinstance(query, str):
            query = query.encode()
        else:
            query_str = query.decode()
        sql_hash = hashlib.sha256(query, usedforsecurity=False).hexdigest()

        sql = None
        if self.mode == "query":
            # Include the full query here
            sql = query_str
        return DjangoSQLTiming(
            fixture_name=fixture_name,
            runtime=elapsed,
            name=self.name,
            test_id=test_id,
            sql_hash=sql_hash,
            sql=sql,
        )


@dataclass
class MockRecorder:
    mocks: frozenset[str]
    output: TimingsOutputFile
    enable_django_sql: Literal[True, "query"] | None

    _mock_funcs: dict[str, SingleMockRecorder] = field(default_factory=dict)

    @contextlib.contextmanager
    def record(self, test_id: str | None, fixture_name: str | None):
        # We want to avoid recursive mock calls, which can happen when using `getfixturevalue`.
        # Detecting if something is a mock is a pain, so we just use a token-style system:
        # we take the entire _mock_funcs dictionary when we set up the mocks, and replace it
        # when we are done.

        if not self._mock_funcs:
            yield
            return

        mock_funcs = self._mock_funcs
        self._mock_funcs = {}

        try:
            with contextlib.ExitStack() as stack:
                for single_mock in mock_funcs.values():
                    stack.enter_context(
                        single_mock.record_mock(self.output, test_id, fixture_name)
                    )
                yield
        finally:
            self._mock_funcs = mock_funcs

    @contextlib.contextmanager
    def initialize_mocks(self):
        for mock_path in self.mocks:
            self._mock_funcs[mock_path] = SingleMockRecorder.from_dotted_path(
                name=mock_path, mock_path=mock_path
            )

        if self.enable_django_sql is not None:
            self._mock_funcs["django_sql"] = DjangoSQLRecorder.from_dotted_path(
                name="django_sql",
                mock_path="django.db.backends.utils.CursorWrapper._execute",
                mode=self.enable_django_sql,
            )

        try:
            yield
        finally:
            self._mock_funcs.clear()
