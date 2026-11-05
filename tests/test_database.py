import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

import pytest

from zava_mcp_server.database import (
    SalesQueryError,
    SalesQueryTimeoutError,
    SalesRepository,
)
from zava_mcp_server.models import ProductSales, SalesQuery

QUERY = SalesQuery(1, date(2025, 1, 1), date(2025, 1, 31), 10)
ROW = {"product_id": 8, "product_name": "Example", "total_amount": Decimal("125.30")}
SECRET = "FAKE_DRIVER_SECRET"


class ProbePool:
    def __init__(self, rows=(), failure=None, stage=None):
        self.events = []
        self.rows = rows
        self.failure = failure
        self.stage = stage

    @asynccontextmanager
    async def acquire(self, *, timeout):
        self.events.append(("acquire", timeout))
        try:
            yield self
        finally:
            self.events.append("release")
            if self.stage == "release":
                raise self.failure

    @asynccontextmanager
    async def transaction(self, *, readonly):
        self.events.append(("begin", readonly))
        try:
            yield
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
            if self.stage == "commit":
                raise self.failure

    async def fetchval(self, sql, *args):
        assert "set_config('app.current_store_id', $1, true)" in sql
        self.events.append(("scope", args))

    async def fetch(self, sql, *args):
        self.events.append(("aggregate", args))
        if self.stage == "query":
            raise self.failure
        return self.rows


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows, expected",
    [([], []), ([ROW], [ProductSales(8, "Example", Decimal("125.30"))])],
)
async def test_returns_rows_after_transaction_and_release(rows, expected):
    pool = ProbePool(rows)
    actual = await SalesRepository(pool, 0.5).top_products(QUERY)
    assert actual == expected
    if actual:
        assert actual[0].total_amount.as_tuple() == Decimal("125.30").as_tuple()
    assert pool.events == [
        ("acquire", 0.5),
        ("begin", True),
        ("scope", ("1",)),
        ("aggregate", (1, QUERY.start_date, QUERY.end_date, 10)),
        "commit",
        "release",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage, error, expected",
    [
        ("query", OSError(SECRET), SalesQueryError),
        ("query", TimeoutError(SECRET), SalesQueryTimeoutError),
        ("query", asyncio.CancelledError(), asyncio.CancelledError),
        ("commit", OSError(SECRET), SalesQueryError),
        ("release", OSError(SECRET), SalesQueryError),
    ],
)
async def test_failure_propagates_after_cleanup(stage, error, expected):
    pool = ProbePool([ROW], error, stage)
    with pytest.raises(expected) as caught:
        await SalesRepository(pool, 0.5).top_products(QUERY)
    assert pool.events[-2:] == ["rollback" if stage == "query" else "commit", "release"]
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    if isinstance(error, asyncio.CancelledError):
        assert caught.value is error
    pool.stage = None
    assert len(await SalesRepository(pool, 0.5).top_products(QUERY)) == 1
