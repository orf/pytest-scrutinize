import contextlib
import gzip
import typing
from dataclasses import dataclass, field
from pathlib import Path

if typing.TYPE_CHECKING:
    from pytest_scrutinize.data import BaseTiming


@dataclass
class TimingsOutputFile:
    path: Path
    buffer: list["BaseTiming"] = field(default_factory=list)

    fd: typing.TextIO | None = None

    def add_timing(self, timing: "BaseTiming"):
        self.buffer.append(timing)

    def flush_buffer(self):
        if self.fd is None:
            raise RuntimeError("Output file not opened")
        # Get a reference to the buffer, then replace it with an
        # empty list. We do this because the GC callbacks _could_
        # cause an append to the list mid-iteration, or after the
        # write loop has finished.
        buffer = self.buffer
        self.buffer = []
        for timing in buffer:
            self.fd.write(timing.model_dump_json())
            self.fd.write("\n")

    @contextlib.contextmanager
    def initialize_writer(self) -> typing.Generator[typing.TextIO, None, None]:
        if self.fd is not None:
            raise RuntimeError("Output file already opened")

        with gzip.open(self.path, mode="wt", compresslevel=1) as fd:
            self.fd = fd
            try:
                yield fd
            finally:
                self.flush_buffer()
                self.fd = None

    @contextlib.contextmanager
    def get_reader(self) -> typing.Generator[typing.TextIO, None, None]:
        if self.fd is not None:
            raise RuntimeError("Output file not closed")

        with gzip.open(self.path, mode="rt") as fd:
            yield fd
