import typing

import pydantic
from typing import Union
from .data import (
    GCTiming,
    CollectionTiming,
    WorkerTiming,
    MockTiming,
    TestTiming,
    FixtureTiming,
    DjangoSQLTiming,
)

Timing = typing.Annotated[
    Union[
        GCTiming,
        CollectionTiming,
        WorkerTiming,
        MockTiming,
        TestTiming,
        FixtureTiming,
        DjangoSQLTiming,
    ],
    pydantic.Field(discriminator="type"),
]

TimingAdapter = pydantic.TypeAdapter(Timing)
