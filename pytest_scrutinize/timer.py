import contextlib
import dataclasses
import time
from datetime import datetime, UTC, timedelta
from typing import Generator

import pydantic
from pydantic import computed_field
from types import SimpleNamespace

# Freezegun (and likely other similar libraries) does some insane stuff to try and ensure that
# time.* and datetime.* functions are patched - it scans every module and looks for any module
# level attribute that is a function it is patching, then patches it.
# We store the original functions inside a class so that it is not replaced under our feet.

_time_funcs = SimpleNamespace(perf_ns=time.perf_counter_ns, now=datetime.now)


def now() -> datetime:
    return _time_funcs.now(tz=UTC)


@contextlib.contextmanager
def measure_time() -> Generator["Timer", None, None]:
    with Timer() as timer:
        yield timer


@dataclasses.dataclass
class Timer:
    _start: int | None = None
    _end: int | None = None

    @property
    def elapsed(self) -> "Duration":
        if self._start is None:
            raise RuntimeError("Timer not started")

        end = _time_funcs.perf_ns() if self._end is None else self._end
        return Duration(as_nanoseconds=end - self._start)

    def start(self):
        self.reset()
        self._start = _time_funcs.perf_ns()

    def stop(self):
        self._end = _time_funcs.perf_ns()

    def reset(self):
        self._start, self._end = None, None

    def __enter__(self) -> "Timer":
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


class Duration(pydantic.BaseModel):
    as_nanoseconds: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def as_microseconds(self) -> int:
        return self.as_nanoseconds // 1_000

    @computed_field  # type: ignore[prop-decorator]
    @property
    def as_iso(self) -> timedelta:
        return timedelta(microseconds=self.as_microseconds)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def as_text(self) -> str:
        return f"{self.as_microseconds} microseconds"

    def __add__(self, other: "Duration") -> "Duration":
        return Duration(as_nanoseconds=self.as_nanoseconds + other.as_nanoseconds)
