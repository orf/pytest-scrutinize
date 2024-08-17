import contextlib
import gc
import shutil
import tempfile
import typing
from pathlib import Path
from typing import Literal

import pydantic
import pytest

from .io import TimingsOutputFile
from .mocks import MockRecorder
from .data import (
    CollectionTiming,
    FixtureTiming,
    TestTiming,
    GCTiming,
)
from .utils import is_generator_fixture
from .timer import Timer, measure_time

if typing.TYPE_CHECKING:
    from _pytest.fixtures import FixtureDef, SubRequest


@pytest.hookimpl
def pytest_addoption(parser: pytest.Parser):
    group = parser.getgroup("scrutinize", "Structured timing output")
    group.addoption(
        "--scrutinize",
        metavar="N",
        action="store",
        type=Path,
        help="Store structured timing output to this file",
    )
    group.addoption(
        "--scrutinize-func",
        action="append",
        type=str,
        nargs="?",
        help="Comma separated list of functions to record",
    )
    group.addoption(
        "--scrutinize-gc", action="store_true", help="Record garbage collections"
    )
    group.addoption(
        "--scrutinize-django-sql",
        nargs="?",
        choices=["hash", "query"],
        default=False,
        const=True,
        help="Record Django SQL queries",
    )


class Config(pydantic.BaseModel):
    output_path: Path
    mocks: frozenset[str]
    enable_gc: bool
    enable_django_sql: Literal[True, "query"] | None


def pytest_configure(config: pytest.Config):
    if output_path := config.getoption("--scrutinize"):
        assert isinstance(output_path, Path)

        enable_gc = typing.cast(bool, config.getoption("--scrutinize-gc") or False)

        enable_django_sql = typing.cast(
            Literal[True, "query"] | None,
            config.getoption("--scrutinize-django-sql") or None,
        )

        mocks = typing.cast(list[str], config.getoption("--scrutinize-func"))
        if mocks is None:
            mocks = frozenset()
        else:
            mocks = {
                stripped_mock
                for mocks_arg in mocks
                for mock_path in mocks_arg.split(",")
                if (stripped_mock := mock_path.strip())
            }
        plugin_config = Config(
            output_path=output_path,
            mocks=frozenset(mocks),
            enable_gc=enable_gc,
            enable_django_sql=enable_django_sql,
        )

        plugin_cls: type[DetailedTimingsPlugin]
        has_xdist = config.pluginmanager.get_plugin("xdist") is not None

        from . import plugin_xdist

        is_xdist_master = plugin_xdist.is_master()
        match (has_xdist, is_xdist_master):
            case (True, True):
                plugin_cls = plugin_xdist.XDistMasterDetailedTimingsPlugin
            case (True, False):
                plugin_cls = plugin_xdist.XDistWorkerDetailedTimingsPlugin
            case (False, _):
                plugin_cls = DetailedTimingsPlugin
            case _:
                assert False, f"unreachable: {has_xdist=} {is_xdist_master=}"

        plugin = plugin_cls(plugin_config)
        config.pluginmanager.register(plugin, name=__name__)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtestloop(session: pytest.Session):
    if plugin := session.config.pluginmanager.get_plugin(__name__):
        with plugin.run(session):
            yield
    else:
        yield


class DetailedTimingsPlugin:
    config: Config
    output: TimingsOutputFile
    mock_recorder: MockRecorder

    def __init__(self, config: Config):
        self.config = config

        temp_dir = Path(tempfile.mkdtemp())
        temp_output_path = temp_dir / "output.jsonl.gz"
        self.output = TimingsOutputFile(temp_output_path)
        self.mock_recorder = MockRecorder(
            mocks=config.mocks,
            output=self.output,
            enable_django_sql=self.config.enable_django_sql,
        )

        if config.enable_gc:
            self.setup_gc_callbacks()

    @contextlib.contextmanager
    def run(self, session: pytest.Session) -> typing.Generator[typing.Self, None, None]:
        with self.output.initialize_writer(), self.mock_recorder.initialize_mocks():
            yield self

        self.create_final_output_file(session)

    def create_final_output_file(self, session: pytest.Session):
        shutil.move(src=self.output.path, dst=self.config.output_path)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_collection(self, session: pytest.Session):
        with measure_time() as timer:
            yield

        self.output.add_timing(CollectionTiming(runtime=timer.elapsed))

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: pytest.Item, nextitem: pytest.Item | None):
        try:
            yield
        finally:
            self.output.flush_buffer()

    @pytest.hookimpl(hookwrapper=True)
    def pytest_pyfunc_call(self, pyfuncitem: pytest.Function):
        with self.mock_recorder.record(test_id=pyfuncitem.nodeid, fixture_name=None):
            with measure_time() as timer:
                yield

        test_timing = TestTiming(
            name=pyfuncitem.name,
            test_id=pyfuncitem.nodeid,
            requires=pyfuncitem.fixturenames,
            runtime=timer.elapsed,
        )

        self.output.add_timing(test_timing)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef: "FixtureDef", request: "SubRequest"):
        is_function_scope = fixturedef.scope == "function"
        full_name = f"{fixturedef.func.__module__}.{fixturedef.func.__qualname__}"

        # Don't associate non-function scoped fixtures with a given test
        test_id = request.node.nodeid if is_function_scope else None

        setup_timer: Timer
        teardown_timer: Timer | None = None

        def fixture_done():
            nonlocal setup_timer, teardown_timer
            teardown_duration_ns = (
                teardown_timer.elapsed if teardown_timer is not None else None
            )

            self.output.add_timing(
                FixtureTiming(
                    name=full_name,
                    short_name=fixturedef.func.__qualname__,
                    test_id=test_id,
                    scope=request.scope,
                    setup=setup_timer.elapsed,
                    teardown=teardown_duration_ns,
                )
            )

        fixturedef.addfinalizer(fixture_done)

        if not is_generator_fixture(fixturedef.func):
            with self.mock_recorder.record(test_id=test_id, fixture_name=full_name):
                with measure_time() as setup_timer:
                    yield
        else:
            # We want to capture the teardown times for fixtures. This is non-trivial as
            # pytest exposes no hooks to allow you to do this.
            # However, we can use finalizers for this: we first attach a finalizer _before_
            # the fixture is executed, then attach a finalizer _after_ the fixture is executed.
            # Pytest hooks are run in reverse order: the first hook to run
            # will be the `record_teardown_finish` finalizer, and the first will be the `record_teardown_start`.

            teardown_mock_capture: typing.ContextManager | None = None
            teardown_timer = Timer()

            def teardown_fixture_start():
                nonlocal teardown_mock_capture
                teardown_mock_capture = self.mock_recorder.record(
                    test_id=test_id, fixture_name=full_name
                )
                teardown_mock_capture.__enter__()
                teardown_timer.__enter__()

            def teardown_fixture_finish():
                teardown_timer.__exit__(None, None, None)
                if teardown_mock_capture is not None:
                    teardown_mock_capture.__exit__(None, None, None)

            fixturedef.addfinalizer(teardown_fixture_finish)
            with self.mock_recorder.record(test_id=test_id, fixture_name=full_name):
                with measure_time() as setup_timer:
                    yield

            fixturedef.addfinalizer(teardown_fixture_start)

    def setup_gc_callbacks(self):
        gc_timer = Timer()

        def gc_callback(phase: Literal["start", "stop"], info: dict[str, int]):
            if phase == "start":
                gc_timer.start()
            else:
                gc_timer.stop()

                self.output.add_timing(
                    GCTiming(
                        runtime=gc_timer.elapsed,
                        collected_count=info["collected"],
                        generation=info["generation"],
                    )
                )

        gc.callbacks.append(gc_callback)
