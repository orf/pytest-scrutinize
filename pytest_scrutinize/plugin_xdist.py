import os
import shutil
import typing

from pathlib import Path
from typing import Any, Sequence

import pytest

from pytest_scrutinize.plugin import DetailedTimingsPlugin
from pytest_scrutinize.data import WorkerTiming, Meta

from pytest_scrutinize.timer import Timer
from .io import TimingsOutputFile

if typing.TYPE_CHECKING:
    from .plugin import Config

    try:
        from xdist.workermanage import WorkerController
    except ImportError:
        pass


def get_worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def is_master() -> bool:
    return get_worker_id() == "master"


_worker_output_key = f"{__name__}.output"


class XDistWorkerDetailedTimingsPlugin(DetailedTimingsPlugin):
    @pytest.hookimpl()
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int):
        if workeroutput := getattr(session.config, "workeroutput", None):
            workeroutput[_worker_output_key] = str(self.output.path.absolute())

    def create_final_output_file(self, session: pytest.Session):
        return


class XDistMasterDetailedTimingsPlugin(DetailedTimingsPlugin):
    setup_nodes_timer: Timer
    worker_timings: dict[str, WorkerTiming]
    worker_output_files: list[Path]

    def __init__(self, config: "Config"):
        super().__init__(config=config)

        self.setup_nodes_timer = Timer()
        self.worker_timings = {}
        self.worker_output_files = []

    @pytest.hookimpl()
    def pytest_xdist_setupnodes(self, config: pytest.Config, specs: Sequence[Any]):
        self.setup_nodes_timer.start()

    @pytest.hookimpl()
    def pytest_testnodeready(self, node: "WorkerController"):
        duration = self.setup_nodes_timer.elapsed

        worker_id = node.workerinfo["id"]
        self.worker_timings[worker_id] = WorkerTiming(
            meta=Meta(worker=worker_id),
            ready=duration,
        )

    def create_final_output_file(self, session: pytest.Session):
        final_output_file = TimingsOutputFile(path=self.config.output_path)
        files_to_combine = [self.output.path] + self.worker_output_files

        with final_output_file.initialize_writer() as output_writer:
            for input_path in files_to_combine:
                with TimingsOutputFile(path=input_path).get_reader() as output_reader:
                    shutil.copyfileobj(fsrc=output_reader, fdst=output_writer)

    def pytest_testnodedown(self, node: "WorkerController", error: Any):
        if workeroutput := getattr(node, "workeroutput", None):
            worker_id = node.workerinfo["id"]
            if worker_timing := self.worker_timings.get(worker_id, None):
                # time since setup nodes was invoked
                worker_timing.runtime = self.setup_nodes_timer.elapsed
                self.output.add_timing(worker_timing)

            if output_path := workeroutput.get(_worker_output_key, None):
                self.worker_output_files.append(Path(output_path))
