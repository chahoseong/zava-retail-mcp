import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

import anyio
import pytest

from zava_mcp_server.database import (
    SalesQueryError,
    SalesQueryTimeoutError,
    SalesRepository,
)
from zava_mcp_server.models import (
    ProductSales,
    SalesQuery,
    SalesSummary,
    SalesSummaryQuery,
)

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
async def test_sales_summary_uses_store_scope_and_returns_aggregate():
    query = SalesSummaryQuery(1, QUERY.start_date, QUERY.end_date)
    pool = ProbePool([{"total_sales": Decimal("125.30"), "order_count": 2}])
    result = await SalesRepository(pool, 0.5).sales_summary(query)
    assert result == SalesSummary(Decimal("125.30"), 2)
    assert pool.events == [
        ("acquire", 0.5),
        ("begin", True),
        ("scope", ("1",)),
        ("aggregate", (1, QUERY.start_date, QUERY.end_date)),
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


@pytest.mark.asyncio
async def test_sdk_cancel_scope_allows_rollback_and_release_to_await():
    running = anyio.Event()

    class CancellablePool(ProbePool):
        @asynccontextmanager
        async def acquire(self, *, timeout):
            async with super().acquire(timeout=timeout) as connection:
                try:
                    yield connection
                finally:
                    await anyio.sleep(0)
                    self.events.append("release-ready")

        @asynccontextmanager
        async def transaction(self, *, readonly):
            async with super().transaction(readonly=readonly):
                try:
                    yield
                finally:
                    await anyio.sleep(0)
                    self.events.append("rollback-ready")

        async def fetch(self, sql, *args):
            running.set()
            await anyio.sleep_forever()

    pool = CancellablePool()
    async with anyio.create_task_group() as group:
        group.start_soon(SalesRepository(pool, 0.5).top_products, QUERY)
        with anyio.fail_after(1):
            await running.wait()
        group.cancel_scope.cancel()

    assert pool.events[-4:] == [
        "rollback-ready",
        "rollback",
        "release-ready",
        "release",
    ]
