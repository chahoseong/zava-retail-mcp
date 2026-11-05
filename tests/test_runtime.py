"""실제 DB를 변경하지 않는 풀 수명주기·준비 확인 테스트."""

import asyncio
import logging
import traceback
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock

import pytest

from zava_mcp_server import __main__ as entrypoint
from zava_mcp_server import runtime
from zava_mcp_server.models import SalesQuery
from zava_mcp_server.settings import SettingsError, load_settings

SECRET = "FAKE_RUNTIME_SECRET"


@pytest.fixture
def settings():
    return load_settings(
        {
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "zava",
            "POSTGRES_USER": "zava_mcp_reader",
            "POSTGRES_PASSWORD": SECRET,
            "DEV_USER_FILE": "config/dev-user.example.json",
            "DB_POOL_MIN_SIZE": "0",
            "DB_POOL_MAX_SIZE": "2",
            "DB_CONNECT_TIMEOUT": ".2",
            "DB_ACQUIRE_TIMEOUT": ".3",
            "DB_QUERY_TIMEOUT": ".4",
            "DB_SHUTDOWN_TIMEOUT": ".01",
        }
    )


class FakePool:
    def __init__(self, *, role=True, row=None, failure=None, close_mode="normal"):
        self.role = role
        self.row = row
        self.failure = failure
        self.close_mode = close_mode
        self.queries = []
        self.acquire_timeout = None
        self.acquired = 0
        self.released = 0
        self.closed = False
        self.terminated = False

    @asynccontextmanager
    async def acquire(self, *, timeout):
        self.acquire_timeout = timeout
        self.acquired += 1
        try:
            yield self
        finally:
            self.released += 1

    async def fetchval(self, query, *args, timeout=None):
        self.queries.append((query, args, timeout))
        if len(self.queries) == 1:
            return self.role
        if self.failure is not None:
            raise self.failure
        return self.row

    @asynccontextmanager
    async def transaction(self, *, readonly):
        assert readonly
        yield

    async def fetch(self, query, *args):
        return []

    async def close(self):
        assert self.acquired == self.released
        if self.close_mode == "timeout":
            await asyncio.Event().wait()
        elif self.close_mode == "error":
            raise OSError(SECRET)
        elif self.close_mode == "cancel":
            raise asyncio.CancelledError
        self.closed = True

    def terminate(self):
        self.terminated = True


@pytest.mark.asyncio
@pytest.mark.parametrize("row", [None, 42])
async def test_ready_shares_pool_and_returns_connection(settings, monkeypatch, row):
    pool = FakePool(row=row)
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr(runtime, "_create_pool", factory)

    async with runtime.open_runtime(settings) as context:
        assert context.pool is pool
        assert context.acquire_timeout == 0.3
        assert pool.acquired == pool.released == 1
        assert pool.acquire_timeout == 0.3
        assert all(timeout == 0.4 for _, _, timeout in pool.queries)
        assert pool.queries[0][1] == ("zava_mcp_reader",)
        assert "current_user" in pool.queries[0][0]
        assert "session_user" in pool.queries[0][0]
        assert [
            query.split("FROM ")[1].split()[0] for query, _, _ in pool.queries[1:]
        ] == ["retail.orders", "retail.order_items", "retail.products"]
        assert not pool.closed

    factory.assert_awaited_once_with(settings)
    assert pool.closed and not pool.terminated


@pytest.mark.asyncio
async def test_driver_receives_connection_and_pool_limits(settings, monkeypatch):
    pool = FakePool()
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr(runtime.asyncpg, "create_pool", factory)
    assert await runtime._create_pool(settings) is pool
    factory.assert_awaited_once_with(
        host="127.0.0.1",
        port=5432,
        database="zava",
        user="zava_mcp_reader",
        password=SECRET,
        min_size=0,
        max_size=2,
        timeout=0.2,
        command_timeout=0.4,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [False, None, "zava_mcp_reader"])
async def test_unexpected_actual_role_prevents_ready(settings, monkeypatch, role):
    pool = FakePool(role=role)
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(runtime.RuntimeStartupError):
        async with runtime.open_runtime(settings):
            pytest.fail("준비에 실패한 풀을 제공하면 안 됩니다")
    assert len(pool.queries) == 1
    assert pool.acquired == pool.released == 1
    assert pool.closed


@pytest.mark.asyncio
async def test_configured_admin_is_rejected_before_connect(settings, monkeypatch):
    factory = AsyncMock()
    monkeypatch.setattr(runtime, "_create_pool", factory)
    settings = settings.model_copy(
        update={"db": settings.db.model_copy(update={"user": "postgres"})}
    )
    with pytest.raises(runtime.RuntimeStartupError):
        async with runtime.open_runtime(settings):
            pytest.fail("관리자 계정으로 시작하면 안 됩니다")
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [OSError(SECRET), TimeoutError(SECRET)])
async def test_connect_failure_is_safe(settings, monkeypatch, caplog, error):
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(side_effect=error))
    with pytest.raises(runtime.RuntimeStartupError) as caught:
        async with runtime.open_runtime(settings):
            pytest.fail("접속 실패 시 시작하면 안 됩니다")
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [PermissionError(SECRET), TimeoutError(SECRET)])
async def test_query_failure_returns_connection_and_closes_pool(
    settings, monkeypatch, caplog, error
):
    pool = FakePool(failure=error)
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(runtime.RuntimeStartupError) as caught:
        async with runtime.open_runtime(settings):
            pytest.fail("테이블 확인 실패 시 시작하면 안 됩니다")
    assert pool.acquired == pool.released == 1
    assert pool.closed
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_acquire_timeout_closes_pool(settings, monkeypatch):
    class UnavailablePool(FakePool):
        @asynccontextmanager
        async def acquire(self, *, timeout):
            assert timeout == 0.3
            raise TimeoutError(SECRET)
            yield  # pragma: no cover

    pool = UnavailablePool()
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(runtime.RuntimeStartupError):
        async with runtime.open_runtime(settings):
            pytest.fail("연결 대여 실패 시 시작하면 안 됩니다")
    assert pool.closed


@pytest.mark.asyncio
async def test_release_failure_still_closes_pool(settings, monkeypatch):
    class ReleaseFailurePool(FakePool):
        @asynccontextmanager
        async def acquire(self, *, timeout):
            async with super().acquire(timeout=timeout) as connection:
                yield connection
            raise OSError(SECRET)

    pool = ReleaseFailurePool()
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(runtime.RuntimeStartupError):
        async with runtime.open_runtime(settings):
            pytest.fail("연결 반환 실패 시 시작하면 안 됩니다")
    assert pool.closed


@pytest.mark.asyncio
async def test_startup_cancellation_is_preserved_and_cleans_pool(settings, monkeypatch):
    pool = FakePool(failure=asyncio.CancelledError())
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(asyncio.CancelledError):
        async with runtime.open_runtime(settings):
            pytest.fail("취소 이후 시작하면 안 됩니다")
    assert pool.released == 1 and pool.closed


@pytest.mark.asyncio
async def test_body_error_is_preserved_and_cleans_pool(settings, monkeypatch):
    pool = FakePool()
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    with pytest.raises(LookupError, match="request error"):
        async with runtime.open_runtime(settings):
            raise LookupError("request error")
    assert pool.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["normal", "timeout", "error", "cancel"])
async def test_shutdown_outcomes(settings, monkeypatch, caplog, mode):
    pool = FakePool(close_mode=mode)
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(return_value=pool))
    caplog.set_level(logging.INFO, logger=runtime.__name__)

    async def run():
        async with runtime.open_runtime(settings):
            pass

    if mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await run()
    else:
        await asyncio.wait_for(run(), timeout=1)
    if mode == "normal":
        assert pool.closed and not pool.terminated
        assert "정상 종료 완료" in caplog.text
    else:
        assert pool.terminated and not pool.closed
        assert "강제 정리 완료" in caplog.text
        assert "정상 종료 완료" not in caplog.text
    assert SECRET not in caplog.text


@pytest.mark.asyncio
async def test_server_factory_is_lazy_and_lifespan_publishes_context(
    settings, monkeypatch
):
    pool = FakePool()
    factory = AsyncMock(return_value=pool)
    monkeypatch.setattr(runtime, "_create_pool", factory)
    status = runtime.RuntimeStatus()
    server = entrypoint.build_server(settings, status)
    factory.assert_not_called()
    assert not status.started
    async with server.settings.lifespan(server) as context:
        assert status.started
        assert context.user is settings.user
        assert (
            await context.service.top_products(
                context.user, SalesQuery(1, date(2025, 1, 1), date(2025, 1, 1), 1)
            )
            == []
        )
        assert pool.acquired == pool.released == 2
    factory.assert_awaited_once_with(settings)
    assert pool.closed


@pytest.mark.parametrize("sdk_exit", [None, 3])
def test_entrypoint_returns_failure_when_sdk_handles_startup_error(
    settings, monkeypatch, caplog, sdk_exit
):
    monkeypatch.setattr(entrypoint, "load_settings", lambda: settings)
    monkeypatch.setattr(runtime, "_create_pool", AsyncMock(side_effect=OSError(SECRET)))

    def sdk_run(server, **kwargs):
        async def start():
            with pytest.raises(runtime.RuntimeStartupError):
                async with server.settings.lifespan(server):
                    pytest.fail("시작 실패 시 요청을 받으면 안 됩니다")

        asyncio.run(start())
        if sdk_exit is not None:
            raise SystemExit(sdk_exit)

    from mcp.server import MCPServer

    monkeypatch.setattr(MCPServer, "run", sdk_run)
    assert entrypoint.main() == 1
    assert SECRET not in caplog.text


@pytest.mark.parametrize("action", ["orders:count", "sales:unknown"])
def test_settings_rejects_unrecognized_sales_permission(tmp_path, action):
    path = tmp_path / "user.json"
    path.write_text(
        '{"user_id":"test","allowed_actions":["'
        + action
        + '"],"allowed_store_ids":[1]}',
        encoding="utf-8",
    )
    with pytest.raises(SettingsError):
        load_settings(
            {
                "POSTGRES_HOST": "127.0.0.1",
                "POSTGRES_PORT": "5432",
                "POSTGRES_DB": "zava",
                "POSTGRES_USER": "zava_mcp_reader",
                "POSTGRES_PASSWORD": SECRET,
                "DEV_USER_FILE": str(path),
            }
        )
