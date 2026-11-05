"""서버 수명 동안 공유할 DB 풀의 준비 확인과 정리를 담당한다."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol, cast

import asyncpg  # type: ignore[import-untyped]  # 드라이버 경계는 아래 Protocol로 한정한다.

from .settings import Settings

logger = logging.getLogger(__name__)
READER_ROLE = "zava_mcp_reader"


class Connection(Protocol):
    """준비 확인에 필요한 드라이버 인터페이스."""

    async def fetchval(
        self, query: str, *args: object, timeout: float | None = None
    ) -> object: ...


class Pool(Protocol):
    """공유 풀을 사용하는 코드에 제공하는 드라이버 인터페이스."""

    def acquire(
        self, *, timeout: float | None = None
    ) -> AbstractAsyncContextManager[Connection]: ...

    async def close(self) -> None: ...

    def terminate(self) -> None: ...


@dataclass(frozen=True)
class RuntimeContext:
    """JSON 데이터가 아닌, 실행 중인 공유 자원과 연결 대여 설정."""

    pool: Pool
    acquire_timeout: float


@dataclass
class RuntimeStatus:
    """SDK가 시작 실패를 처리한 뒤에도 진입점이 종료 코드를 판단할 근거."""

    started: bool = False


class RuntimeStartupError(RuntimeError):
    """DB 원본 예외와 입력값을 포함하지 않는 시작 오류."""


async def _create_pool(settings: Settings) -> Pool:
    """asyncpg 0.32는 초기화 실패·취소 시 이미 만든 연결도 정리한다."""
    return cast(
        Pool,
        await asyncpg.create_pool(
            host=settings.db.host,
            port=settings.db.port,
            database=settings.db.database,
            user=settings.db.user,
            password=settings.db.password.get_secret_value(),
            min_size=settings.pool.min_size,
            max_size=settings.pool.max_size,
            timeout=settings.pool.connect_timeout,
            command_timeout=settings.pool.query_timeout,
        ),
    )


async def _check_ready(pool: Pool, settings: Settings) -> None:
    """행 존재 여부와 무관하게 실제 계정과 orders 조회 가능 여부를 확인한다."""
    async with pool.acquire(timeout=settings.pool.acquire_timeout) as connection:
        expected_role = await connection.fetchval(
            "SELECT current_user::text = $1 AND session_user::text = $1",
            READER_ROLE,
            timeout=settings.pool.query_timeout,
        )
        if expected_role is not True:
            raise RuntimeStartupError("조회 계정이 일치하지 않습니다")
        await connection.fetchval(
            "SELECT order_id FROM retail.orders LIMIT 1",
            timeout=settings.pool.query_timeout,
        )


async def _close_pool(pool: Pool, timeout: float) -> None:
    """종료 대기를 제한하고 정상 종료와 강제 정리를 구분한다."""
    try:
        async with asyncio.timeout(timeout):
            await pool.close()
    except TimeoutError:
        pool.terminate()
        logger.warning("DB 풀 강제 정리 완료: 종료 시간 초과")
    except asyncio.CancelledError:
        pool.terminate()
        logger.warning("DB 풀 강제 정리 완료: 종료 취소")
        raise
    except Exception:
        pool.terminate()
        logger.error("DB 풀 강제 정리 완료: 종료 오류")
    else:
        logger.info("DB 풀 정상 종료 완료")


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncGenerator[RuntimeContext, None]:
    """준비 성공 후에만 공유 자원을 제공하고 모든 종료 경로에서 정리한다."""
    pool: Pool | None = None
    phase = "DB 연결 풀 생성"
    try:
        try:
            if settings.db.user != READER_ROLE:
                raise RuntimeStartupError("조회 계정 설정이 일치하지 않습니다")
            pool = await _create_pool(settings)
            phase = "DB 준비 확인"
            await _check_ready(pool, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            message = f"{phase} 실패: 조회 계정과 DB 설정을 확인하세요"
            logger.error(message)
            raise RuntimeStartupError(message) from None

        logger.info("DB 준비 완료: 조회 계정 및 orders 조회 확인")
        yield RuntimeContext(pool=pool, acquire_timeout=settings.pool.acquire_timeout)
    finally:
        if pool is not None:
            await _close_pool(pool, settings.pool.shutdown_timeout)
